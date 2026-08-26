import unittest
from unittest.mock import MagicMock, patch

import email_utils


class EmailFallbackTests(unittest.TestCase):
    def test_sender_domain_selects_expected_provider(self):
        self.assertEqual(email_utils._provider_for_sender("hr@gmail.com"), "Gmail")
        self.assertEqual(email_utils._provider_for_sender("hr@outlook.com"), "Outlook / Office 365")
        self.assertEqual(email_utils._provider_for_sender("hr@yahoo.com"), "Yahoo")

    def test_plain_email_falls_back_to_smtp_when_gas_fails(self):
        secrets = {
            "GAS_WEBHOOK_URL": "https://example.invalid/exec",
            "GAS_SECRET": "secret",
            "SMTP_EMAIL": "hr@gmail.com",
            "SMTP_APP_PASSWORD": "app-password",
        }
        smtp = MagicMock()
        smtp.return_value.__enter__.return_value = MagicMock()
        with (
            patch.object(email_utils, "is_gas_configured", return_value=True),
            patch.object(email_utils, "_get_secret", side_effect=lambda name: secrets.get(name)),
            patch.object(email_utils.requests, "post", side_effect=RuntimeError("relay unavailable")),
            patch.object(email_utils.smtplib, "SMTP", smtp),
        ):
            ok, message = email_utils.send_plain_email(
                "candidate@example.com", "Interview", "Details"
            )

        self.assertTrue(ok)
        self.assertIn("SMTP fallback", message)
        smtp.return_value.__enter__.return_value.sendmail.assert_called_once()

    def test_pdf_email_falls_back_to_smtp_when_gas_fails(self):
        secrets = {
            "SMTP_EMAIL": "hr@gmail.com",
            "SMTP_APP_PASSWORD": "app-password",
        }
        smtp = MagicMock()
        smtp.return_value.__enter__.return_value = MagicMock()
        with (
            patch.object(email_utils, "is_gas_configured", return_value=True),
            patch.object(email_utils, "_send_via_google_apps_script", return_value=(False, "relay failed")),
            patch.object(email_utils, "_get_secret", side_effect=lambda name: secrets.get(name)),
            patch.object(email_utils.smtplib, "SMTP", smtp),
        ):
            ok, message = email_utils.send_email_with_pdf(
                "candidate@example.com", "Offer", "Congratulations",
                b"pdf", "offer.pdf",
            )

        self.assertTrue(ok)
        self.assertIn("SMTP fallback", message)
        smtp.return_value.__enter__.return_value.sendmail.assert_called_once()


if __name__ == "__main__":
    unittest.main()
