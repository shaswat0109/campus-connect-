# AI Workshop Events API

Flask exposes the event and registration REST contract over the existing Supabase PostgreSQL tables. Gunicorn serves the same Flask app on Render. The API uses JSON and has no login.

```text
backend/
  run.py                         Flask and Gunicorn entry point
  events_api.py                  Routes, validation and Supabase queries
  registration.sql               Atomic registration function and uniqueness index
  requirements.txt               Pinned Python dependencies
  .env.example                   Configuration template
  events.postman_collection.json Importable requests
  tests/                         Mocked, SDK and opt-in Supabase tests
.gitignore
render.yaml
```

## Local setup in VS Code

Open the project folder, then open a PowerShell terminal at its root. The existing `.venv` uses standalone Python 3.13.15. To create it on another Windows machine, use its standalone Python executable explicitly.

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
if (-not (Test-Path .\backend\.env)) { Copy-Item .\backend\.env.example .\backend\.env }
code .\backend\.env
& .\.venv\Scripts\python.exe .\backend\run.py
```

In VS Code, select `.venv\Scripts\python.exe` via **Python – Select Interpreter**. The explicit executable works without activating a PowerShell script. In a second terminal, run `Invoke-RestMethod http://127.0.0.1:5000/health`.

## Supabase configuration

| Variable | Value |
| --- | --- |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SECRET_KEY` | Server-side Supabase secret key |
| `SUPABASE_SERVICE_ROLE_KEY` | Legacy server key accepted as an alternative |
| `ENABLE_DEMO_REGISTRATIONS` | Defaults to disabled. Use `true` only against a project containing synthetic data. |
| `PYTHON_VERSION` | Render setting, `3.13.15` |
| `FLASK_DEBUG` | Render setting, `0` |

Set the URL and one server key in `backend/.env` or in Render secrets. The server role bypasses RLS for its own queries. Keep RLS enabled and keep the key out of Git, logs and Postman. The default public event responses omit organizer identifiers. Registration routes require explicit synthetic demo mode because UUIDs supplied by callers only select fixtures. With no login, they cannot establish caller identity or organizer ownership.

The diagram shows UUID primary keys for `users`, `events` and `registrations`. The registration user and event columns reference their respective tables, and the event organizer references `users.id`. User email and role are outside the API responses.

In the approved **development** Supabase project, open SQL Editor and run [registration.sql](registration.sql) using an authorized database administrator. The function checks event and user existence, duplicate registration and capacity before inserting. A transaction-scoped advisory lock serializes requests per event, and a unique index enforces one registration per user and event. Any other registration writer must call the same function to participate in the capacity check. A null capacity allows unlimited registrations. If index creation reports existing duplicate pairs, reconcile those records before retrying. The script does not create tables or change RLS settings.

## API contract

All GET requests have an empty body. List routes accept optional integer `limit` (1–100, default 100) and `offset` (default 0) and sort by ID. Required IDs are UUIDs. Successful lists return arrays, including `[]` for no results. Errors return an object such as `{"error":"Event not found."}`.

| Method and URL | Request | Success response | Endpoint errors |
| --- | --- | --- | --- |
| `GET /` | None | `200 {"service":"Events API"}` | — |
| `GET /health` | None | `200 {"status":"ok"}` | — |
| `GET /api/events?limit=10&offset=0` | Optional paging | `200` array of events | `400` invalid paging |
| `GET /api/events/{event_id}` | Event UUID in path | `200` event object | `400` invalid UUID, `404` missing event |
| `POST /api/registrations` | JSON object with `user_id` and `event_id` | `201` registration object | `400` invalid body, `403` demo mode disabled, `404` missing event or user, `409` duplicate or full event, `413` body over 16 KiB |
| `GET /api/me/registrations?user_id={user_id}` | User UUID and optional paging | `200` array of that fixture user's registrations | `400` invalid input, `403` demo mode disabled |
| `GET /api/events/{event_id}/registrations?organizer_id={organizer_id}` | Event UUID, stored organizer UUID and optional paging | `200` array of event registrations | `400` invalid input, `403` demo mode disabled or organizer UUID mismatch, `404` missing event |

Database endpoints can return `502` for an unexpected database response and `503` for unavailable database access, missing configuration, insufficient permissions or the missing registration function. Unsupported methods return `405`. The health endpoint checks Flask process liveness.

Example event object. With synthetic demo mode enabled, the object also includes `organizer_id`.

```json
{"id":"10000000-0000-4000-8000-000000000001","title":"Workshop","capacity":10,"status":"open"}
```

Example registration request with `Content-Type: application/json`.

```json
{"user_id":"10000000-0000-4000-8000-000000000002","event_id":"10000000-0000-4000-8000-000000000001"}
```

Example registration response. The two registration list endpoints return arrays of these objects.

```json
{"id":"10000000-0000-4000-8000-000000000004","user_id":"10000000-0000-4000-8000-000000000002","event_id":"10000000-0000-4000-8000-000000000001","created_at":"2026-11-25T12:00:00Z"}
```

## Tests and Postman

```powershell
Push-Location .\backend
& ..\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_events_api*.py" -v
& ..\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_supabase_integration.py" -v
Pop-Location
```

The first command exercises Flask with mocked database operations and constructs requests with the installed SDK without network access. The second suite is skipped by default. To run it, provision a disposable Supabase project with the diagram tables and the function, two synthetic users, and a dedicated empty event with capacity 1. Set `SUPABASE_TEST_DISPOSABLE=true`, `SUPABASE_TEST_URL`, `SUPABASE_TEST_SECRET_KEY`, `SUPABASE_TEST_EVENT_ID`, `SUPABASE_TEST_USER_1` and `SUPABASE_TEST_USER_2` in the test process environment. It sends two concurrent writes, verifies one seat was filled and checks duplicate handling. Its cleanup deletes the registration created by the test, so the test key needs delete access in the disposable project.

Import [events.postman_collection.json](events.postman_collection.json). Set `base_url` to `http://127.0.0.1:5000` or your Render HTTPS URL without a trailing slash. Fill `event_id`, `user_id` and `organizer_id` with development fixture IDs. Send Create registration twice to check `201` followed by `409`. The collection's success assertions expect `201` on the create request, so the deliberate duplicate returns a failed success assertion.

## GitHub

The target is `shaswat0109/campus-connect-` on `main`. Use the prepared checkout to preserve GitHub history and avoid the unrelated parent Git repository. Review the changed files before committing. Run the push command only when you want to publish.

```powershell
git -C .venv/campus-connect-deploy remote -v
git -C .venv/campus-connect-deploy status --short
git -C .venv/campus-connect-deploy diff --cached --stat
git -C .venv/campus-connect-deploy diff --cached
git -C .venv/campus-connect-deploy commit -m "Complete Flask events API and Render configuration"
git -C .venv/campus-connect-deploy push -u origin main
```

If Git rejects a non-fast-forward push, fetch and review the updated remote branch before integrating it. Preserve the remote history.

## Render

Use the root [render.yaml](../render.yaml) as a Blueprint or enter these settings manually.

| Dashboard field | Value |
| --- | --- |
| Service type | Web Service |
| Repository | `shaswat0109/campus-connect-` |
| Runtime | Python |
| Branch | `main` |
| Root Directory | `backend` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn --bind 0.0.0.0:$PORT run:app` |
| Health Check Path | `/health` |
| Auto-Deploy | Off |

Add the environment variables above. The Blueprint uses `SUPABASE_SECRET_KEY`. If using the legacy key, replace that environment entry with `SUPABASE_SERVICE_ROLE_KEY`. For an existing native Rust service, open **Settings → Build → Source → Edit** and select the backing repository to edit the runtime and commands. Saving that source change deploys the service. If that option is unavailable, create a new Python Web Service with the same settings. Once deployed, verify `/health` and perform a database-backed `GET /api/events`. [Render runtime documentation](https://render.com/docs/native-runtimes)

## Troubleshooting

- **`_rust` DLL import error.** Confirm the terminal is running `.venv\Scripts\python.exe` and that the venv was created with standalone Python. If Windows Application Control blocks the interpreter or a DLL, ask your administrator to approve the specific executable or dependency.
- **`cargo build --release` or missing `Cargo.toml`.** Set the Render runtime to Python and verify the build command and root directory.
- **Database permission errors.** Confirm the project URL, server credential and the privileges for `service_role`. A publishable key cannot execute the registration function. Keep RLS enabled.
- **Registration function missing.** Apply the approved SQL in the intended development project and wait for PostgREST to reload its schema.
- **`select()` rejects `count=`.** Verify the requirements were installed in the selected interpreter. Pagination uses SDK column selection and ranges, and the capacity count runs inside PostgreSQL.
