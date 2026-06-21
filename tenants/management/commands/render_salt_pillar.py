"""Render the fleet's salt pillar as a static ``salt_master_pillar_data`` block.

The offline counterpart to the live ``/pillar/<minion_id>`` http_json endpoint
(:mod:`tenants.pillar`): instead of the master pulling each node's pillar at
render time, this emits every active node's pillar up front as a
``node-<minion_id>`` fragment, ready to paste / import into the Kapitan salt
target (``…/gedu-prg-infra-salt.yml``'s ``_param_:salt_master_pillar_data``).

Each fragment is the node's *fully merged* pillar (cluster ⊕ node ⊕ identities,
minus os-bakery-internal keys) — the same bytes :func:`tenants.pillar.node_pillar`
serves live — so the existing pillar-top rule ``node-{{ grains.id }}`` hands each
minion its fragment with no separate ``deploy-*`` shared fragments needed.

    manage.py render_salt_pillar                 # whole fleet → stdout
    manage.py render_salt_pillar --tenant gedu    # one tenant
    manage.py render_salt_pillar -o pillar.yml    # write a file
"""

from __future__ import annotations

import sys

import yaml
from django.core.management.base import BaseCommand

from tenants.models import Node
from tenants.pillar import node_pillar


class _LiteralStr(str):
    """A string rendered as a YAML literal block scalar (``|``)."""


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(
    _LiteralStr,
    lambda dumper, data: dumper.represent_scalar(
        "tag:yaml.org,2002:str", data, style="|"
    ),
)


class Command(BaseCommand):
    help = "Render active nodes' pillars as a salt_master_pillar_data YAML block."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--tenant", help="Limit to this tenant slug (default: all tenants)."
        )
        parser.add_argument(
            "-o", "--output", help="Write to this file instead of stdout."
        )

    def handle(self, *args, **opts) -> None:
        nodes = (
            Node.objects.filter(is_active=True)
            .select_related("cluster", "cluster__tenant", "preset", "hardware_target")
            .prefetch_related("zerotier_identities", "wireguard_identities")
        )
        if opts.get("tenant"):
            nodes = nodes.filter(cluster__tenant__slug=opts["tenant"])

        data: dict[str, _LiteralStr] = {}
        for node in nodes:
            fragment = yaml.safe_dump(
                node_pillar(node), default_flow_style=False, sort_keys=False,
                allow_unicode=True, width=1_000_000,
            )
            data[f"node-{node.minion_id}"] = _LiteralStr(fragment)

        block = {"parameters": {"_param_": {"salt_master_pillar_data": data}}}
        out = yaml.dump(
            block, Dumper=_Dumper, default_flow_style=False, sort_keys=False,
            allow_unicode=True, width=1_000_000,
        )

        if opts.get("output"):
            with open(opts["output"], "w", encoding="utf-8") as fh:
                fh.write(out)
            self.stderr.write(
                self.style.SUCCESS(
                    f"Wrote {len(data)} node pillar(s) to {opts['output']}"
                )
            )
        else:
            sys.stdout.write(out)
