"""Opt-in concurrency check for disposable Supabase fixtures only."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor

from postgrest import APIError
from supabase import create_client


@unittest.skipUnless(os.getenv("SUPABASE_TEST_DISPOSABLE") == "true",
                     "requires a disposable Supabase project and dedicated fixtures")
class SupabaseIntegrationTests(unittest.TestCase):
    def test_two_requests_compete_for_one_empty_seat(self):
        url = os.environ["SUPABASE_TEST_URL"]
        key = os.environ["SUPABASE_TEST_SECRET_KEY"]
        event_id = os.environ["SUPABASE_TEST_EVENT_ID"]
        users = (os.environ["SUPABASE_TEST_USER_1"], os.environ["SUPABASE_TEST_USER_2"])
        self.assertNotEqual(*users)
        client = create_client(url, key)
        self.assertEqual(client.table("events").select("capacity").eq("id", event_id)
                         .execute().data, [{"capacity": 1}])
        self.assertEqual(client.table("registrations").select("id").eq("event_id", event_id)
                         .limit(1).execute().data, [])

        def register(user_id):
            worker = create_client(url, key)
            try:
                result = worker.rpc("register_for_event", {
                    "p_user_id": user_id, "p_event_id": event_id,
                }).execute().data
                return "created", result["id"]
            except APIError as error:
                return error.code, error.message

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(register, users))
        for status, registration_id in results:
            if status == "created":
                self.addCleanup(lambda record_id=registration_id: client.table("registrations")
                                .delete().eq("id", record_id).execute())

        self.assertEqual(sorted(status for status, _ in results), ["PT409", "created"])
        self.assertIn(("PT409", "The event has reached capacity."), results)
        rows = client.table("registrations").select("id,user_id").eq("event_id", event_id).execute().data
        self.assertEqual(len(rows), 1)
        with self.assertRaises(APIError) as duplicate:
            client.rpc("register_for_event", {
                "p_user_id": rows[0]["user_id"], "p_event_id": event_id,
            }).execute()
        self.assertEqual(duplicate.exception.code, "PT409")
        self.assertEqual(duplicate.exception.message, "This user is already registered for the event.")
