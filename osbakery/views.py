"""Public-facing views for the os-bakery landing page.

Lives in `osbakery/` (the project) rather than under any single app because
these views compose data from `catalog` + `recipes` + `builds`.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.files.storage import storages
from django.db.models import Count, Prefetch
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from builds.models import BuildRequest
from catalog.models import (
    HardwareTarget,
    OperatingSystem,
    OSRelease,
    UpstreamImage,
    WireguardPeer,
)
from recipes.models import Recipe
from tenants.models import Cluster, Node


# simple-icons.org serves a public, versioned CDN of brand SVGs. Each entry
# is a slug + an optional accent hex used as both the SVG fill and the card
# accent. Batocera isn't on simple-icons; we fall back to a styled letter
# avatar rendered in the template.
OS_LOGOS: dict[str, dict[str, str]] = {
    "batocera": {
        "fallback_letter": "B",
        "accent": "#1f6feb",
    },
    "ubuntu": {
        "svg": "https://cdn.simpleicons.org/ubuntu/e95420",
        "accent": "#e95420",
    },
    "debian": {
        "svg": "https://cdn.simpleicons.org/debian/a81d33",
        "accent": "#a81d33",
    },
    "raspios": {
        "svg": "https://cdn.simpleicons.org/raspberrypi/c51a4a",
        "accent": "#c51a4a",
    },
    "haos": {
        "svg": "https://cdn.simpleicons.org/homeassistant/18bcf2",
        "accent": "#18bcf2",
    },
    "omarchy": {
        "fallback_letter": "O",
        "accent": "#111827",
    },
    "popos": {
        "svg": "https://cdn.simpleicons.org/popos/48b9c7",
        "accent": "#48b9c7",
    },
    "l4t": {
        "svg": "https://cdn.simpleicons.org/nvidia/76b900",
        "accent": "#76b900",
    },
    "kali": {
        "svg": "https://cdn.simpleicons.org/kalilinux/557c94",
        "accent": "#557c94",
    },
    "proxmox-ve": {
        "svg": "https://cdn.simpleicons.org/proxmox/e57000",
        "accent": "#e57000",
    },
    "esphome": {
        "svg": "https://cdn.simpleicons.org/esphome/000000",
        "accent": "#000000",
    },
    "windows": {
        "svg": "https://cdn.simpleicons.org/windows11/0078d4",
        "accent": "#0078d4",
    },
    "android": {
        "svg": "https://cdn.simpleicons.org/android/3ddc84",
        "accent": "#3ddc84",
    },
}


# The effective model carries two conceptual sets. Image metadata describes the
# artifact itself — hardware identity, build/osbakery identity, the role it
# implements and the per-build options (hostname/minion id). Everything else is
# provisioner metadata — the pillar the provisioner (salt/…) consumes.
_IMAGE_MODEL_KEYS = {"device", "osbakery", "role", "options"}


def _split_model(model: dict) -> tuple[dict, dict]:
    """Partition an effective model into (image_metadata, provisioner_metadata)."""
    image = {k: v for k, v in (model or {}).items() if k in _IMAGE_MODEL_KEYS}
    provisioner = {k: v for k, v in (model or {}).items() if k not in _IMAGE_MODEL_KEYS}
    return image, provisioner


def home(request: HttpRequest) -> HttpResponse:
    """Landing page — a grid of OS cards plus a few aggregate stats."""

    oses = list(
        OperatingSystem.objects.filter(is_active=True)
        .annotate(n_releases=Count("releases", distinct=True))
        .prefetch_related(
            Prefetch(
                "releases",
                queryset=OSRelease.objects.filter(is_default=True),
                to_attr="default_releases",
            ),
        )
        .order_by("kind", "name")
    )

    # Compute hardware-target counts per OS — one query for all of them.
    target_counts: dict[int, int] = {}
    image_counts: dict[int, int] = {}

    for row in (
        UpstreamImage.objects.values("release__operating_system_id")
        .annotate(
            n_images=Count("id"),
            n_targets=Count("hardware_target", distinct=True),
        )
    ):
        os_id = row["release__operating_system_id"]
        image_counts[os_id] = row["n_images"]
        target_counts[os_id] = row["n_targets"]

    cards = []
    for os_ in oses:
        logo = OS_LOGOS.get(os_.slug, {})
        default = os_.default_releases[0] if os_.default_releases else None
        cards.append(
            {
                "id": os_.id,
                "slug": os_.slug,
                "name": os_.name,
                "vendor": os_.vendor,
                "kind": os_.get_kind_display(),
                "summary": os_.summary,
                "logo_svg": logo.get("svg"),
                "logo_letter": logo.get("fallback_letter", os_.name[:1].upper()),
                "accent": logo.get("accent", "#6b7280"),
                "n_releases": os_.n_releases,
                "n_targets": target_counts.get(os_.id, 0),
                "n_images": image_counts.get(os_.id, 0),
                "default_release": default,
                "homepage": os_.homepage,
            }
        )

    context = {
        "cards": cards,
        "stats": {
            "n_oses": len(cards),
            "n_targets_total": HardwareTarget.objects.count(),
            "n_releases_total": OSRelease.objects.count(),
            "n_images_total": sum(image_counts.values()),
        },
    }
    return render(request, "home.html", context)


_SBC_SLUGS = {
    "pc-arm64",
    "beaglebone-black", "beaglebone-blue",
    "jetson-nano", "jetson-xavier-nx", "jetson-orin-nano",
}


def _categorize_target(slug: str, arch_slug: str = "") -> str:
    if slug.startswith("rpi"):
        return "rpi"
    if slug.startswith("vm-"):
        return "vm"
    if slug == "pc-amd64":
        return "pc"
    if slug in _SBC_SLUGS:
        return "sbc"
    # ESP / microcontroller targets all live on Xtensa or RISC-V 32-bit.
    if arch_slug in {"xtensa", "riscv32"}:
        return "mcu"
    return "handheld"


# Per-prefix brand mark for targets that don't have a real product photo
# yet. Either a simple-icons.org brand slug (rendered to SVG by the CDN) or
# a direct URL to a Wikipedia Commons file when simple-icons doesn't carry
# the brand. The accent hex feeds the card background gradient.
_BRAND_LOGO_BY_PREFIX: list[tuple[str, str, str]] = [
    # (slug-prefix, brand-logo URL, accent hex)
    # Single-board computers
    ("rpi",         "https://cdn.simpleicons.org/raspberrypi/c51a4a",  "c51a4a"),
    ("jetson-",     "https://cdn.simpleicons.org/nvidia/76b900",       "76b900"),
    ("beaglebone-", "https://www.beagleboard.org/img/beagleboard-logo.svg", "990000"),
    # ESP / microcontroller — Espressif is the common chip vendor.
    ("esp32",       "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("esp8266",     "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("ai-thinker",  "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("athom",       "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("laskakit",    "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("m5stack",     "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("shelly",      "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("sonoff",      "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("ulanzi",      "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("weber",       "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    ("wemos",       "https://cdn.simpleicons.org/espressif/e7352c",    "e7352c"),
    # Retro handhelds — Anbernic logo from Wikipedia (no simple-icons brand).
    ("rg",          "https://upload.wikimedia.org/wikipedia/commons/thumb/1/10/Anbernic_logo.png/500px-Anbernic_logo.png", "1f6feb"),
    ("loki-",       "https://upload.wikimedia.org/wikipedia/commons/thumb/1/10/Anbernic_logo.png/500px-Anbernic_logo.png", "1f6feb"),
    ("flip-",       "https://upload.wikimedia.org/wikipedia/commons/thumb/1/10/Anbernic_logo.png/500px-Anbernic_logo.png", "1f6feb"),
    ("pocket-",     "",  "1f6feb"),  # Retroid — no public logo on the CDNs we trust
    ("ayn-",        "",  "1f6feb"),  # AYN — same
    # PC / VM hypervisor brands.
    ("vm-virtualbox","https://cdn.simpleicons.org/virtualbox/183a61",  "183a61"),
    ("vm-qemu",     "https://cdn.simpleicons.org/qemu/ff6600",         "ff6600"),
    ("vm-hyperv",   "https://cdn.simpleicons.org/microsoft/0078d4",    "0078d4"),
    ("pc-amd64",    "https://cdn.simpleicons.org/intel/0071c5",        "0071c5"),
    ("pc-arm64","https://cdn.simpleicons.org/arm/0091bd",         "0091bd"),
    # Mobile (Android phones / tablets)
    ("phone-",      "https://cdn.simpleicons.org/android/3ddc84",       "3ddc84"),
    ("tablet-",     "https://cdn.simpleicons.org/android/3ddc84",       "3ddc84"),
]


def _brand_logo_for(slug: str) -> tuple[str, str]:
    """Return (svg_url, accent_hex) for a target's vendor brand mark.

    Returns ("", "") when no brand maps — template falls back to the
    slug-typography card-top.
    """
    for prefix, url, accent in _BRAND_LOGO_BY_PREFIX:
        if slug.startswith(prefix):
            return (url, f"#{accent}")
    return ("", "")


# Targets that share a single multi-device collage as their photo. Each
# slug maps to a (bg-x%, bg-y%) CSS background-position pair so the card
# shows only its quadrant. Empty for now — add an entry when a real
# collage photo lands.
SHARED_IMAGE_CROPS: dict[str, tuple[str, str]] = {}


CATEGORY_ORDER: list[tuple[str, str, str]] = [
    # (key, label, accent)
    ("rpi", "Raspberry Pi", "#c51a4a"),
    ("pc", "PC / Laptop", "#0ea5e9"),
    ("sbc", "ARM SBC / Embedded", "#76b900"),
    ("handheld", "Retro handheld", "#8b5cf6"),
    ("mcu", "Microcontroller / ESP", "#000000"),
    ("vm", "Virtual machine", "#f59e0b"),
]


def devices(request: HttpRequest) -> HttpResponse:
    """Every HardwareTarget, grouped by category, with the OSes that support each."""

    targets = list(
        HardwareTarget.objects.select_related("architecture")
        .order_by("architecture__slug", "slug")
    )

    # One pass: collect per-target image count + the set of OSes that
    # actually have an image for that target.
    image_counts: dict[int, int] = {}
    target_oses: dict[int, set[tuple[str, str]]] = {}
    for img in (
        UpstreamImage.objects
        .select_related("release__operating_system")
        .only(
            "hardware_target_id",
            "release__operating_system__slug",
            "release__operating_system__name",
        )
    ):
        image_counts[img.hardware_target_id] = (
            image_counts.get(img.hardware_target_id, 0) + 1
        )
        target_oses.setdefault(img.hardware_target_id, set()).add(
            (img.release.operating_system.slug,
             img.release.operating_system.name)
        )

    cards_by_category: dict[str, list[dict]] = {}
    for t in targets:
        oses_for_target = sorted(target_oses.get(t.id, set()))
        brand_svg, brand_accent = _brand_logo_for(t.slug)
        crop = SHARED_IMAGE_CROPS.get(t.slug)
        cards_by_category.setdefault(
            _categorize_target(t.slug, t.architecture.slug), []
        ).append({
            "slug": t.slug,
            "name": t.name,
            "arch": t.architecture.slug,
            "boot": t.boot_method,
            "soc": t.soc,
            "notes": t.notes,
            "image_url": t.image_url,
            "image_crop_x": crop[0] if crop else "",
            "image_crop_y": crop[1] if crop else "",
            "brand_svg": brand_svg,
            "brand_accent": brand_accent,
            "is_active": t.is_active,
            "n_images": image_counts.get(t.id, 0),
            "oses": [
                {
                    "slug": slug,
                    "name": name,
                    "svg": OS_LOGOS.get(slug, {}).get("svg"),
                    "letter": OS_LOGOS.get(slug, {}).get(
                        "fallback_letter", name[:1].upper()
                    ),
                    "accent": OS_LOGOS.get(slug, {}).get("accent", "#6b7280"),
                }
                for slug, name in oses_for_target
            ],
        })

    sections = []
    for key, label, accent in CATEGORY_ORDER:
        cards = cards_by_category.get(key, [])
        if not cards:
            continue
        sections.append({
            "key": key,
            "label": label,
            "accent": accent,
            "cards": cards,
            "n_cards": len(cards),
            "n_images": sum(c["n_images"] for c in cards),
        })

    return render(request, "devices.html", {
        "sections": sections,
        "total_targets": len(targets),
        "total_images": sum(image_counts.values()),
    })


def base_images(request: HttpRequest) -> HttpResponse:
    """Every (OS, release, target, variant) upstream-image row, grouped by OS.

    Optional ``?os=<slug>`` query-string filter for a single OS at a time.
    """

    os_filter = request.GET.get("os") or ""

    images_qs = (
        UpstreamImage.objects
        .select_related(
            "release",
            "release__operating_system",
            "hardware_target",
            "hardware_target__architecture",
        )
        .prefetch_related("extra_targets")
        .order_by(
            "release__operating_system__name",
            "-release__released_on",
            "-release__version",
            "hardware_target__slug",
            "variant",
        )
    )
    if os_filter:
        images_qs = images_qs.filter(release__operating_system__slug=os_filter)

    # Group images for the template: list of (operating_system, list-of-images).
    groups: dict[str, dict] = {}
    for img in images_qs:
        os_obj = img.release.operating_system
        accent = OS_LOGOS.get(os_obj.slug, {}).get("accent", "#6b7280")
        bucket = groups.setdefault(
            os_obj.slug,
            {
                "os": os_obj,
                "accent": accent,
                "logo_svg": OS_LOGOS.get(os_obj.slug, {}).get("svg"),
                "logo_letter": OS_LOGOS.get(os_obj.slug, {}).get(
                    "fallback_letter", os_obj.name[:1].upper()
                ),
                "rows": [],
            },
        )
        bucket["rows"].append(img)

    context = {
        "groups": list(groups.values()),
        "all_operating_systems": OperatingSystem.objects.filter(is_active=True).order_by("name"),
        "selected_os": os_filter,
        "total_rows": sum(len(g["rows"]) for g in groups.values()),
    }
    return render(request, "base_images.html", context)


def download_base_image(request: HttpRequest, pk: int) -> HttpResponse:
    """Stream a mirrored upstream base image from the artifacts store.

    Only serves images that have been cached by `manage.py refresh_upstream`
    (``cache_storage_key`` set); upstream-only rows 404 — use their Source link.
    """
    img = get_object_or_404(
        UpstreamImage.objects.select_related("release__operating_system", "hardware_target"),
        pk=pk,
    )
    if not img.cache_storage_key:
        raise Http404("Image not mirrored yet — download it from its source URL.")
    storage = storages["artifacts"]
    if not storage.exists(img.cache_storage_key):
        raise Http404("Mirrored blob missing from the artifact store.")

    filename = img.cache_storage_key.rsplit("/", 1)[-1]
    response = FileResponse(
        storage.open(img.cache_storage_key, "rb"),
        as_attachment=True,
        filename=filename,
    )
    response["Content-Type"] = "application/octet-stream"
    if img.size_bytes:
        response["Content-Length"] = str(img.size_bytes)
    if img.checksum_sha256:
        response["X-Checksum-SHA256"] = img.checksum_sha256
    return response


def baked_images(request: HttpRequest) -> HttpResponse:
    """Actual baked output images (BuildRequests + their artifacts).

    Filterable via ?cluster=<slug>, ?os=<slug>, ?recipe=<slug>, ?status=<s> —
    the cluster cards on /clusters/ link here with ?cluster=… applied.
    """
    builds = (
        BuildRequest.objects.select_related(
            "recipe_version__recipe__operating_system",
            "hardware_target__architecture",
            "upstream_image__release__operating_system",
            "cluster__tenant",
            "tenant",
            "artifact",
        )
        .prefetch_related("artifact__tokens")
        .order_by("-queued_at")
    )
    f_cluster = request.GET.get("cluster") or ""
    f_os = request.GET.get("os") or ""
    f_recipe = request.GET.get("recipe") or ""
    f_status = request.GET.get("status") or ""
    if f_cluster:
        builds = builds.filter(cluster__slug=f_cluster)
    if f_os:
        builds = builds.filter(recipe_version__recipe__operating_system__slug=f_os)
    if f_recipe:
        builds = builds.filter(recipe_version__recipe__slug=f_recipe)
    if f_status:
        builds = builds.filter(status=f_status)

    def _fmt_duration(seconds: float | None) -> str:
        if not seconds or seconds < 0:
            return ""
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s // 60}m {s % 60}s"
        return f"{s // 3600}h {(s % 3600) // 60}m"

    rows = []
    for b in builds:
        art = getattr(b, "artifact", None)
        tok = art.tokens.first() if art else None
        up = b.upstream_image
        rel = up.release if up else None
        build_secs = (
            (b.finished_at - b.started_at).total_seconds()
            if b.started_at and b.finished_at else None
        )
        rows.append({
            "id": b.id,
            "recipe": b.recipe_version.recipe.slug,
            "os": b.recipe_version.recipe.operating_system.slug,
            "target": b.hardware_target.slug,
            "label": b.label,
            "cluster": (f"{b.cluster.tenant.slug}/{b.cluster.slug}" if b.cluster_id else None),
            "cluster_slug": b.cluster.slug if b.cluster_id else None,
            "status": b.status,
            "size_bytes": art.size_bytes if art else 0,
            "filename": art.filename if art else None,
            "token": tok.token if tok else None,
            "s3_url": art.public_url if art else "",
            "queued_at": b.queued_at,
            "finished_at": b.finished_at,
            "build_time": _fmt_duration(build_secs),
            # Base (upstream) image the artifact was baked from.
            "base_version": rel.version if rel else None,
            "base_codename": rel.codename if rel else "",
            "base_released_on": rel.released_on if rel else None,
            "base_channel": rel.get_channel_display() if rel else "",
            "base_variant": up.variant if up else "",
            "base_format": up.get_format_display() if up else "",
            "base_size_bytes": up.size_bytes if up else 0,
            "base_synced_at": up.last_synced_at if up else None,
            "base_source_url": up.source_url if up else "",
        })
    context = {
        "rows": rows,
        "total": len(rows),
        "f_cluster": f_cluster,
        "f_os": f_os,
        "f_recipe": f_recipe,
        "f_status": f_status,
    }
    return render(request, "baked_images.html", context)


@require_POST
def delete_baked_image(request: HttpRequest, build_id: str) -> HttpResponse:
    """Delete a baked image: its S3 blob + the BuildRequest (cascades artifact,
    events, download tokens)."""
    build = get_object_or_404(BuildRequest.objects.select_related("artifact"), pk=build_id)
    label = build.label or str(build.id)
    art = getattr(build, "artifact", None)
    if art and art.storage_key:
        try:
            storage = storages["artifacts"]
            if storage.exists(art.storage_key):
                storage.delete(art.storage_key)
        except Exception as exc:  # noqa: BLE001 — surface storage errors
            messages.error(request, f"Could not remove the S3 object: {exc}")
    build.delete()
    messages.success(request, f"Deleted baked image {label}.")
    return redirect("baked_images")


def build_log(request: HttpRequest, build_id: str) -> HttpResponse:
    """A baked image's build log — the BuildEvent timeline + captured output."""
    build = get_object_or_404(
        BuildRequest.objects.select_related(
            "recipe_version__recipe__operating_system",
            "hardware_target", "cluster__tenant", "artifact",
            "upstream_image__release__operating_system",
        ).prefetch_related("events", "artifact__tokens"),
        pk=build_id,
    )
    events = []
    for e in build.events.order_by("at"):
        data = e.data or {}
        events.append({
            "at": e.at,
            "phase": e.phase,
            "level": e.level,
            "message": e.message,
            "output": data.get("output_tail") or data.get("stdout_tail") or "",
        })
    art = getattr(build, "artifact", None)
    tok = art.tokens.first() if art else None

    # The effective model splits into two sets: image metadata (device +
    # osbakery identity) and provisioner metadata (the pillar the provisioner
    # applies — salt/batocera/options/…).
    import yaml as _yaml
    em = build.effective_model or {}
    image_model, prov_model = _split_model(em)
    image_yaml = (_yaml.safe_dump(image_model, sort_keys=False) if image_model else "")
    provisioner_yaml = (_yaml.safe_dump(prov_model, sort_keys=False) if prov_model else "")

    # Base (upstream) image metadata this artifact was baked from.
    up = build.upstream_image
    rel = up.release if up else None
    base = None
    if up and rel:
        base = {
            "os": rel.operating_system.slug,
            "version": rel.version,
            "codename": rel.codename,
            "channel": rel.get_channel_display(),
            "released_on": rel.released_on,
            "eol_on": rel.end_of_life_on,
            "variant": up.variant,
            "format": up.get_format_display(),
            "size_bytes": up.size_bytes,
            "checksum": up.checksum_sha256,
            "synced_at": up.last_synced_at,
            "source_url": up.source_url,
            "release_notes_url": rel.release_notes_url,
        }
    return render(request, "build_log.html", {
        "build": build,
        "events": events,
        "artifact": art,
        "token": tok.token if tok else None,
        "image_yaml": image_yaml,
        "provisioner_yaml": provisioner_yaml,
        "base": base,
        "s3_url": art.public_url if art else "",
    })


def clusters(request: HttpRequest) -> HttpResponse:
    """Clusters as cards; each links to baked images filtered to that cluster."""
    from django.db.models import Count, Q

    cluster_qs = (
        Cluster.objects.filter(is_active=True)
        .select_related("tenant")
        .annotate(
            baked=Count("build_requests", filter=Q(build_requests__artifact__isnull=False), distinct=True),
            builds=Count("build_requests", distinct=True),
            node_count=Count("nodes", filter=Q(nodes__is_active=True), distinct=True),
        )
        .order_by("tenant__name", "name")
    )
    from tenants.models import Tenant
    return render(request, "clusters.html", {
        "clusters": cluster_qs,
        "tenants": Tenant.objects.filter(is_active=True).order_by("name"),
    })


def provisioners(request: HttpRequest) -> HttpResponse:
    """List provisioners (Salt/Ansible/Cloud-Init), the states each can apply,
    and which recipes (presets) use them."""
    from catalog.models import Provisioner

    rows = []
    for p in (Provisioner.objects
              .prefetch_related("recipes__operating_system")
              .order_by("-is_default", "name")):
        states = p.available_states or []
        rows.append({
            "slug": p.slug,
            "name": p.name,
            "description": p.description,
            "is_default": p.is_default,
            "is_active": p.is_active,
            "states": states,
            "state_count": len(states),
            "recipes": [
                {"slug": r.slug, "name": r.name, "os": r.operating_system.slug}
                for r in p.recipes.all().order_by("name")
            ],
        })
    return render(request, "provisioners.html", {"provisioners": rows})


def cluster_detail(request: HttpRequest, slug: str) -> HttpResponse:
    """A single cluster's metadata (key-value parameters) + link to its bakes.

    The ``parameters`` JSON mirrors the salt-reclass deploy metadata (namespaces,
    nodes, per-deploy config); render it as a pretty key-value tree.
    """
    import yaml

    cluster = get_object_or_404(Cluster.objects.select_related("tenant"), slug=slug)
    params = cluster.parameters or {}
    # Render the metadata as YAML (it mirrors salt-reclass deploy data, which is
    # YAML natively). One block per top-level key so each is readable on its own.
    sections = []
    if isinstance(params, dict):
        for key in params:
            sections.append({
                "key": key,
                "yaml": yaml.safe_dump(
                    {key: params[key]}, sort_keys=False,
                    default_flow_style=False, allow_unicode=True,
                ).rstrip(),
            })
    full_yaml = yaml.safe_dump(
        params, sort_keys=False, default_flow_style=False, allow_unicode=True,
    ).rstrip() if params else ""
    baked = cluster.build_requests.filter(artifact__isnull=False).count()
    builds = cluster.build_requests.count()
    return render(request, "cluster_detail.html", {
        "cluster": cluster,
        "params": params,
        "sections": sections,
        "full_yaml": full_yaml,
        "param_count": len(params) if isinstance(params, dict) else 0,
        "baked": baked,
        "builds": builds,
        "tags_str": ", ".join(cluster.tags or []),
    })


@require_POST
def cluster_create(request: HttpRequest) -> HttpResponse:
    """Create a cluster from the form on /clusters/ (name, tenant, kind, YAML)."""
    import yaml
    from django.utils.text import slugify
    from tenants.models import Tenant

    name = (request.POST.get("name") or "").strip()
    slug = (request.POST.get("slug") or "").strip() or slugify(name)
    tenant_id = request.POST.get("tenant")
    raw = request.POST.get("metadata_yaml", "")
    if not name or not tenant_id:
        messages.error(request, "Name and tenant are required.")
        return redirect("clusters")
    try:
        parsed = yaml.safe_load(raw) or {}
        if not isinstance(parsed, dict):
            raise ValueError("metadata must be a mapping (key: value)")
    except (yaml.YAMLError, ValueError) as exc:
        messages.error(request, f"Invalid YAML — not created: {exc}")
        return redirect("clusters")
    if Cluster.objects.filter(slug=slug).exists():
        messages.error(request, f"A cluster with slug '{slug}' already exists.")
        return redirect("clusters")
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    tags = [t.strip() for t in (request.POST.get("tags") or "").split(",") if t.strip()]
    cluster = Cluster.objects.create(
        tenant=tenant, slug=slug, name=name, parameters=parsed,
        tags=tags, notes=request.POST.get("notes", ""),
    )
    messages.success(request, f"Created cluster {cluster.name}.")
    return redirect("cluster_detail", slug=cluster.slug)


@require_POST
def cluster_edit(request: HttpRequest, slug: str) -> HttpResponse:
    """Update all editable cluster params: slug, name, tags, notes,
    active, and the metadata (YAML)."""
    import yaml
    from django.utils.text import slugify

    cluster = get_object_or_404(Cluster, slug=slug)
    name = (request.POST.get("name") or "").strip()
    new_slug = slugify((request.POST.get("slug") or "").strip()) or cluster.slug
    notes = request.POST.get("notes", "")
    is_active = request.POST.get("is_active") == "on"
    tags = [t.strip() for t in (request.POST.get("tags") or "").split(",") if t.strip()]
    raw = request.POST.get("metadata_yaml", "")
    try:
        parsed = yaml.safe_load(raw) or {}
        if not isinstance(parsed, dict):
            raise ValueError("top-level metadata must be a mapping (key: value)")
    except (yaml.YAMLError, ValueError) as exc:
        messages.error(request, f"Invalid YAML — not saved: {exc}")
        return redirect("cluster_detail", slug=slug)
    # Slug is unique per tenant; guard against collisions on rename.
    if new_slug != cluster.slug and Cluster.objects.filter(
        tenant=cluster.tenant, slug=new_slug,
    ).exclude(pk=cluster.pk).exists():
        messages.error(request, f"Slug '{new_slug}' already exists in this tenant.")
        return redirect("cluster_detail", slug=slug)
    if name:
        cluster.name = name
    cluster.slug = new_slug
    cluster.notes = notes
    cluster.is_active = is_active
    cluster.tags = tags
    cluster.parameters = parsed
    cluster.save(update_fields=[
        "name", "slug", "notes", "is_active", "tags",
        "parameters", "updated_at",
    ])
    messages.success(request, f"Saved {cluster.name} ({len(parsed)} metadata keys).")
    return redirect("cluster_detail", slug=cluster.slug)


@require_POST
def cluster_delete(request: HttpRequest, slug: str) -> HttpResponse:
    """Remove a cluster. Its builds keep (FK is SET_NULL) but lose the link."""
    cluster = get_object_or_404(Cluster, slug=slug)
    name = cluster.name
    cluster.delete()
    messages.success(request, f"Removed cluster {name}.")
    return redirect("clusters")


def _parse_node_params(raw: str):
    """Parse a node's parameters YAML; returns (dict, error_message)."""
    import yaml
    try:
        parsed = yaml.safe_load(raw) or {}
        if not isinstance(parsed, dict):
            raise ValueError("parameters must be a mapping (key: value)")
        return parsed, None
    except (yaml.YAMLError, ValueError) as exc:
        return None, str(exc)


@require_POST
def node_create(request: HttpRequest) -> HttpResponse:
    """Create a node from the form on /nodes/."""
    from django.utils.text import slugify

    cluster_id = request.POST.get("cluster")
    preset_id = request.POST.get("preset")
    target_id = request.POST.get("hardware_target")
    name = (request.POST.get("name") or "").strip()
    slug = slugify((request.POST.get("slug") or "").strip() or name)
    if not (name and cluster_id and preset_id and target_id):
        messages.error(request, "Name, cluster, preset and hardware target are required.")
        return redirect("nodes")
    parsed, err = _parse_node_params(request.POST.get("parameters_yaml", ""))
    if err:
        messages.error(request, f"Invalid YAML — not created: {err}")
        return redirect("nodes")
    cluster = get_object_or_404(Cluster, pk=cluster_id)
    if Node.objects.filter(cluster=cluster, slug=slug).exists():
        messages.error(request, f"Node '{slug}' already exists in {cluster.slug}.")
        return redirect("nodes")
    tags = [t.strip() for t in (request.POST.get("tags") or "").split(",") if t.strip()]
    node = Node.objects.create(
        cluster=cluster, slug=slug, name=name,
        hostname=(request.POST.get("hostname") or "").strip(),
        preset_id=preset_id, hardware_target_id=target_id,
        parameters=parsed, tags=tags, notes=request.POST.get("notes", ""),
    )
    messages.success(request, f"Created node {node.slug}.")
    return redirect("node_detail", pk=node.pk)


@require_POST
def node_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Update a node's editable fields + parameters (YAML)."""
    from django.utils.text import slugify

    node = get_object_or_404(Node, pk=pk)
    cluster_id = request.POST.get("cluster") or node.cluster_id
    new_slug = slugify((request.POST.get("slug") or "").strip()) or node.slug
    name = (request.POST.get("name") or "").strip()
    parsed, err = _parse_node_params(request.POST.get("parameters_yaml", ""))
    if err:
        messages.error(request, f"Invalid YAML — not saved: {err}")
        return redirect("node_detail", pk=pk)
    if (new_slug != node.slug or str(cluster_id) != str(node.cluster_id)) and \
            Node.objects.filter(cluster_id=cluster_id, slug=new_slug).exclude(pk=node.pk).exists():
        messages.error(request, f"Node '{new_slug}' already exists in that cluster.")
        return redirect("node_detail", pk=pk)
    if name:
        node.name = name
    node.slug = new_slug
    node.cluster_id = cluster_id
    node.hostname = (request.POST.get("hostname") or "").strip()
    if request.POST.get("preset"):
        node.preset_id = request.POST.get("preset")
    if request.POST.get("hardware_target"):
        node.hardware_target_id = request.POST.get("hardware_target")
    node.is_active = request.POST.get("is_active") == "on"
    node.tags = [t.strip() for t in (request.POST.get("tags") or "").split(",") if t.strip()]
    node.notes = request.POST.get("notes", "")
    node.parameters = parsed
    node.save()
    messages.success(request, f"Saved node {node.slug}.")
    return redirect("node_detail", pk=node.pk)


@require_POST
def node_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Remove a node. Its builds keep (FK is SET_NULL) but lose the link."""
    node = get_object_or_404(Node, pk=pk)
    slug = node.slug
    node.delete()
    messages.success(request, f"Removed node {slug}.")
    return redirect("nodes")


@require_POST
def node_clone(request: HttpRequest, pk: int) -> HttpResponse:
    """Clone a node under a new name (same cluster/preset/target/params)."""
    from django.utils.text import slugify

    src = get_object_or_404(Node, pk=pk)
    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "Provide a name for the clone.")
        return redirect("nodes")
    slug = slugify((request.POST.get("slug") or "").strip() or name)
    if Node.objects.filter(cluster=src.cluster, slug=slug).exists():
        messages.error(request, f"Node '{slug}' already exists in {src.cluster.slug}.")
        return redirect("nodes")
    clone = Node.objects.create(
        cluster=src.cluster, slug=slug, name=name,
        hostname=slug,  # fresh per-node hostname / minion id
        preset=src.preset, hardware_target=src.hardware_target,
        upstream_image=src.upstream_image, parameters=src.parameters,
        tags=list(src.tags or []), notes=src.notes,
    )
    messages.success(request, f"Cloned {src.slug} → {clone.slug}.")
    return redirect("node_detail", pk=clone.pk)


@require_POST
def drop_base_image(request: HttpRequest, pk: int) -> HttpResponse:
    """Drop a base image's local sync — delete the mirrored blob from the
    artifact store and revert the row to 'remote'."""
    img = get_object_or_404(UpstreamImage, pk=pk)
    if not img.cache_storage_key:
        messages.error(request, "Not mirrored — nothing to drop.")
        return redirect("base_images")
    key = img.cache_storage_key
    storage = storages["artifacts"]
    try:
        if storage.exists(key):
            storage.delete(key)
    except Exception as exc:  # noqa: BLE001 - surface storage errors to the UI
        messages.error(request, f"Failed to remove the mirrored object: {exc}")
        return redirect("base_images")
    img.cache_storage_key = ""
    img.mirror_started_at = None
    img.last_synced_at = None
    img.save(update_fields=["cache_storage_key", "mirror_started_at", "last_synced_at"])
    messages.success(request, f"Dropped local sync for {img} — removed from the artifact store.")
    return redirect("base_images")


@require_POST
def sync_base_image(request: HttpRequest, pk: int) -> HttpResponse:
    """Queue a background job to mirror an upstream image into the artifact store.

    Enqueues ``catalog.tasks.mirror_upstream_image`` (runs on the packer worker)
    and redirects back to /images/. The row flips to "mirrored" once the job
    finishes and ``cache_storage_key`` is set.
    """
    img = get_object_or_404(
        UpstreamImage.objects.select_related("release__operating_system", "hardware_target"),
        pk=pk,
    )
    from catalog.tasks import mirror_upstream_image

    # Mark as syncing so the row flips from "remote" to "syncing" immediately
    # (persists across refresh until the job caches the blob or clears it).
    from django.utils import timezone
    UpstreamImage.objects.filter(pk=img.pk).update(mirror_started_at=timezone.now())

    mirror_upstream_image.delay(img.pk)
    messages.success(
        request,
        f"Queued mirror job for {img} — refresh in a few minutes (multi-GB pull).",
    )
    return redirect("base_images")


def _declared_zerotier_network_ids(node) -> list[str]:
    """Network ids declared for a node (cluster ⊕ node params), de-duped.

    Accepts the per-entry network key as ``network_id`` (preferred), ``network``,
    or the legacy ``id`` — mirroring ``splice_zerotier_identities``.
    """
    from tenants.models import _deep_merge

    params = _deep_merge(node.cluster.parameters or {}, node.parameters or {})
    nets = (params.get("zerotier") or {}).get("networks") or []
    ids: list[str] = []
    for entry in nets:
        if not isinstance(entry, dict):
            continue
        nid = entry.get("network_id") or entry.get("network") or entry.get("id")
        if nid and str(nid) not in ids:
            ids.append(str(nid))
    return ids


def _declared_wireguard_interfaces(node) -> list[dict]:
    """WireGuard interfaces declared for a node (cluster ⊕ node params).

    Returns the merged interface dicts in declared order, de-duped by ``name``
    (node params win over cluster). Mirrors ``_declared_zerotier_network_ids``.
    """
    from tenants.models import _deep_merge

    params = _deep_merge(node.cluster.parameters or {}, node.parameters or {})
    ifaces = (params.get("wireguard") or {}).get("interfaces") or []
    out: list[dict] = []
    seen: set[str] = set()
    for entry in ifaces:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(entry)
    return out


@require_POST
def generate_zerotier_identity(request: HttpRequest, pk: int) -> HttpResponse:
    """Prepopulate ZeroTier identities for a node's declared networks.

    Runs ``zerotier-idtool generate`` per network and upserts a
    :class:`tenants.models.ZerotierIdentity`. By default fills only networks that
    lack an identity; ``network_id=<id>`` targets one network and ``force=1``
    regenerates an existing one.
    """
    node = get_object_or_404(Node.objects.select_related("cluster"), pk=pk)
    from tenants.models import ZerotierIdentity
    from tenants.zerotier import IdtoolError, generate_identity

    target = (request.POST.get("network_id") or "").strip()
    force = request.POST.get("force") == "1"
    net_ids = [target] if target else _declared_zerotier_network_ids(node)
    if not net_ids:
        messages.warning(
            request,
            f"No ZeroTier networks declared on {node.slug} — add "
            "zerotier.networks to the cluster or node parameters first.",
        )
        return redirect("node_detail", pk=pk)

    made = kept = failed = 0
    for nid in net_ids:
        existing = ZerotierIdentity.objects.filter(node=node, network_id=nid).first()
        if existing and existing.member_id and not (force or target):
            kept += 1
            continue
        try:
            ident = generate_identity()
        except IdtoolError as exc:
            failed += 1
            messages.error(request, f"{nid}: {exc}")
            continue
        ZerotierIdentity.objects.update_or_create(
            node=node, network_id=nid,
            defaults={
                "member_id": ident["member_id"],
                "public_key": ident["public_key"],
                "secret_key": ident["secret_key"],
            },
        )
        made += 1

    if made or kept:
        summary = f"ZeroTier identities — generated {made}, kept {kept} existing"
        if failed:
            summary += f", {failed} failed"
        messages.success(request, summary + ".")
    return redirect("node_detail", pk=pk)


@require_POST
def node_zerotier_join(request: HttpRequest, pk: int) -> HttpResponse:
    """Join a node to a ZeroTier network from the node page.

    Appends ``{network_id, name, member_name}`` to the node's
    ``parameters.zerotier.networks`` (deduped by network_id) and immediately
    generates the identity keypair, so the network shows up in the identities
    table prepopulated. ``member_name`` defaults to the node's minion id.
    """
    node = get_object_or_404(Node.objects.select_related("cluster__tenant"), pk=pk)
    from tenants.models import Integration, ZerotierIdentity
    from tenants.zerotier import (ZEROTIER_NETWORKS, IdtoolError,
                                  RegistrationError, generate_identity,
                                  register_member)

    nid = (request.POST.get("network_id") or "").strip()
    known = {n["network_id"]: n for n in ZEROTIER_NETWORKS}
    if nid not in known:
        messages.error(request, "Pick a known ZeroTier network.")
        return redirect("node_detail", pk=pk)
    name = known[nid]["network_name"]
    # Default the member name to the node's salt id (effective model), not the
    # hostname; fall back to minion_id only when no salt.id is configured.
    salt_id = (node.effective_model.get("salt") or {}).get("id") or node.minion_id
    member_name = (request.POST.get("member_name") or "").strip() or salt_id

    # Append to node.parameters.zerotier.networks (dedup by network_id). Use the
    # normalised keys (network_name / member_name); accept legacy network/id when
    # matching an existing entry.
    params = dict(node.parameters or {})
    zt = dict(params.get("zerotier") or {})
    nets = list(zt.get("networks") or [])
    idx = next((i for i, e in enumerate(nets)
                if isinstance(e, dict)
                and (e.get("network_id") or e.get("network")) == nid),
               None)
    entry = {"network_id": nid, "network_name": name, "member_name": member_name}
    if idx is None:
        nets.append(entry)
    else:
        nets[idx] = {**nets[idx], **entry}
    zt["networks"] = nets
    params["zerotier"] = zt
    node.parameters = params
    node.save(update_fields=["parameters"])

    # Generate (or refresh) the identity for this network.
    try:
        ident = generate_identity()
        ZerotierIdentity.objects.update_or_create(
            node=node, network_id=nid,
            defaults={
                "member_id": ident["member_id"],
                "public_key": ident["public_key"],
                "secret_key": ident["secret_key"],
            },
        )
        messages.success(
            request,
            f"Joined {name} ({nid}) as {member_name} — identity {ident['member_id']} generated.",
        )
    except IdtoolError as exc:
        messages.warning(
            request,
            f"Joined {name} ({nid}) as {member_name}, but identity generation "
            f"failed ({exc}); it will self-generate on first boot.",
        )
        return redirect("node_detail", pk=pk)

    # Best-effort: register + authorize the member on the tenant's ZeroTier
    # controller (ZT Central), naming it member_name. Falls back to the global
    # integration; skips quietly when none is configured.
    tenant = node.cluster.tenant if node.cluster_id else None
    integration = None
    if tenant is not None:
        integration = tenant.integrations.filter(
            type=Integration.Type.ZEROTIER, is_active=True
        ).first()
    if integration is None:
        integration = Integration.objects.filter(
            tenant__isnull=True, type=Integration.Type.ZEROTIER, is_active=True
        ).first()
    if integration is None or not (integration.url and integration.token):
        messages.info(
            request,
            "No ZeroTier controller configured for this tenant — skipped "
            "controller registration (the member self-authorizes if the network "
            "is public, otherwise authorize it manually).",
        )
        return redirect("node_detail", pk=pk)
    try:
        register_member(
            url=integration.url, token=integration.token,
            org=known[nid].get("org", ""), network_id=nid,
            member_id=ident["member_id"], name=member_name,
        )
        messages.success(
            request,
            f"Registered {member_name} ({ident['member_id']}) on {name} via "
            f"{integration.name} — authorized.",
        )
    except RegistrationError as exc:
        messages.warning(
            request,
            f"Identity stored, but controller registration failed ({exc}); "
            "authorize the member manually on ZeroTier Central.",
        )
    return redirect("node_detail", pk=pk)


@require_POST
def generate_wireguard_identity(request: HttpRequest, pk: int) -> HttpResponse:
    """Prepopulate WireGuard keypairs for a node's declared interfaces.

    Runs ``wg genkey``/``wg pubkey`` per declared interface and upserts a
    :class:`tenants.models.WireguardIdentity`. By default fills only interfaces
    that lack a keypair; ``interface=<name>`` targets one and ``force=1``
    regenerates an existing one. Mirrors :func:`generate_zerotier_identity`.
    """
    node = get_object_or_404(Node.objects.select_related("cluster"), pk=pk)
    from tenants.models import WireguardIdentity
    from tenants.wireguard import WgError, generate_keypair

    target = (request.POST.get("interface") or "").strip()
    force = request.POST.get("force") == "1"
    names = [target] if target else [
        i["name"] for i in _declared_wireguard_interfaces(node)
    ]
    if not names:
        messages.warning(
            request,
            f"No WireGuard interfaces declared on {node.slug} — add a tunnel "
            "(or wireguard.interfaces to the cluster/node parameters) first.",
        )
        return redirect("node_detail", pk=pk)

    made = kept = failed = 0
    last_pub = ""
    for name in names:
        existing = WireguardIdentity.objects.filter(node=node, interface=name).first()
        if existing and existing.private_key and not (force or target):
            kept += 1
            continue
        try:
            kp = generate_keypair()
        except WgError as exc:
            failed += 1
            messages.error(request, f"{name}: {exc}")
            continue
        WireguardIdentity.objects.update_or_create(
            node=node, interface=name,
            defaults={"private_key": kp["private_key"],
                      "public_key": kp["public_key"]},
        )
        last_pub = kp["public_key"]
        made += 1

    if made or kept:
        summary = f"WireGuard keypairs — generated {made}, kept {kept} existing"
        if failed:
            summary += f", {failed} failed"
        if made == 1 and last_pub:
            summary += f". Authorize this peer on the server: {last_pub}"
        messages.success(request, summary + ".")
    return redirect("node_detail", pk=pk)


@require_POST
def node_wireguard_add(request: HttpRequest, pk: int) -> HttpResponse:
    """Add a WireGuard tunnel to a node from the node page.

    Appends an interface (with one peer — its endpoint, public key, allowed IPs)
    to the node's ``parameters.wireguard.interfaces`` (deduped by interface name;
    an existing interface gets the new peer appended) and immediately generates
    this node's keypair, so the tunnel shows up prepopulated. The node's public
    key is what you then authorize as a ``[Peer]`` on the WireGuard server/hub.
    Mirrors :func:`node_zerotier_join`.
    """
    node = get_object_or_404(Node.objects.select_related("cluster__tenant"), pk=pk)
    from tenants.models import WireguardIdentity
    from tenants.wireguard import WgError, generate_keypair

    def _csv(field: str) -> list[str]:
        raw = request.POST.get(field) or ""
        return [v.strip() for v in raw.replace("\n", ",").split(",") if v.strip()]

    # Preferred path: pick a WireguardPeer from the catalog (the WG analogue of
    # selecting a ZeroTier network) — its endpoint/public_key/allowed_ips fill in.
    # The per-node tunnel address stays a form field. Free-form fields remain a
    # fallback for ad-hoc peers not in the catalog.
    registered: dict | None = None
    address = _csv("address")
    preshared_key = ""  # set when a wg-easy controller registers this node
    peer_slug = (request.POST.get("wireguard_peer") or "").strip()
    if peer_slug:
        from catalog.models import WireguardPeer
        wgp = WireguardPeer.objects.filter(slug=peer_slug, is_active=True).first()
        if wgp is None:
            messages.error(request, f"WireGuard peer '{peer_slug}' not found.")
            return redirect("node_detail", pk=pk)
        if not wgp.public_key:
            messages.error(
                request,
                f"Peer '{wgp.slug}' has no public key yet (endpoint not up?) — "
                "fill it in on the WireguardPeer first.",
            )
            return redirect("node_detail", pk=pk)
        name = wgp.interface or "wg0"
        endpoint = wgp.endpoint
        peer_public_key = wgp.public_key
        allowed_ips = list(wgp.allowed_ips or [])
        dns = list(wgp.dns or [])
        keepalive = str(wgp.persistent_keepalive or "")
        # Controller registration (ZeroTier-style): if the peer has a wg-easy
        # controller, register this node on it — the controller mints the keypair
        # + assigns the tunnel IP, so the node boots already-authorized (no manual
        # [Peer] step). Falls back to local key generation when there's no controller.
        ctrl = wgp.controller
        if ctrl and ctrl.is_active and ctrl.type == "wg_easy":
            from tenants.wireguard import WgRegisterError, register_client
            try:
                registered = register_client(
                    url=ctrl.url, password=ctrl.token, name=node.minion_id,
                )
            except WgRegisterError as exc:
                messages.error(
                    request, f"wg-easy registration on {ctrl.name} failed: {exc}")
                return redirect("node_detail", pk=pk)
            if registered.get("address"):
                address = [registered["address"]]
            # The controller config is authoritative for the SERVER identity:
            # prefer its public key over the catalog peer's recorded one (which
            # can go stale) and capture the per-client PresharedKey wg-easy v15
            # issues. The selected peer/endpoint (LAN vs public) is kept.
            if registered.get("server_public_key"):
                peer_public_key = registered["server_public_key"]
            preshared_key = registered.get("preshared_key") or ""
    else:
        name = (request.POST.get("interface") or "wg0").strip()
        endpoint = (request.POST.get("endpoint") or "").strip()
        peer_public_key = (request.POST.get("peer_public_key") or "").strip()
        allowed_ips = _csv("allowed_ips")
        dns = _csv("dns")
        keepalive = (request.POST.get("persistent_keepalive") or "").strip()
        if not endpoint or not peer_public_key:
            messages.error(
                request,
                "Select a WireGuard peer from the catalog, or enter a peer "
                "endpoint + public key.",
            )
            return redirect("node_detail", pk=pk)

    peer: dict = {"public_key": peer_public_key, "endpoint": endpoint}
    if preshared_key:
        peer["preshared_key"] = preshared_key
    if allowed_ips:
        peer["allowed_ips"] = allowed_ips
    if keepalive:
        try:
            peer["persistent_keepalive"] = int(keepalive)
        except ValueError:
            pass

    iface: dict = {"name": name}
    if address:
        iface["address"] = address
    if dns:
        iface["dns"] = dns
    iface["peers"] = [peer]

    # Append to node.parameters.wireguard.interfaces (dedup by name; an existing
    # interface keeps its config and gets this peer appended).
    params = dict(node.parameters or {})
    wg = dict(params.get("wireguard") or {})
    ifaces = list(wg.get("interfaces") or [])
    idx = next((i for i, e in enumerate(ifaces)
                if isinstance(e, dict) and e.get("name") == name), None)
    if idx is None:
        ifaces.append(iface)
    else:
        merged = {**ifaces[idx],
                  **{k: v for k, v in iface.items() if k != "peers"}}
        merged["peers"] = list(ifaces[idx].get("peers") or []) + [peer]
        ifaces[idx] = merged
    wg["interfaces"] = ifaces
    params["wireguard"] = wg
    node.parameters = params
    node.save(update_fields=["parameters"])

    # Controller minted the keypair: store it (the node is already authorized on
    # the controller, ZeroTier-style — no manual [Peer] step).
    if registered and registered.get("private_key"):
        WireguardIdentity.objects.update_or_create(
            node=node, interface=name,
            defaults={"private_key": registered["private_key"],
                      "public_key": registered.get("public_key", "")},
        )
        messages.success(
            request,
            f"Registered {node.minion_id} on the wg-easy controller — tunnel "
            f"{name} at {registered.get('address') or '?'}; keypair minted "
            "controller-side, no manual authorization needed.",
        )
        return redirect("node_detail", pk=pk)

    # Generate (or keep) this node's keypair for the interface.
    existing = WireguardIdentity.objects.filter(node=node, interface=name).first()
    if existing and existing.private_key:
        messages.success(
            request,
            f"Added peer {endpoint} to {name} — kept existing keypair "
            f"(public key {existing.public_key}).",
        )
        return redirect("node_detail", pk=pk)
    try:
        kp = generate_keypair()
        WireguardIdentity.objects.update_or_create(
            node=node, interface=name,
            defaults={"private_key": kp["private_key"],
                      "public_key": kp["public_key"]},
        )
        messages.success(
            request,
            f"Added peer {endpoint} to {name} — keypair generated. Authorize "
            f"this node's public key on the server: {kp['public_key']}",
        )
    except WgError as exc:
        messages.warning(
            request,
            f"Added peer {endpoint} to {name}, but keypair generation failed "
            f"({exc}); generate it here or set "
            "wireguard.interfaces[].private_key in the parameters.",
        )
    return redirect("node_detail", pk=pk)


def _render_wireguard_ps1(node, tunnel: str, conf: str) -> str:
    """Render a Windows PowerShell init script: installs WireGuard for Windows if
    missing, writes the tunnel config, and (re)activates it as a service."""
    template = r'''#Requires -RunAsAdministrator
# os-bakery - WireGuard setup for __NODE__ (minion __MINION__), tunnel "__TUNNEL__".
# Run in an elevated PowerShell. Installs WireGuard for Windows if missing, writes
# the tunnel config, then (re)activates it as an auto-start service.
$ErrorActionPreference = "Stop"
$Tunnel   = "__TUNNEL__"
$WgExe    = Join-Path $env:ProgramFiles "WireGuard\wireguard.exe"
$WgMsiUrl = "https://download.wireguard.com/windows-client/wireguard-amd64-0.5.3.msi"  # bump if it 404s
$ConfDir  = Join-Path $env:ProgramData "os-bakery\wireguard"
$ConfPath = Join-Path $ConfDir "$Tunnel.conf"

if (-not (Test-Path $WgExe)) {
    Write-Host "WireGuard not found - downloading + installing..."
    $msi = Join-Path $env:TEMP "wireguard-installer.msi"
    Invoke-WebRequest -Uri $WgMsiUrl -OutFile $msi -UseBasicParsing
    Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart" -Wait
}
if (-not (Test-Path $WgExe)) { throw "WireGuard install failed - install it manually, then re-run." }

New-Item -ItemType Directory -Force -Path $ConfDir | Out-Null
$conf = @'
__CONF__
'@
Set-Content -Path $ConfPath -Value $conf -Encoding ASCII

# (Re)install the tunnel as an auto-start Windows service.
& $WgExe /uninstalltunnelservice $Tunnel 2>$null
Start-Sleep -Seconds 1
& $WgExe /installtunnelservice $ConfPath
Write-Host "WireGuard tunnel '$Tunnel' installed and activated."
'''
    return (template
            .replace("__NODE__", node.name)
            .replace("__MINION__", node.minion_id)
            .replace("__TUNNEL__", tunnel)
            .replace("__CONF__", conf.strip()))


def _wireguard_node_conf(node) -> tuple[str | None, str | None, str | None]:
    """Build the wg-quick config for a node's first declared WireGuard tunnel.

    Returns ``(interface_name, conf_text, error)``. On success ``error`` is
    ``None``; on failure ``interface_name``/``conf_text`` are ``None`` and
    ``error`` is a user-facing message. Shared by the per-client setup views
    (Windows ``.ps1``, raw ``.conf`` download, Android QR). For controller-backed
    peers the full config (incl the wg-easy PresharedKey) is fetched live from
    the controller; otherwise it's assembled from the node's params + the stored
    WireguardIdentity.
    """
    from catalog.models import WireguardPeer
    from tenants.models import WireguardIdentity
    from tenants.wireguard import WgRegisterError, get_client_config

    ifaces = _declared_wireguard_interfaces(node)
    if not ifaces:
        return None, None, f"{node.slug} has no WireGuard tunnel — attach a peer first."
    iface = ifaces[0]
    name = iface.get("name") or "wg0"
    peer_pubs = [p.get("public_key") for p in (iface.get("peers") or [])
                 if isinstance(p, dict) and p.get("public_key")]
    wgp = WireguardPeer.objects.filter(public_key__in=peer_pubs).first() if peer_pubs else None

    if wgp and wgp.controller_id and wgp.controller.is_active and wgp.controller.type == "wg_easy":
        try:
            conf = get_client_config(url=wgp.controller.url, password=wgp.controller.token,
                                     name=node.minion_id)
        except WgRegisterError as exc:
            return None, None, f"Could not fetch the tunnel config from the controller: {exc}"
        return name, conf, None

    ident = WireguardIdentity.objects.filter(node=node, interface=name).first()
    if not (ident and ident.private_key):
        return None, None, f"No keypair for {name} on {node.slug} — generate it first."
    addr = iface.get("address")
    addr = ", ".join(addr) if isinstance(addr, list) else (addr or "")
    dns = iface.get("dns")
    dns = ", ".join(dns) if isinstance(dns, list) else (dns or "")
    lines = ["[Interface]", f"PrivateKey = {ident.private_key}"]
    if addr:
        lines.append(f"Address = {addr}")
    if dns:
        lines.append(f"DNS = {dns}")
    for p in (iface.get("peers") or []):
        if not isinstance(p, dict):
            continue
        lines += ["", "[Peer]", f"PublicKey = {p.get('public_key', '')}"]
        aips = p.get("allowed_ips")
        aips = ", ".join(aips) if isinstance(aips, list) else (aips or "")
        if aips:
            lines.append(f"AllowedIPs = {aips}")
        if p.get("endpoint"):
            lines.append(f"Endpoint = {p['endpoint']}")
        if p.get("persistent_keepalive"):
            lines.append(f"PersistentKeepalive = {p['persistent_keepalive']}")
    return name, "\n".join(lines), None


def node_wireguard_ps1(request: HttpRequest, pk: int) -> HttpResponse:
    """Per-node Windows PowerShell init script that installs WireGuard (if
    missing) and brings up the node's tunnel."""
    node = get_object_or_404(Node.objects.select_related("cluster__tenant"), pk=pk)
    name, conf, error = _wireguard_node_conf(node)
    if error:
        messages.error(request, error)
        return redirect("node_detail", pk=pk)
    resp = HttpResponse(_render_wireguard_ps1(node, name, conf),
                        content_type="text/plain; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{node.slug}-wireguard.ps1"'
    return resp


def node_wireguard_conf(request: HttpRequest, pk: int) -> HttpResponse:
    """Raw wg-quick ``.conf`` for the node's tunnel — the universal client format.

    The WireGuard app on Android/iOS imports it ("Import from file or archive")
    and wg-quick on Linux/macOS runs it directly. Carries the node's private key.
    """
    node = get_object_or_404(Node.objects.select_related("cluster__tenant"), pk=pk)
    name, conf, error = _wireguard_node_conf(node)
    if error:
        messages.error(request, error)
        return redirect("node_detail", pk=pk)
    resp = HttpResponse(conf.strip() + "\n", content_type="text/plain; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{node.slug}-{name}.conf"'
    return resp


def node_wireguard_android(request: HttpRequest, pk: int) -> HttpResponse:
    """Android setup page: a scannable QR of the wg-quick config (the WireGuard
    Android app's "Scan from QR code" flow), plus a ``.conf`` download fallback.

    The QR is rendered server-side (``segno``, pure-Python) so the private key
    never leaves for a third-party script. If ``segno`` isn't installed the page
    still works — it degrades to the ``.conf`` download + manual import steps.
    """
    node = get_object_or_404(Node.objects.select_related("cluster__tenant"), pk=pk)
    name, conf, error = _wireguard_node_conf(node)
    if error:
        messages.error(request, error)
        return redirect("node_detail", pk=pk)
    conf = conf.strip()
    qr_svg = None
    try:
        import segno

        # svg_inline() returns a bare <svg> string (no XML decl / namespace) ready
        # to embed in the page; error="m" keeps it scannable for the wg-quick
        # payload. (segno.save(kind="svg") writes bytes, so we use svg_inline.)
        qr_svg = segno.make(conf, error="m").svg_inline(scale=4, border=2)
    except Exception:
        qr_svg = None
    return render(request, "node_wireguard_android.html", {
        "node": node, "interface": name, "conf": conf, "qr_svg": qr_svg,
    })


# ---------------------------------------------------------------------------
# Bake — role-template recipe picker + per-recipe form
# ---------------------------------------------------------------------------


def _os_logo(slug: str) -> dict[str, str]:
    """Bundle of {svg, letter, accent} for a given OS slug — defaults for unknown."""
    entry = OS_LOGOS.get(slug, {})
    return {
        "svg": entry.get("svg"),
        "letter": entry.get("fallback_letter", slug[:1].upper()),
        "accent": entry.get("accent", "#6b7280"),
    }


# Recipe-to-use-case mapping. Single source of truth for the bake UI's
# top-level grouping — keep this list in sync as new recipes land.
RECIPE_USE_CASE: dict[str, str] = {
    "batocera-handheld":   "retro",
    "batocera-arcade":     "retro",
    "batocera-notebook":   "retro",
    "ubuntu-desktop":      "desktop",
    "omarchy-desktop":     "desktop",
    "popos-workstation":   "desktop",
    "ubuntu-docker":       "server",
    "ubuntu-kube":         "server",
    "debian-server":       "server",
    "raspios-headless":    "iot",
    "haos-appliance":      "iot",
    "kali-pentest":        "security",
    "l4t-jetson":          "edge_ai",
    "ardupilot-rover":     "robotics",
    "ardupilot-copter":    "robotics",
    "esphome-laskakit-esplan": "firmware",
    "esphome-bluetooth-proxy": "firmware",
    "esphome-vindriktning":    "firmware",
    "esphome-custom":          "firmware",
    "windows-workstation": "desktop",
    "proxmox-bare-metal":  "hypervisor",
}

USE_CASES: list[tuple[str, str, str, str]] = [
    # (key, label, tagline, accent)
    ("retro",      "Retro gaming",
     "Handhelds, arcade cabinets, retro laptops — Batocera presets.",
     "#1f6feb"),
    ("desktop",    "Desktop / workstation",
     "GNOME, Hyprland, Pop!_OS — daily-driver workstations.",
     "#e95420"),
    ("server",     "Server",
     "Headless Linux for fleet roles — Docker hosts, Kubernetes nodes, "
     "general servers.",
     "#0ea5e9"),
    ("iot",        "IoT / appliance",
     "Single-purpose images for home automation and headless Pis.",
     "#18bcf2"),
    ("hypervisor", "Bare-metal hypervisor",
     "Proxmox VE for fleet hosts.",
     "#e57000"),
    ("security",   "Pentest / security",
     "Kali workstation, ready for red-team use.",
     "#557c94"),
    ("edge_ai",    "Edge AI",
     "NVIDIA Jetson SDK images for on-device inference.",
     "#76b900"),
    ("robotics",   "Robotics / autopilot",
     "ArduPilot stacks on the BeagleBone Blue — rovers, drones, surface "
     "vehicles.",
     "#10b981"),
    ("firmware",   "Microcontroller firmware",
     "ESPHome configs for ESP32 / ESP8266 devices — Home Assistant "
     "integration, BLE proxies, sensor turnkeys. Flash to the chip "
     "directly from the browser.",
     "#000000"),
]


def bake_index(request: HttpRequest) -> HttpResponse:
    """Recipe-picker page — role templates grouped by use case."""
    os_filter = request.GET.get("os") or ""

    qs = (
        Recipe.objects.filter(status=Recipe.Status.ACTIVE)
        .select_related("operating_system")
        .prefetch_related("supported_hardware")
        .order_by("operating_system__name", "name")
    )
    if os_filter:
        qs = qs.filter(operating_system__slug=os_filter)

    cards_by_use_case: dict[str, list[dict]] = {}
    for r in qs:
        logo = _os_logo(r.operating_system.slug)
        card = {
            "slug": r.slug,
            "name": r.name,
            "summary": r.summary,
            "os_slug": r.operating_system.slug,
            "os_name": r.operating_system.name,
            "os_kind": r.operating_system.get_kind_display(),
            "logo_svg": logo["svg"],
            "logo_letter": logo["letter"],
            "accent": logo["accent"],
            "hardware": [
                {"slug": h.slug, "name": h.name}
                for h in r.supported_hardware.all()
            ],
        }
        use_case = RECIPE_USE_CASE.get(r.slug, "other")
        cards_by_use_case.setdefault(use_case, []).append(card)

    sections: list[dict] = []
    for key, label, tagline, accent in USE_CASES:
        cards = cards_by_use_case.get(key, [])
        if not cards:
            continue
        sections.append({
            "key": key,
            "label": label,
            "tagline": tagline,
            "accent": accent,
            "cards": cards,
            "n_cards": len(cards),
        })
    # Anything not in USE_CASES falls through to a final "Other" bucket.
    if "other" in cards_by_use_case:
        sections.append({
            "key": "other",
            "label": "Other",
            "tagline": "Recipes without a use-case mapping yet.",
            "accent": "#525252",
            "cards": cards_by_use_case["other"],
            "n_cards": len(cards_by_use_case["other"]),
        })

    return render(request, "bake_index.html", {
        "sections": sections,
        "total_recipes": sum(s["n_cards"] for s in sections),
        "all_operating_systems": OperatingSystem.objects.filter(
            is_active=True, recipes__status=Recipe.Status.ACTIVE,
        ).distinct().order_by("name"),
        "selected_os": os_filter,
    })


def bake_recipe(request: HttpRequest, slug: str) -> HttpResponse:
    """Per-recipe form: pick a hardware target + fill out options + bake."""
    recipe = get_object_or_404(
        Recipe.objects.select_related("operating_system", "pinned_release")
        .prefetch_related("supported_hardware", "options"),
        slug=slug,
    )
    version = (recipe.versions.filter(is_current=True).first()
               or recipe.versions.order_by("-created_at").first())
    if version is None:
        return render(request, "bake_recipe.html", {
            "recipe": recipe,
            "error": "This recipe has no published version yet.",
        }, status=400)

    options = list(recipe.options.order_by("sort_order", "key"))
    targets = list(
        recipe.supported_hardware.select_related("architecture").order_by("slug")
    )

    release = recipe.pinned_release or recipe.operating_system.releases.filter(
        is_default=True
    ).first()

    # For each (target, variant) we have a UpstreamImage row — group them
    # so the form can present a "Device · variant" picker.
    image_choices: list[dict] = []
    if release:
        from django.db.models import Q
        for target in targets:
            # Images whose primary target is this device, plus shared images
            # that list it as an extra target (x86 handhelds → x86_64 build).
            target_images = (UpstreamImage.objects.filter(release=release)
                             .filter(Q(hardware_target=target)
                                     | Q(extra_targets=target))
                             .order_by("variant").distinct())
            for img in target_images:
                variant = img.variant or ""
                label = target.name + (f" · {variant}" if variant else "")
                image_choices.append({
                    "id": img.id,
                    "target_slug": target.slug,
                    "target_name": target.name,
                    "arch": target.architecture.slug,
                    "variant": variant,
                    "label": label,
                })

    # Clusters the user can drop this device into. For now: all active
    # clusters across all tenants. When auth/tenancy lands, scope to the
    # requesting user's tenants.
    clusters_qs = (
        Cluster.objects.filter(is_active=True)
        .select_related("tenant")
        .order_by("tenant__name", "name")
    )

    if request.method == "POST":
        image_id = request.POST.get("upstream_image")
        upstream = UpstreamImage.objects.filter(pk=image_id).first()
        if not upstream:
            messages.error(request, "Pick a device + variant.")
        else:
            option_values: dict[str, object] = {}
            for opt in options:
                if opt.kind == "file":
                    # Upload to the artifact store; stash the key so the
                    # provisioner can fetch it (e.g. a HAOS backup .tar).
                    f = request.FILES.get(f"opt_{opt.key}")
                    if f:
                        import uuid as _uuid
                        key = f"uploads/{recipe.slug}/{_uuid.uuid4().hex}-{f.name}"
                        storages["artifacts"].save(key, f)
                        option_values[opt.key] = key
                    else:
                        option_values[opt.key] = ""
                    continue
                raw = request.POST.get(f"opt_{opt.key}", "")
                if opt.kind == RecipeOptionKind_BOOLEAN:
                    option_values[opt.key] = raw == "on"
                elif opt.kind == RecipeOptionKind_INTEGER:
                    try:
                        option_values[opt.key] = int(raw) if raw else None
                    except ValueError:
                        option_values[opt.key] = raw
                else:
                    option_values[opt.key] = raw

            cluster_id = request.POST.get("cluster") or None
            cluster_obj = (
                Cluster.objects.filter(pk=cluster_id).first()
                if cluster_id else None
            )

            build = BuildRequest.objects.create(
                recipe_version=version,
                hardware_target=upstream.hardware_target,
                upstream_image=upstream,
                option_values=option_values,
                label=str(option_values.get("hostname") or recipe.slug),
                requester=request.user if request.user.is_authenticated else None,
                cluster=cluster_obj,
                tenant=cluster_obj.tenant if cluster_obj else None,
            )
            messages.success(
                request,
                f"Build {build.id} queued"
                + (f" — joining {cluster_obj}" if cluster_obj else "")
                + ". Track it in the admin.",
            )
            return redirect(f"/admin/builds/buildrequest/{build.id}/change/")

    logo = _os_logo(recipe.operating_system.slug)
    # Build cluster choices for the template, grouped by tenant.
    cluster_choices = [
        {
            "id": c.id,
            "slug": c.slug,
            "name": c.name,
            "tenant_slug": c.tenant.slug,
            "tenant_name": c.tenant.name,
        }
        for c in clusters_qs
    ]
    return render(request, "bake_recipe.html", {
        "recipe": recipe,
        "version": version,
        "release": release,
        "os_name": recipe.operating_system.name,
        "os_slug": recipe.operating_system.slug,
        "logo_svg": logo["svg"],
        "logo_letter": logo["letter"],
        "accent": logo["accent"],
        "options": options,
        "image_choices": image_choices,
        "cluster_choices": cluster_choices,
    })


# Avoid hardcoding string literals when checking RecipeOption.kind.
RecipeOptionKind_BOOLEAN = "boolean"
RecipeOptionKind_INTEGER = "integer"


# ---------------------------------------------------------------------------
# Docs viewer — render markdown files under docs/ as styled HTML
# ---------------------------------------------------------------------------

# Files allowed to be rendered. Keeps the view from serving arbitrary
# project paths under /docs/<slug>/. Add a row when you want a new doc on
# the site.
DOCS_ON_SITE: dict[str, dict[str, str]] = {
    "flashing": {
        "title": "Flashing baked images",
        "tagline": "Per-format, per-OS: how to write the artifact onto SD / "
                   "USB / VM / ESP.",
        "file": "docs/flashing.md",
    },
    "catalog": {
        "title": "Catalog matrix",
        "tagline": "Every Architecture / HardwareTarget / OperatingSystem / "
                   "OSRelease / UpstreamImage row the seed creates.",
        "file": "docs/catalog.md",
    },
    "platforms": {
        "title": "Supported platforms",
        "tagline": "The wider device universe — Pis, BeagleBone, Jetson, "
                   "PCs, VMs, future targets.",
        "file": "docs/platforms.md",
    },
    "salt-states": {
        "title": "Salt states we bake",
        "tagline": "The vendored gedu salt formulas — what each does, the "
                   "per-OS dispatch pattern, and how bakes apply them.",
        "file": "docs/salt-states.md",
    },
}


def docs_index(request: HttpRequest) -> HttpResponse:
    pages = [
        {"slug": slug, **meta}
        for slug, meta in DOCS_ON_SITE.items()
    ]
    return render(request, "docs_index.html", {"pages": pages})


def doc_page(request: HttpRequest, slug: str) -> HttpResponse:
    meta = DOCS_ON_SITE.get(slug)
    if meta is None:
        raise Http404(f"Unknown doc: {slug!r}")

    import markdown

    path = Path(settings.BASE_DIR) / meta["file"]
    if not path.exists():
        raise Http404(f"Doc file missing on disk: {path}")

    text = path.read_text(encoding="utf-8")
    body_html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        output_format="html5",
    )
    return render(request, "doc.html", {
        "slug": slug,
        "title": meta["title"],
        "tagline": meta["tagline"],
        "body_html": body_html,
        "other_pages": [
            {"slug": s, **m}
            for s, m in DOCS_ON_SITE.items() if s != slug
        ],
    })


# ---------------------------------------------------------------------------
# Nodes — the units we bake images onto (cluster + preset + hardware)
# ---------------------------------------------------------------------------

def _node_form_options() -> dict:
    """Select options for the node create/edit forms."""
    return {
        "clusters": Cluster.objects.filter(is_active=True)
                    .select_related("tenant").order_by("tenant__name", "name"),
        "presets": Recipe.objects.select_related("operating_system").order_by("slug"),
        "targets": HardwareTarget.objects.filter(is_active=True)
                   .select_related("architecture").order_by("slug"),
    }


def nodes(request: HttpRequest) -> HttpResponse:
    """All nodes, grouped by cluster, with their preset + target + last bake."""
    f_cluster = request.GET.get("cluster") or ""
    qs = (
        Node.objects.filter(is_active=True)
        .select_related("cluster__tenant", "preset__operating_system",
                        "hardware_target__architecture")
        .order_by("cluster__tenant__name", "cluster__slug", "slug")
    )
    if f_cluster:
        qs = qs.filter(cluster__slug=f_cluster)

    rows = []
    for n in qs:
        last = (n.build_requests.order_by("-queued_at").first())
        rows.append({
            "id": n.id,
            "slug": n.slug,
            "name": n.name,
            "hostname": n.minion_id,
            "cluster": f"{n.cluster.tenant.slug}/{n.cluster.slug}",
            "cluster_slug": n.cluster.slug,
            "preset": n.preset.slug,
            "os": n.preset.operating_system.slug,
            "target": n.hardware_target.slug,
            "arch": n.hardware_target.architecture.slug,
            "tags": n.tags or [],
            "last_status": last.status if last else None,
            "last_build_id": last.id if last else None,
        })
    return render(request, "nodes.html", {
        "rows": rows, "total": len(rows), "f_cluster": f_cluster,
        **_node_form_options(),
    })


def node_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """One node: its joined metadata (effective model) + recent bakes + bake."""
    node = get_object_or_404(
        Node.objects.select_related(
            "cluster__tenant", "preset__operating_system",
            "hardware_target__architecture", "upstream_image__release",
        ),
        pk=pk,
    )
    import yaml as _yaml
    model = node.effective_model
    image_model, prov_model = _split_model(model)
    image_yaml = _yaml.safe_dump(image_model, sort_keys=False) if image_model else ""
    provisioner_yaml = _yaml.safe_dump(prov_model, sort_keys=False) if prov_model else ""
    cluster_params = node.cluster.parameters or {}
    cluster_yaml = _yaml.safe_dump(cluster_params, sort_keys=False) if cluster_params else ""
    node_yaml = _yaml.safe_dump(node.parameters or {}, sort_keys=False) if node.parameters else ""

    builds = list(
        node.build_requests.select_related("artifact").order_by("-queued_at")[:10]
    )

    # ZeroTier: declared networks ⊕ prepopulated identities (orphan identities
    # for no-longer-declared networks are still surfaced so they can be cleaned).
    zt_identities = {i.network_id: i for i in node.zerotier_identities.all()}
    zt_network_ids = _declared_zerotier_network_ids(node)
    zt_rows = [{"network_id": nid, "identity": zt_identities.get(nid)}
               for nid in zt_network_ids]
    for nid, ident in zt_identities.items():
        if nid not in zt_network_ids:
            zt_rows.append({"network_id": nid, "identity": ident, "orphan": True})

    from tenants.zerotier import ZEROTIER_NETWORKS
    joined_ids = {r["network_id"] for r in zt_rows}
    zt_networks = [{**n, "joined": n["network_id"] in joined_ids}
                   for n in ZEROTIER_NETWORKS]
    # The member name defaults to the node's salt id (from the effective model),
    # NOT the hostname — falls back to minion_id only when no salt.id is set.
    zt_member_default = ((node.effective_model.get("salt") or {}).get("id")
                         or node.minion_id)

    # WireGuard: declared interfaces ⊕ prepopulated keypairs (orphan keypairs for
    # no-longer-declared interfaces are surfaced so they can be cleaned).
    wg_identities = {i.interface: i for i in node.wireguard_identities.all()}
    wg_rows = []
    wg_declared: set[str] = set()
    for iface in _declared_wireguard_interfaces(node):
        name = iface["name"]
        wg_declared.add(name)
        addr = iface.get("address")
        peers = iface.get("peers") or []
        wg_rows.append({
            "interface": name,
            "address": ", ".join(addr) if isinstance(addr, list) else (addr or ""),
            "endpoints": [p.get("endpoint") for p in peers
                          if isinstance(p, dict) and p.get("endpoint")],
            "identity": wg_identities.get(name),
        })
    for name, ident in wg_identities.items():
        if name not in wg_declared:
            wg_rows.append({"interface": name, "address": "", "endpoints": [],
                            "identity": ident, "orphan": True})

    # Suggest a free overlay IP per peer for the attach form: the next address in
    # the peer's address_pool not already used by any node (reserve .1 = server,
    # .2 = infra). For controller-backed peers the controller still assigns the
    # final IP — this is the pre-fill/suggestion.
    import ipaddress
    _used_ips: set = set()
    for n in Node.objects.exclude(parameters={}).only("parameters"):
        for ifc in (((n.parameters or {}).get("wireguard") or {}).get("interfaces") or []):
            if not isinstance(ifc, dict):
                continue
            a = ifc.get("address")
            for v in (a if isinstance(a, list) else ([a] if a else [])):
                try:
                    _used_ips.add(ipaddress.ip_address(str(v).split("/")[0].strip()))
                except ValueError:
                    pass

    def _suggest_addr(pool: str) -> str:
        if not pool:
            return ""
        try:
            net = ipaddress.ip_network(pool, strict=False)
        except ValueError:
            return ""
        reserved = {net.network_address + 1, net.network_address + 2}
        for h in net.hosts():
            if h in reserved or h in _used_ips:
                continue
            return f"{h}/{net.prefixlen}"
        return ""

    wg_peers = list(WireguardPeer.objects.filter(is_active=True).order_by("slug"))
    for _p in wg_peers:
        _p.suggested_address = _suggest_addr(_p.address_pool)

    return render(request, "node_detail.html", {
        "node": node,
        "image_yaml": image_yaml,
        "provisioner_yaml": provisioner_yaml,
        "cluster_yaml": cluster_yaml,
        "node_yaml": node_yaml,
        "node_params_yaml": node_yaml,
        "tags_csv": ", ".join(node.tags or []),
        "builds": builds,
        "zt_rows": zt_rows,
        "zt_networks": zt_networks,
        "zt_member_default": zt_member_default,
        "wg_rows": wg_rows,
        "wireguard_peers": wg_peers,
        **_node_form_options(),
    })


@require_POST
def bake_node(request: HttpRequest, pk: int) -> HttpResponse:
    """Create a BuildRequest from a node (its cluster + preset + target)."""
    node = get_object_or_404(Node.objects.select_related("cluster", "preset"), pk=pk)
    recipe = node.preset
    version = (recipe.versions.filter(is_current=True).first()
               or recipe.versions.order_by("-created_at").first())
    if version is None:
        messages.error(request, f"Preset {recipe.slug} has no published version.")
        return redirect("node_detail", pk=pk)

    img = node.upstream_image
    if img is None:
        from django.db.models import Q
        # Match the device as the image's primary target OR an extra target
        # (x86 handhelds like Loki / Steam Deck share the one x86_64 build).
        target_q = (Q(hardware_target=node.hardware_target)
                    | Q(extra_targets=node.hardware_target))
        candidates = (UpstreamImage.objects
                      .filter(release__operating_system=recipe.operating_system)
                      .filter(target_q).distinct())
        # Prefer the recipe's pinned release, else the OS default.
        release = recipe.pinned_release or recipe.operating_system.releases.filter(
            is_default=True
        ).first()
        if release:
            img = candidates.filter(release=release).order_by("variant").first()
        # Per-SoC distros (Batocera) ship device images that lag the OS default —
        # e.g. the RG353/RK3566 build is stuck on v42 while the default is v43, and
        # no v43 rgxx3 image exists. Fall back to the newest release that actually
        # has an image for this device rather than failing the bake.
        if img is None:
            img = candidates.order_by(
                "-release__released_on", "-release__version", "variant"
            ).first()
    if img is None:
        messages.error(
            request,
            f"No base image for {recipe.operating_system.slug} on "
            f"{node.hardware_target.slug} (arch {node.hardware_target.architecture.slug}) "
            "— sync the matching base image or pin one on the node.",
        )
        return redirect("node_detail", pk=pk)

    build = BuildRequest.objects.create(
        recipe_version=version,
        hardware_target=node.hardware_target,
        upstream_image=img,
        option_values={"hostname": node.minion_id, "minion_id": node.minion_id},
        label=node.minion_id,
        cluster=node.cluster,
        tenant=node.cluster.tenant,
        node=node,
    )
    messages.success(request, f"Baking node {node.slug} — build {build.id} queued.")
    return redirect("build_log", build_id=build.id)


def bake_node_script(request: HttpRequest) -> HttpResponse:
    """Download scripts/bake-node.sh — bakes a live Batocera node over SSH."""
    path = settings.BASE_DIR / "scripts" / "bake-node.sh"
    if not path.exists():
        raise Http404("bake-node.sh not found")
    return FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename="bake-node.sh",
        content_type="application/x-shellscript",
    )


def node_bake_script(request: HttpRequest, pk: int) -> HttpResponse:
    """Per-node init script: the live-node bake script (scripts/bake-node.sh)
    with THIS node's salt minion id AND rendered pillar baked in, so running it
    reproduces exactly what os-bakery bakes for this node. Downloaded as
    ``<slug>-init.sh`` from the node's page; run it against the node's IP:

        ./<slug>-init.sh [--test] <node-ip>

    ``--test`` previews (salt test=True) without applying.
    """
    import yaml as _yaml

    from builds.provisioners.batocera_pkg import _NON_STATE_KEYS

    node = get_object_or_404(Node, pk=pk)
    base = settings.BASE_DIR / "scripts" / "bake-node.sh"
    if not base.exists():
        raise Http404("bake-node.sh not found")
    # Build the same pillar the bake writes (batocera_pkg._write_pillar): the
    # effective model minus image/identity keys, plus a pillar-driven `states`
    # list (batocera first — it configures the repos the rest install from).
    model = node.effective_model or {}
    data = {k: v for k, v in model.items() if k not in _NON_STATE_KEYS}
    states = (["batocera"] if "batocera" in data else []) + \
             [k for k in data if k != "batocera"]
    pillar_yaml = _yaml.safe_dump({**data, "states": states},
                                  default_flow_style=False, sort_keys=False)
    # The salt minion id is the pillar's salt.id (set from node/cluster params),
    # NOT the hostname. Seeding node.minion_id (= hostname) as salt.minion-id is
    # what made the salt run correct it from the hostname back to salt.id. Read
    # it straight from the pillar data we just rendered (single source of truth).
    mid = (data.get("salt") or {}).get("id") or node.minion_id

    pillar_marker = "NEW_PILLAR=\"$(cat <<'OSBAKERY_PILLAR_EOF'\nOSBAKERY_PILLAR_EOF\n)\""
    pillar_filled = ("NEW_PILLAR=\"$(cat <<'OSBAKERY_PILLAR_EOF'\n"
                     + pillar_yaml + "OSBAKERY_PILLAR_EOF\n)\"")

    # Bake in the expected target hostname (the node's minion id / hostname) so
    # the script refuses to run against the wrong machine unless --force.
    script = (base.read_text()
              .replace('MINION_ID="${MINION_ID:-}"',
                       f'MINION_ID="${{MINION_ID:-{mid}}}"', 1)
              .replace('EXPECT_HOST="${EXPECT_HOST:-}"',
                       f'EXPECT_HOST="${{EXPECT_HOST:-{node.minion_id}}}"', 1)
              .replace(pillar_marker, pillar_filled, 1))

    resp = HttpResponse(script, content_type="application/x-shellscript")
    resp["Content-Disposition"] = f'attachment; filename="{node.slug}-init.sh"'
    return resp
