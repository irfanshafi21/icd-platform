import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import db


class PublicApplicationDeleteTests(unittest.TestCase):
    def test_delete_is_scoped_to_application_and_company(self):
        client = MagicMock()
        first_filter = client.table.return_value.delete.return_value.eq.return_value
        second_filter = first_filter.eq.return_value
        second_filter.execute.return_value = SimpleNamespace(data=[{"id": 42}])

        with patch.object(db, "_get_client", return_value=client), patch.object(
            db, "_current_company_id", return_value="company-1"
        ):
            self.assertTrue(db.delete_public_application(42))

        client.table.assert_called_once_with("public_applications")
        client.table.return_value.delete.return_value.eq.assert_called_once_with("id", 42)
        first_filter.eq.assert_called_once_with("company_id", "company-1")

    def test_delete_requires_a_signed_in_company(self):
        with patch.object(db, "_get_client", return_value=MagicMock()), patch.object(
            db, "_current_company_id", return_value=None
        ):
            self.assertFalse(db.delete_public_application(42))
            self.assertIn("signed-in company", db.get_last_error())


if __name__ == "__main__":
    unittest.main()
