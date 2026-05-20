# Operations

Runbook-style notes for operators.

## Adding a new operating system

1. `OperatingSystem.objects.create(slug=..., name=..., kind=..., vendor=...)`.
2. Create at least one `OSRelease` for it; mark one `is_default=True`.
3. Author a Packer template under `packer/<os>/<hw>/template.pkr.hcl`.
4. Add baseline Salt states under `salt/states/<os>/base/`.
5. `python manage.py sync_filesystem`.
6. Wire a recipe to it.

## Adding a new hardware target

1. `HardwareTarget.objects.create(slug=..., architecture=..., boot_method=...)`.
2. For each OS that supports it: either add a Packer template variant or extend an existing one with a new local path.
3. Create an `UpstreamImage` row for `(release, hardware_target)` pointing at the vendor URL.
4. Run Packer to populate `local_path` + checksum.
5. (Optional) Add the new target to relevant recipes' `supported_hardware`.

## Refreshing base images

Manual:
```sh
cd packer/raspios/rpi5
packer build template.pkr.hcl
python manage.py sync_filesystem
```

Scheduled (recommended): run `packer build` for each template via cron / GitHub Actions on a host with disk space; then have it `curl -X POST /api/admin/sync-filesystem` (TBD endpoint) or pull-down + run the management command via SSH.

## Reissuing a download link

```py
from datetime import timedelta
from django.utils import timezone
from builds.models import Artifact, DownloadToken

artifact = Artifact.objects.get(filename__contains="kitchen-arcade")
DownloadToken.objects.create(
    artifact=artifact,
    expires_at=timezone.now() + timedelta(hours=24),
    issued_to=request.user,
    note="re-issued via shell",
)
```

## Revoking a token

```py
DownloadToken.objects.get(token="...").revoke()
```

## Failing a stuck build

If a worker died mid-build, the row is left in `building` and stays that way. To clean up:

```py
from builds.models import BuildRequest
b = BuildRequest.objects.get(pk="...")
b.status = BuildRequest.Status.FAILED
b.failure_reason = "Worker died (manual cleanup)"
b.finished_at = timezone.now()
b.save()
```

The orchestrator's workspace under `BUILD_WORK_ROOT/<build-id>/` won't be cleaned up automatically — `rm -rf` it manually.

## Common failures

| Symptom                                       | Likely cause                                                  |
| --------------------------------------------- | ------------------------------------------------------------- |
| `Upstream image ... has no local_path`        | Packer hasn't refreshed yet, or `sync_filesystem` not run.    |
| `No upstream image for <release> on <hw>`     | Missing `UpstreamImage` row.                                  |
| `Base image missing on disk`                  | `local_path` is set but the file moved/got deleted.            |
| Build stays in `queued` forever               | Celery worker not running, or not subscribed to `builds` queue. |
| `xz: command not found` in worker logs        | Worker image missing the build toolchain.                     |

## Useful queries

```py
# How many builds last 24h, by status:
from django.db.models import Count
from django.utils import timezone
from datetime import timedelta
since = timezone.now() - timedelta(days=1)
BuildRequest.objects.filter(queued_at__gte=since).values('status').annotate(n=Count('id'))

# Recipes that have no current version yet:
Recipe.objects.exclude(versions__is_current=True)

# Tokens that will expire in the next 24h:
DownloadToken.objects.filter(expires_at__lt=timezone.now()+timedelta(days=1), revoked_at__isnull=True)
```
