import os
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, render_template_string, request, send_from_directory
from httpx import RequestError
from postgrest import APIError
from supabase import SupabaseException, create_client
from werkzeug.exceptions import HTTPException

load_dotenv(Path(__file__).with_name(".env"))

app = Flask(__name__)
app.config.update(DEBUG=False, MAX_CONTENT_LENGTH=16 * 1024)
PUBLIC_EVENT_COLUMNS = "id,title,capacity,status"
EVENT_COLUMNS = f"{PUBLIC_EVENT_COLUMNS},organizer_id"
REGISTRATION_COLUMNS = "id,user_id,event_id,created_at"
FRONTEND_DIRECTORY = Path(__file__).resolve().parent.parent / "frontend"


def demo_registrations_enabled():
    return os.getenv("ENABLE_DEMO_REGISTRATIONS") == "true"


@app.before_request
def require_demo_data():
    if request.endpoint in {
        "create_registration", "list_user_registrations", "list_event_registrations"
    } and not demo_registrations_enabled():
        abort(403, description="Registration routes require synthetic demo data.")


def database():
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    url = os.getenv("SUPABASE_URL")
    if not url or not key:
        abort(503, description="Configure SUPABASE_URL and a Supabase server key.")
    try:
        return create_client(url, key)
    except SupabaseException:
        abort(503, description="Check the Supabase server configuration.")


def uuid_value(value, field):
    try:
        return str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        abort(400, description=f"{field} must be a UUID.")


def pagination():
    try:
        limit = int(request.args.get("limit", "100"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        abort(400, description="limit and offset must be integers.")
    if not 1 <= limit <= 100 or not 0 <= offset <= 2_147_483_647 - limit:
        abort(400, description="limit must be 1 to 100 and offset must be a valid nonnegative row offset.")
    return offset, offset + limit - 1


def page(query, bounds):
    return query.order("id").range(*bounds).execute().data


def find_event(client, event_id, columns):
    rows = (
        client.table("events").select(columns)
        .eq("id", event_id).limit(1).execute().data
    )
    if not rows:
        abort(404, description="Event not found.")
    return rows[0]


@app.errorhandler(HTTPException)
def http_error(error):
    response = error.get_response()
    response.set_data(app.json.dumps({"error": error.description}))
    response.content_type = "application/json"
    return response


@app.errorhandler(APIError)
def database_error(error):
    expected_errors = {
        "PT404": (404, "User or event not found."),
        "PT409": (409, error.message if error.message in {
            "This user is already registered for the event.",
            "The event has reached capacity.",
        } else "Registration conflict."),
        "42501": (503, "Database permissions require server configuration."),
        "23505": (409, "This user is already registered for the event."),
        "23503": (404, "The user or event no longer exists."),
        "PGRST202": (503, "Apply registration.sql to the Supabase database."),
    }
    if error.code in expected_errors:
        status, message = expected_errors[error.code]
        return jsonify(error=message), status
    app.logger.error("Supabase query failed (code %s)", error.code)
    return jsonify(error="Database request failed."), 502


@app.errorhandler(RequestError)
def database_connection_error(error):
    app.logger.error("Supabase connection failed (%s)", type(error).__name__)
    return jsonify(error="Database is temporarily unavailable."), 503


@app.get("/")
def index():
    return jsonify(events=event_rows(), service="event-registration-api", status="ok")


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/campus")
@app.get("/campus/")
def campus():
    return render_template_string(
        (FRONTEND_DIRECTORY / "index.html").read_text(encoding="utf-8"),
        campus_css=(FRONTEND_DIRECTORY / "styles.css").read_text(encoding="utf-8"),
        campus_js=(FRONTEND_DIRECTORY / "campus.js").read_text(encoding="utf-8"),
    )


@app.get("/campus/<any(styles.css,campus.js):filename>")
def campus_asset(filename):
    return send_from_directory(FRONTEND_DIRECTORY, filename)


def event_rows():
    bounds = pagination()
    columns = EVENT_COLUMNS if demo_registrations_enabled() else PUBLIC_EVENT_COLUMNS
    return page(database().table("events").select(columns), bounds)


@app.get("/api/events")
def list_events():
    return jsonify(event_rows())


@app.get("/api/events/<event_id>")
def get_event(event_id):
    event_id = uuid_value(event_id, "event_id")
    columns = EVENT_COLUMNS if demo_registrations_enabled() else PUBLIC_EVENT_COLUMNS
    return jsonify(find_event(database(), event_id, columns))


@app.post("/api/registrations")
def create_registration():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"user_id", "event_id"}:
        abort(400, description="Send a JSON object with user_id and event_id.")
    user_id = uuid_value(body.get("user_id"), "user_id")
    event_id = uuid_value(body.get("event_id"), "event_id")
    response = database().rpc(
        "register_for_event", {"p_user_id": user_id, "p_event_id": event_id}
    ).execute()
    return jsonify(response.data), 201


@app.get("/api/me/registrations")
def list_user_registrations():
    user_id = uuid_value(request.args.get("user_id"), "user_id")
    bounds = pagination()
    query = database().table("registrations").select(REGISTRATION_COLUMNS)
    return jsonify(page(query.eq("user_id", user_id), bounds))


@app.get("/api/events/<event_id>/registrations")
def list_event_registrations(event_id):
    event_id = uuid_value(event_id, "event_id")
    organizer_id = uuid_value(request.args.get("organizer_id"), "organizer_id")
    bounds = pagination()
    client = database()
    event = find_event(client, event_id, EVENT_COLUMNS)
    if event["organizer_id"] != organizer_id:
        abort(403, description="organizer_id must match the event organizer.")
    query = client.table("registrations").select(REGISTRATION_COLUMNS)
    return jsonify(page(query.eq("event_id", event_id), bounds))
