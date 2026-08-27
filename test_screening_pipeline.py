import os
import unittest
from unittest.mock import patch

from screening_pipeline import (
    cache_key, cached_ai_result, content_hash, extraction_worker_count,
    job_description_hash, worker_count,
)


class ScreeningPipelineTests(unittest.TestCase):
    def test_hashes_are_stable_and_pair_specific(self):
        self.assertEqual(content_hash(b"resume"), content_hash("resume"))
        self.assertEqual(job_description_hash("Role  \nSkills\n"), job_description_hash("Role\nSkills"))
        self.assertNotEqual(cache_key("resume-a", "jd"), cache_key("resume-b", "jd"))

    def test_worker_count_is_bounded(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(worker_count(20), 10)
        with patch.dict(os.environ, {"SCREENING_MAX_WORKERS": "99"}):
            self.assertEqual(worker_count(20), 10)
        with patch.dict(os.environ, {"SCREENING_MAX_WORKERS": "2"}):
            self.assertEqual(worker_count(1), 1)

    def test_extraction_worker_count_is_bounded(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(extraction_worker_count(0), 1)
            self.assertEqual(extraction_worker_count(3), 3)
            self.assertEqual(extraction_worker_count(100), 4)

    def test_cached_result_restores_unweighted_ai_score(self):
        candidate = {"profile": {"name": "A"}, "score": {
            "overall_score": 70, "ai_overall_score": 82, "breakdown": {}}}
        profile, score = cached_ai_result(candidate)
        self.assertEqual(profile["name"], "A")
        self.assertEqual(score["overall_score"], 82)


if __name__ == "__main__":
    unittest.main()
