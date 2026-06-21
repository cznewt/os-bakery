"""Serve a node's salt pillar over HTTP — for a Salt master's external pillar.

A Salt master can pull each minion's pillar from os-bakery instead of carrying
a static copy, using the built-in ``salt.pillar.http_json`` external pillar.
Point the master at this view::

    ext_pillar:
      - http_json:
          url: http://os-bakery.example/pillar/%s
          username: salt
          password: <SALT_PILLAR_PASSWORD>

Salt replaces ``%s`` with the minion id, GETs the URL, and merges the returned
JSON into that minion's pillar at the top level. The body is exactly the pillar
a bake writes for the node — :pyattr:`tenants.models.Node.effective_model` minus
the os-bakery-internal keys (:data:`builds.orchestrator.NON_PILLAR_KEYS`) — so a
master-driven highstate and an os-bakery bake see the same pillar.

The same :func:`node_pillar` serializer backs the ``render_salt_pillar``
management command, which emits these fragments as a static ``ext_pillar``
block for the Kapitan salt model (the offline counterpart to this live view).
"""

from __future__ import annotations

import base64
import hmac

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from tenants.models import Node


def node_pillar(node: Node) -> dict:
    """The salt pillar for ``node``: its effective model minus os-bakery keys.

    Identical to what the bake serialises (``builds.orchestrator`` drops the
    same keys before writing the minion pillar), so the live ext_pillar and a
    masterless bake stay in lock-step. Imported lazily to avoid a load-time
    ``tenants`` ↔ ``builds`` import cycle.
    """
    from builds.orchestrator import NON_PILLAR_KEYS

    model = node.effective_model or {}
    return {k: v for k, v in model.items() if k not in NON_PILLAR_KEYS}


def resolve_node(minion_id: str) -> Node | None:
    """Find the active node whose **salt minion id** is ``minion_id``.

    The salt minion id is the node's effective ``salt.id`` — which os-bakery
    pins in ``node.parameters['salt']['id']`` (and which typically equals the
    slug), **not** the hostname. Match, in priority order: an explicit
    ``salt.id`` in the node parameters, then the slug, then the hostname (the
    latter two cover nodes that leave ``salt.id`` defaulting to their
    ``minion_id``). A node never inherits a *usable* ``salt.id`` purely from its
    cluster (that would be non-unique), so these three lookups are exhaustive —
    and stay cheap (indexed) for the unknown-minion case that returns ``{}``.
    """
    qs = Node.objects.filter(is_active=True)
    return (
        qs.filter(parameters__salt__id=minion_id).first()
        or qs.filter(slug=minion_id).first()
        or qs.filter(hostname=minion_id).first()
    )


def _authorized(request: HttpRequest) -> bool:
    """Validate HTTP Basic credentials against the configured pillar secret.

    Enforced only when ``SALT_PILLAR_PASSWORD`` is set — with no password
    configured the endpoint is open (dev-insecure default). Constant-time
    comparison avoids leaking the credential via timing.
    """
    want_pw = settings.SALT_PILLAR_PASSWORD
    if not want_pw:
        return True
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.startswith("Basic "):
        return False
    try:
        user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    want_user = settings.SALT_PILLAR_USERNAME or ""
    return hmac.compare_digest(user, want_user) and hmac.compare_digest(pw, want_pw)


def pillar_json(request: HttpRequest, minion_id: str) -> HttpResponse:
    """Return the merged salt pillar for ``minion_id`` as JSON.

    Shaped for ``salt.pillar.http_json``. Unknown minions get an empty object
    with 200 (not 404): the master then merges nothing for nodes os-bakery does
    not manage, and http_json stays quiet instead of logging an error each
    pillar render.
    """
    if not _authorized(request):
        resp = HttpResponse(status=401)
        resp["WWW-Authenticate"] = 'Basic realm="os-bakery pillar"'
        return resp
    node = resolve_node(minion_id)
    if node is None:
        return JsonResponse({})
    return JsonResponse(node_pillar(node))
