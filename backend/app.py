import os
from uuid import UUID

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request
from httpx import RequestError
from postgrest import APIError
from supabase import create_client
from werkzeug.exceptions import HTTPException

load_dotenv()

app = Flask(__name__)
EVENT_COLUMNS = "id,organizer_id,title,capacity,status"
REGISTRATION_COLUMNS = "id,user_id,event_id,created_at"


def database():
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    url = os.getenv("SUPABASE_URL")
    if not url or not key:
        abort(503, description="Configure SUPABASE_URL and a Supabase server key.")
    return create_client(url, key)


def uuid_value(value, field):
    try:
        return str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        abort(400, description=f"{field} must be a UUID.")


def page(query):
    try:
        limit = int(request.args.get("limit", "100"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        abort(400, description="limit and offset must be integers.")
    if not 1 <= limit <= 100 or not 0 <= offset <= 2_147_483_647 - limit:
        abort(400, description="limit must be 1 to 100 and offset must be a valid nonnegative row offset.")
    return query.order("id").range(offset, offset + limit - 1).execute().data


def find_event(client, event_id):
    rows = (
        client.table("events").select(EVENT_COLUMNS)
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
        "PT404": (404, error.message),
        "PT409": (409, error.message),
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
    return jsonify(service="Events API")


@app.get("/api/events")
def list_events():
    return jsonify(page(database().table("events").select(EVENT_COLUMNS)))


@app.get("/api/events/<event_id>")
def get_event(event_id):
    event_id = uuid_value(event_id, "event_id")
    return jsonify(find_event(database(), event_id))


@app.post("/api/registrations")
def create_registration():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
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
    query = database().table("registrations").select(REGISTRATION_COLUMNS)
    return jsonify(page(query.eq("user_id", user_id)))


@app.get("/api/events/<event_id>/registrations")
def list_event_registrations(event_id):
    event_id = uuid_value(event_id, "event_id")
    organizer_id = uuid_value(request.args.get("organizer_id"), "organizer_id")
    client = database()
    event = find_event(client, event_id)
    if event["organizer_id"] != organizer_id:
        abort(403, description="organizer_id must match the event organizer.")
    query = client.table("registrations").select(REGISTRATION_COLUMNS)
    return jsonify(page(query.eq("event_id", event_id)))


if __name__ == "__main__":
    app.run(host="127.0.0.1")
