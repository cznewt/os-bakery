"""Backfill stored Node.parameters to match the current model schema.

`Node.effective_model` injects ``salt.id`` (the minion id) live, but the
node's *stored* ``parameters`` JSON predates that — and may still carry the
decorative ``variant`` / ``fleet_role`` / ``role`` keys the salt modules now
own. This command persists ``salt.id`` into each node's parameters and drops
those dead keys, so the saved record matches what gets baked.

Idempotent — re-running changes nothing once converged. Use ``--dry-run`` to
preview.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from tenants.models import Node

# Top-level pillar keys the salt modules now own — stripped from recipes in
# seed_recipes, so they have no business lingering in a node's stored params.
STALE_KEYS = ("variant", "fleet_role", "role")


class Command(BaseCommand):
    help = ("Backfill salt.id (the node's minion id) into each Node's stored "
            "parameters and drop schema-dead variant/fleet_role/role keys.")

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, dry_run: bool = False, **options) -> None:
        scanned = changed = 0
        for node in Node.objects.select_related("cluster__tenant").all():
            scanned += 1
            params = dict(node.parameters or {})
            before = json.dumps(params, sort_keys=True)

            # salt.id = the minion id, authoritatively; keep any other salt.*
            # (e.g. the cluster-inherited master block isn't here, but a node
            # may carry its own salt overrides).
            salt = dict(params.get("salt") or {})
            salt["id"] = node.minion_id
            params["salt"] = salt

            removed = [k for k in STALE_KEYS if k in params]
            for k in removed:
                params.pop(k)

            if json.dumps(params, sort_keys=True) == before:
                continue
            changed += 1
            note = f"salt.id={node.minion_id}"
            if removed:
                note += f"; dropped {', '.join(removed)}"
            self.stdout.write(f"  {'[dry] ' if dry_run else ''}{node}: {note}")
            if not dry_run:
                node.parameters = params
                node.save(update_fields=["parameters"])

        verb = "would update" if dry_run else "updated"
        self.stdout.write(self.style.SUCCESS(
            f"Scanned {scanned} nodes, {verb} {changed}."
        ))
