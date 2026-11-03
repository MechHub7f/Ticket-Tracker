"""Smoke tests for the Ticket Tracker backend (stdlib unittest)."""

import os
import sys
import tempfile
import unittest
from datetime import date as date_cls, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import auth, services  # noqa: E402
from server.db import Database  # noqa: E402


class TicketTrackerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db = Database(f"sqlite:///{self._tmp.name}")
        self.db.init_schema()
        from server.seed import seed_demo

        seed_demo(self.db)
        self.admin_id = auth.create_user(self.db, "tester", "password123", "Tester", "admin")

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_generate_tickets(self):
        today = services.today_iso()
        result = services.generate_tickets(self.db, today)
        self.assertEqual(result["created"], 0)  # seed already made today's

    def test_bulk_add_and_remove(self):
        tickets = services.list_tickets(self.db, service_date=services.today_iso())
        ids = [t["id"] for t in tickets[:5]]
        items = services.list_items(self.db)
        juice = next(i for i in items if i["name"] == "Coffee")

        result = services.bulk_add_items(self.db, ids, [juice["id"]], qty=2)
        self.assertTrue(result["applied"])
        for t in services.list_tickets(self.db, service_date=tickets[0]["service_date"], ids=ids):
            match = [i for i in t["items"] if i["item_id"] == juice["id"]]
            self.assertEqual(match[0]["qty"], 2)

        removed = services.bulk_remove_items(self.db, ids, [juice["id"]])
        self.assertTrue(removed["applied"])
        for t in services.list_tickets(self.db, service_date=tickets[0]["service_date"], ids=ids):
            self.assertFalse([i for i in t["items"] if i["item_id"] == juice["id"]])

    def test_allergy_conflict_blocks_add(self):
        residents = services.list_residents(self.db, q="Stanley")
        resident = residents[0]
        self.assertIn("Peanut", resident["allergies"])
        cookies = services.list_items(self.db, q="Peanut")
        cookie = cookies[0]

        ticket_id = services.create_ticket(
            self.db, {"resident_id": resident["id"], "date": services.today_iso(), "meal": "snack"}
        )
        result = services.bulk_add_items(self.db, [ticket_id], [cookie["id"]])
        self.assertFalse(result["applied"])
        self.assertGreaterEqual(len(result["conflicts"]), 1)
        self.assertTrue(
            any("peanut" in c["reason"].lower() for c in result["conflicts"]),
            f"Expected a peanut conflict, got: {result['conflicts']}",
        )

        forced = services.bulk_add_items(self.db, [ticket_id], [cookie["id"]], force=True)
        self.assertTrue(forced["applied"])

    def test_replace_item(self):
        tickets = services.list_tickets(self.db, service_date=services.today_iso())
        with_item = next(t for t in tickets if t["items"])
        from_item = with_item["items"][0]
        items = services.list_items(self.db)
        to_item = next(i for i in items if i["id"] != from_item["item_id"])

        result = services.bulk_replace_item(
            self.db, [with_item["id"]], from_item["item_id"], to_item["id"]
        )
        self.assertTrue(result["applied"])
        fresh = services.get_ticket(self.db, with_item["id"])
        self.assertIn(to_item["id"], [i["item_id"] for i in fresh["items"]])

    def test_export_csv(self):
        csv_text = services.export_tickets_csv(
            self.db, services.today_iso(), services.today_iso()
        )
        self.assertIn("Resident", csv_text)
        self.assertGreater(len(csv_text.splitlines()), 1)

    def test_auth_roundtrip(self):
        token, user = auth.login(self.db, "tester", "password123")
        self.assertEqual(user["username"], "tester")
        self.assertIsNotNone(auth.get_session_user(self.db, token))
        auth.logout(self.db, token)
        self.assertIsNone(auth.get_session_user(self.db, token))

    # ------------------------------------------------------ compliance tests
    def test_consent_required_for_medical_data(self):
        today = services.today_iso()
        # Adding a resident WITH allergies and no consent date must fail.
        with self.assertRaises(ValueError):
            services.create_resident(
                self.db,
                {"name": "No Consent", "allergies": "Peanuts", "diet": ""},
            )
        # With a consent date it succeeds.
        resident_id = services.create_resident(
            self.db,
            {"name": "With Consent", "allergies": "Peanuts", "consent_date": today},
        )
        resident = services.get_resident(self.db, resident_id)
        self.assertEqual(resident["consent_date"], today)

        # Updating a resident with NO consent to have allergies must fail.
        plain_id = services.create_resident(self.db, {"name": "Plain Resident"})
        with self.assertRaises(ValueError):
            services.update_resident(
                self.db, plain_id, {"allergies": "Shellfish"}
            )
        # Recording consent first, then allergies, works.
        services.update_resident(self.db, plain_id, {"consent_date": today})
        services.update_resident(self.db, plain_id, {"allergies": "Shellfish"})

    def test_retention_purge(self):
        # Create an inactive resident with an old ticket and a current one.
        today = services.today_iso()
        resident_id = services.create_resident(
            self.db,
            {
                "name": "Gone Resident",
                "active": 0,
                "consent_date": today,
            },
        )
        old_date = (date_cls.today() - timedelta(days=3650)).isoformat()
        old_ticket = services.create_ticket(
            self.db, {"resident_id": resident_id, "date": old_date, "meal": "lunch"}
        )
        items = services.list_items(self.db)
        services.add_item_to_ticket(self.db, old_ticket, items[0]["id"])

        recent_ticket = services.create_ticket(
            self.db, {"resident_id": resident_id, "date": today, "meal": "lunch"}
        )
        services.add_item_to_ticket(self.db, recent_ticket, items[0]["id"])

        result = services.purge_old_data(self.db, years=7)
        self.assertGreaterEqual(result["removed_tickets"], 1)
        remaining = services.list_tickets(self.db, resident_id=resident_id)
        remaining_ids = [t["id"] for t in remaining]
        self.assertNotIn(old_ticket, remaining_ids)
        self.assertIn(recent_ticket, remaining_ids)

    def test_active_only_filter(self):
        today = services.today_iso()
        inactive = services.create_resident(
            self.db, {"name": "Hidden Resident", "active": 0, "consent_date": today}
        )
        services.create_ticket(
            self.db, {"resident_id": inactive, "date": today, "meal": "lunch"}
        )
        # staff view: active residents only
        staff_view = services.list_tickets(self.db, service_date=today, active_only=True)
        self.assertFalse(any(t["resident_id"] == inactive for t in staff_view))
        # admin view: includes inactive residents
        admin_view = services.list_tickets(self.db, service_date=today, active_only=False)
        self.assertTrue(any(t["resident_id"] == inactive for t in admin_view))


if __name__ == "__main__":
    unittest.main()
