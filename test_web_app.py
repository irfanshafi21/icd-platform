import json
import unittest

from fastapi.testclient import TestClient

from web_app import _candidate, app


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_and_spa_shell(self):
        self.assertEqual(self.client.get("/api/health").json()["service"], "icd-web")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("ICD Platform", response.text)
        self.assertIn("favicon.svg", response.text)
        self.assertEqual(self.client.get("/static/favicon.svg").status_code, 200)
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


if __name__ == "__main__":
    unittest.main()
