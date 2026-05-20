# Roadmap

This is an honest status of the scaffold: what works end-to-end, what's stubbed, and what's wanted next.

## ✓ Done

- Project scaffold (Django 5, Celery, DRF, Postgres-ready).
- Catalog schema: Architecture, HardwareTarget, OperatingSystem, OSRelease, UpstreamImage.
- Recipes schema: Recipe, RecipeVersion, RecipeOption (with the `is_current` invariant).
- Builds schema: BuildRequest, BuildEvent, Artifact, DownloadToken.
- Infra registry: PackerTemplate, SaltFormula, plus `sync_filesystem` management command.
- Build dispatch via `post_save` signal → Celery queue.
- Orchestrator shape: workspace prep, pillar materialisation, top-file resolution, packing, publish, token issue.
- Download view with revocation/expiry/use-count enforcement.
- Packer templates for Batocera (rpi5/rpi4/x86_64), Raspberry Pi OS (rpi5/rpi4/rpi-zero2w), Ubuntu (arm64/amd64).
- Salt formulas: base hardening / users / network / locale, batocera (base/arcade/family/minimal), raspios (base/kiosk/headless/docker), ubuntu (base/server/k3s).
- Documentation set under `docs/`.

## ◐ Stubbed (intentional)

- **`builds.orchestrator._mount_and_provision`** — records the intent and skips the actual mount + salt-call. Needs root + libguestfs + qemu-user-static on the build host. Replace with real implementation when running on a machine that has those.
- **Authentication** — DRF default permissions are `IsAuthenticatedOrReadOnly`. Hook up SSO/JWT to taste.
- **UI** — DRF browsable + Django admin only for now.

## ☐ Next

- [ ] Real mount + salt-call inside a worker container.
- [ ] Cleanup management command for expired artifacts + tokens + workspaces.
- [ ] Cron job (Celery beat) for daily Packer refreshes.
- [ ] Per-OS pillar deep-merge helper (currently only top-level merge).
- [ ] Encrypted secret storage for `secret` recipe options.
- [ ] Frontend SPA (React/Svelte/Htmx — undecided).
- [ ] Webhook on build completion.
- [ ] Per-build resource limits (timeout, max output size).
- [ ] `BuildRequest.cancel()` action that revokes the Celery task.
