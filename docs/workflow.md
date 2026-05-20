# Build workflow

This walks through every step of going from "user clicks Build" to "user downloads a personalised image", and points at the exact code paths involved.

## 0. Prerequisites

Before any build can run, four things must be in place:

1. A `HardwareTarget` for the device you want to image.
2. An `UpstreamImage` row pointing at a *local* base image (Packer has run at least once).
3. A `Recipe` with at least one `RecipeVersion` marked `is_current=True`.
4. A Celery worker subscribed to the `builds` queue.

## 1. User submits the request

`POST /api/builds/`

```json
{
  "recipe_slug": "family-arcade",
  "hardware_target_slug": "rpi5",
  "label": "kitchen-arcade",
  "option_values": {
    "admin_username": "newt",
    "admin_ssh_keys": ["ssh-ed25519 AAAA..."],
    "wifi_ssid": "Bakery",
    "wifi_password": "hunter2",
    "timezone": "Europe/Prague",
    "boot_to_arcade": true
  }
}
```

Implemented by `builds.serializers.BuildRequestSerializer.create`. It:

- Resolves `recipe_slug` → `Recipe.current_version`.
- Picks the OS default release (or `Recipe.pinned_release`).
- Looks up the `UpstreamImage` for `(release, hardware_target)`. 404 if it doesn't exist.
- Persists a `BuildRequest` with status `queued`.

## 2. The signal dispatches it

`builds/signals.py::enqueue_new_build_requests` (registered via `BuildsConfig.ready`) fires on `post_save` and calls:

```py
async_result = run_build.apply_async(args=[str(instance.id)], queue="builds")
```

The Celery task ID is stamped back on the row so admins can correlate.

## 3. The worker takes over

`builds.tasks.run_build` (`@shared_task(name="builds.tasks.run_build")`):

1. Transitions `queued → preparing`, records a `BuildEvent("prepare")`.
2. Calls into `builds.orchestrator.bake(build)`.
3. On success: `succeeded`. On failure: `failed` + `failure_reason`.

## 4. The orchestrator bakes

`builds/orchestrator.py::bake` runs these phases in order, each emitting a `BuildEvent`:

| Phase     | What happens                                                                                                       |
| --------- | ------------------------------------------------------------------------------------------------------------------- |
| `prepare` | `_prepare_workspace`: makes `BUILD_WORK_ROOT/<build-id>/`, copies the cached base image into `target.img`.        |
| `pillar`  | `_write_pillar`: materialises a per-build pillar tree with `osbakery.*` metadata, `options.*` from the form, and recipe `pillar_overrides`. |
| `salt`    | `_mount_and_provision`: mounts the image, copies pillar/top, `arch-chroot ... salt-call --local state.apply`. *(scaffold no-op today — needs root + libguestfs)* |
| `pack`    | `_pack`: `xz -T0 -z` the target image to `target.img.xz`.                                                          |
| `publish` | `_publish`: SHA-256s the artifact, saves it via `storages["artifacts"]`, creates the `Artifact` + `DownloadToken`. |

The pillar materialisation step is the contract between the app and Salt:

```yaml
osbakery:
  build_id: "...uuid..."
  recipe: family-arcade
  recipe_version: "1.0.0"
  operating_system: batocera
  hardware_target: rpi5
  label: kitchen-arcade
options:
  admin_username: newt
  admin_ssh_keys:
    - ssh-ed25519 AAAA...
  wifi_ssid: Bakery
  wifi_password: hunter2
  timezone: Europe/Prague
  boot_to_arcade: true
# ... + anything from RecipeVersion.pillar_overrides
```

Salt states should *only* read from `pillar['options']` and `pillar['osbakery']` for build-time context, plus their own per-formula namespace (e.g. `pillar['batocera']` for batocera-specific defaults).

## 5. The user downloads

The serializer's `tokens` field returns one or more URLs like `https://bakery.example.com/d/<token>/`. The view at `builds.views.download_artifact`:

- 404s on revoked / expired / over-used tokens (no leak of which).
- Increments `use_count`, sets `last_used_at`.
- Streams the file via `FileResponse` straight from the `artifacts` storage backend.
- Adds `X-Checksum-SHA256` so clients can verify.

## 6. Cleanup

Two retention deadlines are tracked:

- `Artifact.expires_at` — purge the file (and the row) after this.
- `DownloadToken.expires_at` — token stops working after this.

A future `cleanup` management command (or Celery beat task) will sweep both. Until then, run it manually.

## State diagram

```
        queued ──▶ preparing ──▶ building ──▶ finalizing ──▶ succeeded
           │           │            │              │
           │           ▼            ▼              ▼
           └────────▶ failed ◀── failed ◀───── failed
           │
           └─────▶ cancelled
                       │
                       └─▶ expired (set by retention job)
```

`BuildRequest.is_terminal` returns True for `succeeded / failed / cancelled / expired`.
