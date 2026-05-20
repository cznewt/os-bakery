# API reference

All endpoints return JSON and are mounted under `/api/`. Authentication is session-based by default; configure DRF auth classes in `osbakery/settings.py` as needed.

## Catalog (read-only)

| Method | Path                                       | Notes                                |
| ------ | ------------------------------------------ | ------------------------------------ |
| GET    | `/api/catalog/architectures/`              | List architectures.                  |
| GET    | `/api/catalog/architectures/{slug}/`       | Detail.                              |
| GET    | `/api/catalog/hardware-targets/`           | Filter by `architecture__slug`, `boot_method`, `is_active`. |
| GET    | `/api/catalog/hardware-targets/{slug}/`    | Detail.                              |
| GET    | `/api/catalog/operating-systems/`          | Filter by `kind`, `is_active`.       |
| GET    | `/api/catalog/operating-systems/{slug}/`   | Detail.                              |
| GET    | `/api/catalog/releases/`                   | Filter by `operating_system__slug`, `channel`, `is_default`. |
| GET    | `/api/catalog/releases/{id}/`              | Detail.                              |
| GET    | `/api/catalog/upstream-images/`            | Filter by `release__operating_system__slug`, `hardware_target__slug`, `format`. |
| GET    | `/api/catalog/upstream-images/{id}/`       | Detail.                              |

## Recipes (read-only)

| Method | Path                       | Notes                                                  |
| ------ | -------------------------- | ------------------------------------------------------ |
| GET    | `/api/recipes/`            | Filter by `operating_system__slug`, `status`, `visibility`. |
| GET    | `/api/recipes/{slug}/`     | Embeds `options[]`, `versions[]`, `current_version`.   |

## Builds

| Method | Path                       | Notes                                                  |
| ------ | -------------------------- | ------------------------------------------------------ |
| GET    | `/api/builds/`             | List your builds (filter by `status`, `hardware_target__slug`, `recipe_version__recipe__slug`). |
| POST   | `/api/builds/`             | Submit a new build (see below).                        |
| GET    | `/api/builds/{id}/`        | Detail, including timeline `events[]`, `artifact`, `tokens[]`. |

### Submitting a build

```http
POST /api/builds/
Content-Type: application/json

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

Response (`201 Created`):

```json
{
  "id": "0d24bb74-...",
  "status": "queued",
  "queued_at": "2026-05-20T12:34:56Z",
  "events": [],
  "tokens": []
}
```

Poll `GET /api/builds/{id}/` until `status == "succeeded"` and `tokens[]` is non-empty, or check `events` for progress.

## Downloads

| Method | Path                                  | Notes                                                  |
| ------ | ------------------------------------- | ------------------------------------------------------ |
| GET    | `/d/{token}/`                         | Streams the artifact. Sets `X-Checksum-SHA256` header. |

Returns `404` for revoked / expired / over-used tokens; does **not** distinguish between the failure modes (to avoid token-existence oracles).
