import inspect
import unittest
from unittest.mock import Mock, patch

import httpx
from postgrest import APIError
from supabase import create_client

import events_api as backend

EVENT = "10000000-0000-4000-8000-000000000001"
USER = "10000000-0000-4000-8000-000000000002"
ORGANIZER = "10000000-0000-4000-8000-000000000003"
BODY = {"event_id": EVENT, "user_id": USER}
ATTENDEES_PATH = f"/api/events/{EVENT}/registrations"
EVENT_ROW = {"id": EVENT, "title": "Workshop", "capacity": 1, "status": "open"}
REGISTRATION = {"id": "10000000-0000-4000-8000-000000000004", **BODY,
                "created_at": "2026-11-25T12:00:00Z"}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = backend.app.test_client()
        self.db = self.enterContext(patch.object(backend, "database")).return_value
        self.query = self.db.table.return_value.select.return_value
        self.query.eq.return_value = self.query
        self.query.limit.return_value = self.query
        self.query.order.return_value = self.query
        self.query.range.return_value = self.query
        self.enterContext(patch.dict("os.environ", {"ENABLE_DEMO_REGISTRATIONS": "true"}))

    def test_initialization_and_health(self):
        self.assertFalse(backend.app.debug)
        self.assertEqual(self.client.get("/health").json, {"status": "ok"})
        self.db.table.assert_not_called()

    def test_campus_page_serves_frontend_without_a_database_query(self):
        for path, mimetype in (
            ("/campus", "text/html"),
            ("/campus/styles.css", "text/css"),
            ("/campus/campus.js", "text/javascript"),
        ):
            with self.subTest(path=path), self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, mimetype)
        self.assertEqual(self.client.get("/campus/design/code.html").status_code, 404)
        with self.client.get("/campus") as response:
            self.assertIn(b"<h1>Campus <em>after class.</em></h1>", response.data)
            self.assertIn(b"async function loadEvents", response.data)
        self.db.table.assert_not_called()

    def test_root_event_summary(self):
        self.query.execute.return_value.data = [EVENT_ROW]
        with patch.dict("os.environ", {"ENABLE_DEMO_REGISTRATIONS": "false"}):
            response = self.client.get("/?limit=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {
            "events": [EVENT_ROW], "service": "event-registration-api", "status": "ok",
        })
        self.db.table.return_value.select.assert_called_once_with(backend.PUBLIC_EVENT_COLUMNS)
        self.query.range.assert_called_once_with(0, 0)

    def test_list_events(self):
        self.query.execute.return_value.data = [EVENT_ROW]
        response = self.client.get("/api/events?limit=5&offset=2")
        self.assertEqual(response.json, [EVENT_ROW])
        self.db.table.assert_called_once_with("events")
        self.query.range.assert_called_once_with(2, 6)

    def test_event_details_and_missing(self):
        self.query.execute.return_value.data = [EVENT_ROW]
        self.assertEqual(self.client.get(f"/api/events/{EVENT}").json, EVENT_ROW)
        self.query.eq.assert_called_once_with("id", EVENT)
        self.query.execute.return_value.data = []
        self.assertEqual(self.client.get(f"/api/events/{EVENT}").status_code, 404)

    def test_create_registration(self):
        self.db.rpc.return_value.execute.return_value.data = REGISTRATION
        response = self.client.post("/api/registrations", json=BODY)
        self.assertEqual((response.status_code, response.json), (201, REGISTRATION))
        self.db.rpc.assert_called_once_with(
            "register_for_event", {"p_user_id": USER, "p_event_id": EVENT}
        )

    def test_registration_database_errors(self):
        execute = self.db.rpc.return_value.execute
        for code, message, status in [
            ("PT409", "The event has reached capacity.", 409),
            ("PT409", "This user is already registered for the event.", 409),
            ("23505", "unique violation", 409),
            ("PT404", "User not found.", 404),
            ("23503", "foreign key violation", 404),
            ("PGRST202", "RPC missing", 503),
            ("42501", "permission denied", 503),
            ("XX000", "private database details", 502),
        ]:
            with self.subTest(code=code, message=message):
                execute.side_effect = APIError({"code": code, "message": message})
                response = self.client.post("/api/registrations", json=BODY)
                self.assertEqual(response.status_code, status)
                self.assertEqual(set(response.json), {"error"})
                self.assertNotIn("private database details", response.json["error"])

    def test_connection_error(self):
        self.query.execute.side_effect = httpx.ConnectError("private network details")
        self.assertEqual(self.client.get("/api/events").status_code, 503)

    def test_user_registrations(self):
        self.query.execute.return_value.data = [REGISTRATION]
        response = self.client.get(f"/api/me/registrations?user_id={USER}")
        self.assertEqual(response.json, [REGISTRATION])
        self.db.table.assert_called_once_with("registrations")
        self.query.eq.assert_called_once_with("user_id", USER)

    def test_organizer_registrations(self):
        self.query.execute.side_effect = [
            Mock(data=[{**EVENT_ROW, "organizer_id": ORGANIZER}]),
            Mock(data=[REGISTRATION]),
        ]
        response = self.client.get(f"{ATTENDEES_PATH}?organizer_id={ORGANIZER}")
        self.assertEqual(response.json, [REGISTRATION])
        self.query.eq.assert_any_call("event_id", EVENT)

    def test_organizer_mismatch_and_missing_event(self):
        self.query.execute.return_value.data = [{**EVENT_ROW, "organizer_id": ORGANIZER}]
        self.assertEqual(self.client.get(f"{ATTENDEES_PATH}?organizer_id={USER}").status_code, 403)
        self.query.execute.return_value.data = []
        self.assertEqual(self.client.get(f"{ATTENDEES_PATH}?organizer_id={ORGANIZER}").status_code, 404)

    def test_input_validation(self):
        for path in (
            "/api/events?limit=x", "/api/events?limit=101", "/api/events?offset=-1",
            "/api/events/bad", "/api/me/registrations", ATTENDEES_PATH,
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 400)
        for payload in ({}, [], {"user_id": 5, "event_id": EVENT}, {**BODY, "extra": 1}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/api/registrations", json=payload).status_code, 400)
        self.db.rpc.assert_not_called()
        self.assertEqual(self.client.post("/api/events").status_code, 405)

    def test_public_defaults(self):
        with patch.dict("os.environ", {"ENABLE_DEMO_REGISTRATIONS": "false"}):
            self.assertEqual(self.client.post("/api/registrations", json=BODY).status_code, 403)
            self.assertEqual(self.client.get(f"/api/me/registrations?user_id={USER}").status_code, 403)
            self.assertEqual(self.client.get(f"{ATTENDEES_PATH}?organizer_id={ORGANIZER}").status_code, 403)
            self.db.table.assert_not_called()
            self.query.execute.return_value.data = [EVENT_ROW]
            self.assertEqual(self.client.get("/api/events").status_code, 200)
            self.db.table.return_value.select.assert_called_once_with("id,title,capacity,status")


class SdkTests(unittest.TestCase):
    def test_installed_client_builders(self):
        client = create_client("https://example.supabase.co", "sb_secret_fake_test")
        table = client.table("events")
        self.assertIn("columns", str(inspect.signature(table.select)))
        builder = table.select(backend.PUBLIC_EVENT_COLUMNS).order("id").range(0, 4)
        self.assertEqual(builder.request.params["limit"], "5")
        rpc = client.rpc("register_for_event", {"p_user_id": USER, "p_event_id": EVENT})
        self.assertEqual(rpc.request.json, {"p_user_id": USER, "p_event_id": EVENT})
