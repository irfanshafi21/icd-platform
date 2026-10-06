import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from web_app import OWNER_EMAIL, _assistant_candidate, _candidate, _hiring_average, _interview_score, _is_completed_screening, _is_owner_email, _numeric_score, _screen_payloads, app, update_application, update_candidate


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_notification_preferences_require_the_matching_session(self):
        for role in ("candidate", "recruiter"):
            self.assertEqual(self.client.get("/api/notifications/" + role).status_code, 401)
            self.assertEqual(self.client.put("/api/notifications/" + role, json={"items": []}).status_code, 401)

    def test_notification_reads_merge_in_authenticated_user_metadata(self):
        from web_app import _notification_reads
        client = MagicMock()
        client.auth.get_user.return_value.user = SimpleNamespace(user_metadata={"icd_notification_reads_candidate": ["old"]})
        self.assertEqual(_notification_reads(client, "candidate", ["old", "new"]), {"items": ["old", "new"]})
        client.auth.update_user.assert_called_once_with({"data": {"icd_notification_reads_candidate": ["old", "new"]}})
        with self.assertRaises(HTTPException):
            _notification_reads(client, "candidate", ["x" * 501])

    @patch("web_app.requests.get")
    def test_google_login_always_requests_account_chooser(self, get):
        from urllib.parse import urlparse, parse_qs
        get.return_value.json.return_value = {"external": {"google": True}}
        response = self.client.get("/api/candidate/google", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        params = parse_qs(urlparse(response.headers["location"]).query)
        self.assertEqual(params["prompt"], ["select_account"])
        self.assertEqual(params["provider"], ["google"])
        self.assertEqual(params["code_challenge_method"], ["s256"])

    def test_health_and_spa_shell(self):
        self.assertEqual(self.client.get("/api/health").json()["service"], "icd-web")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("ICD Platform", response.text)
        self.assertIn("/favicon.ico", response.text)
        icon = self.client.get("/favicon.ico")
        self.assertEqual(icon.status_code, 200)
        self.assertIn("image/png", icon.headers["content-type"])
        self.assertEqual(self.client.get("/missing-page").status_code, 404)

    def test_privacy_policy_is_public_and_server_rendered(self):
        for path in ("/privacy", "/privacy/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/html", response.headers["content-type"])
            self.assertIn("Privacy Policy | ICD Platform", response.text)
            self.assertIn("Google sign-in", response.text)
            self.assertIn("without permanently erasing", response.text)
            self.assertNotIn('<div id="app">', response.text)

    def test_candidate_rows_are_normalized_for_frontend(self):
        row = {
            "id": 7,
            "candidate_name": "Asha",
            "profile_json": json.dumps({"skills": ["Python"], "years_experience": "3 years"}),
            "score_json": json.dumps({"overall_score": 84, "matched_skills": ["Python"]}),
            "decision_status": "Selected",
        }
        candidate = _candidate(row)
        self.assertEqual(candidate["score"], 84)
        self.assertEqual(candidate["skills"], ["Python"])
        self.assertEqual(candidate["decision_status"], "Selected")

    def test_candidate_rows_keep_structured_data_for_ai_assistant(self):
        candidate = _assistant_candidate({
            "candidate_name": "Asha",
            "profile_json": json.dumps({"skills": ["Python"]}),
            "score_json": json.dumps({"overall_score": 84, "breakdown": {"skills_match": 90}}),
        })
        self.assertEqual(candidate["name"], "Asha")
        self.assertEqual(candidate["profile"]["skills"], ["Python"])
        self.assertEqual(candidate["score"]["overall_score"], 84)

    def test_only_completed_screening_rows_reach_the_candidate_library(self):
        completed = {"filename": "asha.pdf",
                     "profile_json": json.dumps({"_screening_source": "Web Upload"}),
                     "score_json": "{}"}
        self.assertTrue(_is_completed_screening(completed))
        self.assertFalse(_is_completed_screening({"candidate_name": "Sample Candidate"}))
        self.assertFalse(_is_completed_screening({"filename": "legacy.pdf", "profile_json": "{}",
                                                  "score_json": "{}"}))

    def test_hiring_average_requires_both_scores_and_uses_strict_offer_gate(self):
        self.assertIsNone(_hiring_average(82, None))
        self.assertEqual(_hiring_average(82, 74), 78.0)
        self.assertEqual(_hiring_average(70, 70), 70.0)
        self.assertFalse((_hiring_average(70, 70) or 0) > 70)
        self.assertTrue((_hiring_average(71, 71) or 0) > 70)

    def test_scores_are_safely_normalized(self):
        self.assertEqual(_numeric_score("55"), 55)
        self.assertEqual(_numeric_score(120), 100)
        self.assertEqual(_numeric_score("invalid"), 0)

    def test_interview_scores_match_integer_database_contract(self):
        self.assertEqual(_interview_score("59"), 59)
        with self.assertRaises(HTTPException):
            _interview_score("59.5")
        with self.assertRaises(HTTPException):
            _interview_score(101)

    def test_owner_email_matching_is_case_insensitive(self):
        self.assertTrue(_is_owner_email(f"  {OWNER_EMAIL.upper()}  "))
        self.assertFalse(_is_owner_email("candidate@example.com"))

    @staticmethod
    def _rejection_session():
        candidate = {"id": 7, "company_id": "company", "job_id": 3, "candidate_name": "Asha",
                     "email": "asha@example.com", "job_role": "Engineer", "overall_score": 72,
                     "profile_json": "{}", "score_json": "{}"}
        tables = {}
        for name in ("screening_history", "public_applications", "interviews"):
            table = MagicMock()
            table.select.return_value = table
            table.update.return_value = table
            table.delete.return_value = table
            table.eq.return_value = table
            table.limit.return_value = table
            table.execute.return_value = SimpleNamespace(data=[candidate] if name == "screening_history" else [])
            tables[name] = table
        client = MagicMock()
        client.table.side_effect = lambda name: tables[name]
        return SimpleNamespace(client=client, company={"id": "company", "name": "Acme"}), tables

    @patch("web_app._send_company_email", return_value=(False, "relay unavailable"))
    def test_rejection_keeps_candidate_when_email_fails(self, _send):
        session, tables = self._rejection_session()
        with self.assertRaises(HTTPException) as caught:
            update_candidate(7, {"status": "Rejected"}, session)
        self.assertEqual(caught.exception.status_code, 502)
        tables["screening_history"].delete.assert_not_called()
        tables["public_applications"].delete.assert_not_called()

    @patch("web_app._send_company_email", return_value=(True, "sent"))
    def test_rejection_emails_then_erases_company_candidate_data(self, _send):
        session, tables = self._rejection_session()
        result = update_candidate(7, {"status": "Rejected"}, session)
        self.assertTrue(result["deleted"])
        self.assertTrue(result["email_delivery"]["sent"])
        tables["screening_history"].delete.assert_called_once()
        tables["public_applications"].update.assert_called_with({"status": "Rejected"})
        tables["interviews"].delete.assert_called_once()

    @patch("web_app._send_company_email", return_value=(True, "sent"))
    def test_applied_candidate_rejection_erases_company_data(self, _send):
        application = {"id": 11, "job_id": 3, "company_id": "company", "applicant_name": "Asha",
                       "applicant_email": "asha@example.com", "status": "Screening"}
        tables = {}
        for name in ("public_applications", "screening_history", "interviews", "jobs"):
            table = MagicMock()
            table.select.return_value = table
            table.delete.return_value = table
            table.eq.return_value = table
            table.limit.return_value = table
            table.execute.return_value = SimpleNamespace(
                data=[application] if name == "public_applications" else ([{"title": "Engineer"}] if name == "jobs" else []))
            tables[name] = table
        client = MagicMock()
        client.table.side_effect = lambda name: tables[name]
        session = SimpleNamespace(client=client, company={"id": "company", "name": "Acme"})
        result = update_application(11, {"status": "Rejected"}, session)
        self.assertTrue(result["deleted"])
        self.assertTrue(result["email_delivery"]["sent"])
        tables["public_applications"].update.assert_called_with({"status": "Rejected"})
        tables["screening_history"].delete.assert_called_once()
        tables["interviews"].delete.assert_called_once()

    @patch("web_app.check_api_key", return_value=True)
    @patch("web_app.heuristic_resume_check", return_value={"looks_like_resume": True})
    @patch("web_app.extract_text_from_bytes", return_value="resume")
    @patch("web_app.parse_and_score")
    def test_rescreen_updates_existing_record_with_new_priorities(self, parse, *_mocks):
        old = {"id": 7, "raw_text": "resume", "job_id": 3, "job_details": "Python",
               "overall_score": 70, "decision_status": "Selected", "score_json": json.dumps({
                   "overall_score": 70, "ai_overall_score": 75,
                   "breakdown": {"skills_match": 100, "experience_fit": 50, "education_fit": 50}})}
        table = MagicMock()
        for method in ("select", "eq", "order", "range", "update"):
            getattr(table, method).return_value = table
        table.execute.side_effect = lambda: SimpleNamespace(data=[{**old, **(table.update.call_args.args[0] if table.update.called else {})}])
        client = MagicMock()
        client.table.return_value = table
        results, skipped = _screen_payloads([("a.pdf", b"resume"), ("copy.pdf", b"resume")],
            "Engineer", "Python", "3", {"skills_match": 80, "experience_fit": 10, "education_fit": 10},
            SimpleNamespace(client=client, company={"id": "company"}), "Web Upload")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["score"], 90)
        self.assertEqual(results[0]["decision_status"], "Selected")
        updated = table.update.call_args.args[0]
        self.assertEqual(json.loads(updated["score_json"])["ai_overall_score"], 75)
        self.assertEqual(json.loads(updated["score_json"])["priority_weights"]["skills"], 80)
        self.assertNotIn("decision_status", updated)
        table.eq.assert_any_call("company_id", "company")
        table.eq.assert_any_call("id", 7)
        table.insert.assert_not_called()
        parse.assert_not_called()
        self.assertEqual(len(skipped), 1)

    @patch("web_app.check_api_key", return_value=True)
    @patch("web_app.heuristic_resume_check", return_value={"looks_like_resume": True})
    @patch("web_app.extract_text_from_bytes", side_effect=lambda _name, data: data.decode())
    @patch("web_app.parse_and_score")
    def test_screening_returns_partial_ai_failures(self, parse, *_mocks):
        score = {"overall_score": 80, "breakdown": {"skills_match": 80, "experience_fit": 80,
                                                     "education_fit": 80}, "matched_skills": [], "gaps": []}
        parse.side_effect = lambda text, _description: (_ for _ in ()).throw(RuntimeError("provider timeout")) if text == "bad" else ({"name": "Good"}, score.copy())
        client = MagicMock()
        client.table.return_value.insert.side_effect = lambda row: SimpleNamespace(
            execute=lambda: SimpleNamespace(data=[{**row, "id": 1}]))
        results, skipped = _screen_payloads([("good.pdf", b"good"), ("bad.pdf", b"bad")], "Engineer", "Python", "",
                                            {"skills_match": 40, "experience_fit": 40, "education_fit": 20},
                                            SimpleNamespace(client=client, company={"id": "company"}), "Web Upload")
        self.assertEqual(len(results), 1)
        self.assertEqual(skipped[0]["filename"], "bad.pdf")
        self.assertIn("provider timeout", skipped[0]["reason"])
        inserted = client.table.return_value.insert.call_args.args[0]
        self.assertNotIn("source", inserted)

    @patch("web_app.check_api_key", return_value=True)
    @patch("web_app.heuristic_resume_check", return_value={"looks_like_resume": True})
    @patch("web_app.extract_text_from_bytes", return_value="resume")
    @patch("web_app.parse_and_score", side_effect=RuntimeError("all providers failed"))
    def test_screening_returns_503_when_all_ai_calls_fail(self, *_mocks):
        with self.assertRaises(HTTPException) as caught:
            _screen_payloads([("candidate.pdf", b"resume")], "Engineer", "Python", "",
                             {"skills_match": 40, "experience_fit": 40, "education_fit": 20},
                             SimpleNamespace(client=MagicMock(), company={"id": "company"}), "Web Upload")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("temporarily unavailable", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
