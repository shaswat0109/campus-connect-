# Events API

This Flask backend uses the existing Supabase `public.events`, `public.users`,
and `public.registrations` tables.

1. Run [registration.sql](registration.sql) in the Supabase SQL Editor. It adds
   a uniqueness index and the database function that checks capacity and creates
   registrations in a single transaction. If the index fails because existing
   rows share an event and user, reconcile those duplicates before retrying.
2. Keep `SUPABASE_URL` in your local `.env` and add `SUPABASE_SECRET_KEY` or
   `SUPABASE_SERVICE_ROLE_KEY` using the corresponding server key from your
   Supabase project.
3. Run `python -m pip install -r requirements.txt` and `python app.py`.
   The development server listens on `http://127.0.0.1:5000`.

## Deploying to Render

Create a Render Web Service with `backend` as its root directory. Use
`pip install -r requirements.txt` as the build command and
`gunicorn app:app --bind 0.0.0.0:$PORT` as the start command. Add `SUPABASE_URL`
and either `SUPABASE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY` as Render
environment variables; do not commit `.env` or server keys.

This API does not authenticate callers. A public deployment allows anyone who
knows the relevant UUIDs to call its endpoints, so add caller authentication
and access controls before using it with real user data.

| Method | Route | Inputs and results |
| --- | --- | --- |
| GET | `/api/events` | Browse events. |
| GET | `/api/events/{id}` | Fetch an event by UUID. |
| POST | `/api/registrations` | Send JSON with `user_id` and `event_id`. Returns `201` on success, `409` for an existing registration or a full event, and `404` for a missing user or event. |
| GET | `/api/me/registrations?user_id={uuid}` | List registrations for the supplied user UUID. |
| GET | `/api/events/{id}/registrations?organizer_id={uuid}` | List attendee registrations. Returns `403` if the supplied UUID differs from the event's organizer. |

List routes accept `limit` (1 to 100, default 100) and `offset` (default 0).
A null event capacity allows unlimited registrations. Event status is returned
as stored because the schema image does not specify allowed status values.

Callers need no login or API key. Anyone who knows the relevant UUIDs can
submit them; see the deployment warning above.
