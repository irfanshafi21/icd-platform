import json
import unittest

from fastapi.testclient import TestClient

from web_app import _candidate, _hiring_average, _numeric_score, app


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


if __name__ == "__main__":
    unittest.main()
