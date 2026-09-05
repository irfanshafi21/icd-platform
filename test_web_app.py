import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from web_app import OWNER_EMAIL, _candidate, _hiring_average, _is_owner_email, _numeric_score, _screen_payloads, app


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

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

    def test_owner_email_matching_is_case_insensitive(self):
        self.assertTrue(_is_owner_email(f"  {OWNER_EMAIL.upper()}  "))
        self.assertFalse(_is_owner_email("candidate@example.com"))

    @patch("web_app.check_api_key", return_value=True)
    @patch("web_app.heuristic_resume_check", return_value={"looks_like_resume": True})
    @patch("web_app.extract_text_from_bytes", side_effect=lambda _name, data: data.decode())
    @patch("web_app.parse_and_score")
    def test_screening_returns_partial_ai_failures(self, parse, *_mocks):
        score = {"overall_score": 80, "breakdown": {"skills_match": 80, "experience_fit": 80,
                                                     "education_fit": 80}, "matched_skills": [], "gaps": []}
        parse.side_effect = lambda text, _description: (_ for _ in ()).throw(RuntimeError("provider timeout")) if text == "bad" else ({"name": "Good"}, score.copy())
        response = MagicMock(data=[])
        client = MagicMock()
        client.table.return_value.insert.return_value.execute.return_value = response
        results, skipped = _screen_payloads([("good.pdf", b"good"), ("bad.pdf", b"bad")], "Engineer", "Python", "",
                                            {"skills_match": 40, "experience_fit": 40, "education_fit": 20},
                                            SimpleNamespace(client=client, company={"id": "company"}), "Web Upload")
        self.assertEqual(len(results), 1)
        self.assertEqual(skipped[0]["filename"], "bad.pdf")
        self.assertIn("provider timeout", skipped[0]["reason"])

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
