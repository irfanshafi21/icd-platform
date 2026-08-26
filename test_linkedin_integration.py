import unittest
from unittest.mock import patch

import linkedin_integration as linkedin


class LinkedInOAuthStateTests(unittest.TestCase):
    def setUp(self):
        linkedin._pending_oauth_states.clear()

    def tearDown(self):
        linkedin._pending_oauth_states.clear()

    def test_oauth_state_restores_originating_app_session_once(self):
        original_session = {
            "_supabase_client": object(),
            "auth_company": {"id": "company-1"},
            "auth_user": {"id": "user-1"},
        }
        callback_session = {}

        with patch.object(linkedin.st, "session_state", original_session):
            linkedin._stash_oauth_state("state-1")

        context = linkedin._consume_oauth_state("state-1")
        self.assertIsNotNone(context)
        self.assertIsNone(linkedin._consume_oauth_state("state-1"))

        with patch.object(linkedin.st, "session_state", callback_session):
            linkedin._restore_oauth_session(context)

        self.assertEqual(callback_session["auth_company"], {"id": "company-1"})
        self.assertEqual(callback_session["auth_user"], {"id": "user-1"})
        self.assertIs(callback_session["_supabase_client"], original_session["_supabase_client"])


if __name__ == "__main__":
    unittest.main()
