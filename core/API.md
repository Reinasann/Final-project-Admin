# Smart Recycle API

Base URL: `/api/v1/`. Flutter endpoints use `Authorization: Bearer <access_token>` after login. All bodies are JSON. Each machine reports the three classified waste types: `plastic`, `glass`, and `can`.

| Method and path | Purpose |
| --- | --- |
| `POST /auth/login/` | Log in with `email`, `password`; token remains valid until logout, account suspension, password reset, or server-side revocation. |
| `POST /auth/logout/` | Revoke the Bearer token currently in use. |
| `POST /auth/password-reset/request/` | Send a six-digit reset code to `email`; the code expires in 10 minutes. |
| `POST /auth/password-reset/confirm/` | Reset with `email`, `code`, `new_password`; all existing tokens are revoked. |
| `GET /me/` | Current profile. |
| `POST /me/push-devices/register/` | Register the signed-in device's FCM `token` and `platform`. |
| `POST /me/push-devices/unregister/` | Disable the supplied FCM `token` for the signed-in user. |
| `PATCH /me/profile/` | Update `name`, `phone`. |
| `POST /me/change-password/` | Send `old_password`, `new_password`. |
| `GET /machines/` | Super admins see every machine; other users see every machine in their organization. Each result includes `caretakers` (multiple users), the legacy first `caretaker`, and a `can_operate` flag. |
| `GET /machines/{id}/` | One machine. |
| `PATCH /machines/{id}/status/` | Persist machine status with boolean `is_on`; any assigned caretaker only. |
| `GET /machines/{id}/telemetry/?limit=60` | Recent history, maximum 500 readings. |
| `GET /collections/?mine=1` | Collection history; `mine=1` limits results to records collected by the signed-in user. |
| `POST /collections/create/` | Save a manual collection: `machine_id`, `waste_type`, `weight_kg`, optional `label_code`; any assigned caretaker only. The machine must be `Offline`; otherwise the API returns `409`. |
| `GET /issues/?mine=1` | Issues for visible machines; `mine=1` limits results to reports created by the signed-in user. |
| `GET /issue-categories/` | Active issue categories for the report form. |
| `POST /issues/create/` | Create an issue: `machine_id`, `category_id`, `description`; any assigned caretaker only. |
| `GET /notifications/` | Signed-in user's alerts. |
| `POST /notifications/{id}/read/` | Mark one alert as read. |
| `POST /notifications/{id}/acknowledge/` | Accept an actionable full-bin alert. The first acceptance wins and other active users in the organization receive a notification naming the accepting user. |

During local development, password-reset email uses Django's console backend and
the response includes `debug_code` while `DEBUG=True`. For deployment, configure
`EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL`.

## ESP32 telemetry

`POST /iot/telemetry/` uses `X-Device-Key` instead of a user token. The ESP32 sends the values it already calculated; the server validates and records them without deriving weight or level.

Turning a machine off in the app or admin system pauses telemetry ingestion for
30 minutes. Valid device submissions during the pause update only the device's
`last_seen_at` and return HTTP `409` with `accepted: false`,
`retry_after_seconds`, and `auto_online_at`; telemetry and current bin values are
not changed. After the pause expires, the next valid submission automatically
changes the machine to `Online` and is recorded with `auto_online: true`. A new
or otherwise `Offline` machine without a manual pause also becomes `Online` on
its first valid submission. Machines in `Maintenance` never auto-resume.

When a reported level reaches the bin's `full_threshold_percent`, the server
creates one active alert and delivers it to every active user in the machine's
organization. Repeated minute-by-minute readings do not create duplicates. A
new alert can be created after the level falls below the threshold and later
reaches it again.

```json
{
  "device_id": "ESP32-SR-001",
  "recorded_at": "2026-07-21T10:30:00+07:00",
  "bins": [
    {"waste_type": "plastic", "weight_kg": 4.25, "level_percent": 36.5},
    {"waste_type": "glass", "weight_kg": 12.40, "level_percent": 81.0},
    {"waste_type": "can", "weight_kg": 2.10, "level_percent": 20.0}
  ]
}
```

Create a `MachineInformation` row for each ESP32, set its API key with `device.set_api_key("secret")`, then attach it to its `Machine`. Store only the hash in SQLite. `Telemetry` is immutable historical data; `MachineBin.current_*` is the quick, latest-state read model.
