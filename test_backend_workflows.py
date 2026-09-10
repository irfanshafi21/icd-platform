"""HTTP workflow regressions with isolated storage and mocked delivery/AI."""
import copy
import io
import json
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import web_app


class MemoryQuery:
    def __init__(self, database, table):
        self.database, self.table_name = database, table
        self.filters, self.operation, self.values = [], "select", None
        self.maximum = None

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters.append(lambda row: row.get(key) == value)
        return self

    def neq(self, key, value):
        self.filters.append(lambda row: row.get(key) != value)
        return self

    def is_(self, key, value):
        self.filters.append(lambda row: row.get(key) is None if value == "null" else row.get(key) is value)
        return self

    def in_(self, key, values):
        self.filters.append(lambda row: row.get(key) in values)
        return self

    def ilike(self, key, value):
        self.filters.append(lambda row: value.strip("%").casefold() in str(row.get(key, "")).casefold())
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, value):
        self.maximum = value
        return self

    def update(self, values):
        self.operation, self.values = "update", values
        return self

    def insert(self, values):
        self.operation, self.values = "insert", values
        return self

    def execute(self):
        failure = (self.table_name, self.operation)
        if self.database.fail_once == failure:
            self.database.fail_once = None
            raise RuntimeError("Simulated temporary storage failure")
        if self.database.empty_once == failure:
            self.database.empty_once = None
            return SimpleNamespace(data=[])
        table = self.database.rows.setdefault(self.table_name, [])
        if self.table_name == "interviews" and self.operation == "update" and self.database.concurrent_score is not None:
            table[0].update(interview_score=self.database.concurrent_score, status="Completed")
            self.database.concurrent_score = None
        if self.operation == "insert":
            inserted = self.values if isinstance(self.values, list) else [self.values]
            rows = []
            for value in inserted:
                row = copy.deepcopy(value)
                row.setdefault("id", max([r.get("id", 0) for r in table] + [0]) + 1)
                table.append(row)
                rows.append(row)
        else:
            rows = [row for row in table if all(test(row) for test in self.filters)]
            if self.maximum is not None:
                rows = rows[:self.maximum]
            if self.operation == "update":
                for row in rows:
                    row.update(copy.deepcopy(self.values))
        return SimpleNamespace(data=copy.deepcopy(rows))


class MemoryDatabase:
    def __init__(self):
        self.rows = {"companies_public": [{"id": "company", "name": "Acme"}]}
        self.fail_once = None
        self.empty_once = None
        self.concurrent_score = None

    def table(self, name):
        return MemoryQuery(self, name)


class BackendWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.database = MemoryDatabase()
        self.session = SimpleNamespace(client=self.database, company={"id": "company", "name": "Acme"})
        self.candidate_session = SimpleNamespace(client=self.database, user=SimpleNamespace(id="user", email="asha@example.com"))
        web_app.app.dependency_overrides[web_app._session] = lambda: self.session
        web_app.app.dependency_overrides[web_app._candidate_session] = lambda: self.candidate_session
        self.addCleanup(web_app.app.dependency_overrides.clear)
        for name, value in (
            ("_public_client", self.database), ("check_api_key", True),
            ("email_is_configured", True), ("inbox_is_configured", False),
            ("extract_text_from_bytes", "Asha has five years of Python experience."),
            ("heuristic_resume_check", {"looks_like_resume": True}),
            ("_send_company_email", (True, "Mock delivery accepted")),
            ("_offer_pdf_for", b"%PDF-1.4\nmock offer"),
        ):
            context = patch.object(web_app, name, return_value=value)
            context.start()
            self.addCleanup(context.stop)
        self.ai = patch.object(web_app, "parse_and_score", side_effect=self.analysis).start()
        self.addCleanup(patch.stopall)
        self.client = TestClient(web_app.app)

    @staticmethod
    def analysis(*_args):
        return ({"name": "Asha", "email": "asha@example.com", "skills": ["Python"]},
                {"overall_score": 80, "breakdown": {"skills_match": 80, "experience_fit": 80, "education_fit": 80},
                 "matched_skills": ["Python"], "gaps": []})

    def seed_candidate(self, score=80, interview_score=None):
        profile, analysis = self.analysis()
        profile["_screening_source"] = "Web Upload"
        row = {"id": 7, "company_id": "company", "job_id": 3, "job_role": "Engineer",
               "candidate_name": "Asha", "email": "asha@example.com", "filename": "asha.pdf",
               "raw_text": "Resume evidence", "profile_json": json.dumps(profile), "score_json": json.dumps(analysis),
               "overall_score": score, "interview_score": interview_score, "status": "active",
               "decision_status": "Interview Eligible"}
        self.database.rows["screening_history"] = [row]
        self.database.rows["interviews"] = [{"id": 11, "company_id": "company", "candidate_name": "Asha",
                                            "job_role": "Engineer", "status": "Scheduled", "interview_score": interview_score}]
        self.database.rows["public_applications"] = [{"id": 4, "company_id": "company", "job_id": 3,
                                                     "applicant_email": "asha@example.com", "status": "Screening"}]
        return row

    def test_publish_apply_screen_schedule_score_and_offer_workflow(self):
        created = self.client.post("/api/jobs", json={"title": "Engineer", "required_skills": ["Python"]})
        self.assertEqual(created.status_code, 200, created.text)
        job_id = created.json()["id"]
        self.assertEqual(self.client.get("/api/public/jobs").json(), [])
        published = self.client.patch(f"/api/jobs/{job_id}", json={"published_to_portal": True})
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(len(self.client.get("/api/public/jobs").json()), 1)
        data = {"job_id": job_id, "full_name": "Asha"}
        files = {"resume": ("asha.pdf", b"resume", "application/pdf")}
        applied = self.client.post("/api/candidate/applications", data=data, files=files)
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(self.client.post("/api/candidate/applications", data=data, files=files).status_code, 409)
        screened = self.client.post(f"/api/jobs/{job_id}/screen-applications")
        self.assertEqual(screened.status_code, 200, screened.text)
        candidate = screened.json()["candidates"][0]
        self.assertEqual(candidate["filename"], "asha.pdf")
        self.assertEqual(self.client.post(f"/api/jobs/{job_id}/screen-applications").json()["processed"], 0)
        self.assertEqual(len(self.database.rows["screening_history"]), 1)
        scheduled = self.client.post("/api/interviews", json={"candidate_id": candidate["id"],
            "candidate_name": "Asha", "job_role": "Engineer", "scheduled_at": "2026-10-01T09:30",
            "mode": "Physical", "location": "Office"})
        self.assertEqual(scheduled.status_code, 200, scheduled.text)
        self.assertTrue(scheduled.json()["email_delivery"]["sent"])
        saved = self.client.patch(f"/api/interviews/{scheduled.json()['id']}", json={"interview_score": 80})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["decision_status"], "Selected")
        self.assertEqual(self.database.rows["public_applications"][0]["status"], "Selected")
        offer = self.client.post("/api/offers/preview.pdf", json={"candidate_ids": [candidate["id"]]})
        self.assertEqual(offer.status_code, 200, offer.text)
        self.assertTrue(offer.content.startswith(b"%PDF"))
        self.assertEqual(self.client.patch(f"/api/jobs/{job_id}", json={"status": "archived"}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/public/jobs/{job_id}").status_code, 404)

    def test_score_retry_repairs_partial_candidate_sync(self):
        self.seed_candidate()
        self.database.fail_once = ("screening_history", "update")
        failed = self.client.patch("/api/interviews/11", json={"interview_score": 80})
        self.assertEqual(failed.status_code, 503, failed.text)
        self.assertIn("Retry the same score", failed.json()["detail"])
        self.assertEqual(self.database.rows["interviews"][0]["interview_score"], 80)
        retried = self.client.patch("/api/interviews/11", json={"interview_score": 80})
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["hiring_average"], 80)
        self.assertEqual(self.database.rows["screening_history"][0]["interview_score"], 80)
        self.assertEqual(self.database.rows["public_applications"][0]["status"], "Selected")
        self.assertEqual(self.client.patch("/api/interviews/11", json={"interview_score": 79}).status_code, 409)

    def test_score_retry_repairs_candidate_portal_sync(self):
        self.seed_candidate()
        self.database.fail_once = ("public_applications", "update")
        with self.assertLogs(web_app.logger, level="WARNING"):
            failed = self.client.patch("/api/interviews/11", json={"interview_score": 80})
        self.assertEqual(failed.status_code, 503, failed.text)
        self.assertEqual(self.database.rows["screening_history"][0]["interview_score"], 80)
        self.assertEqual(self.database.rows["public_applications"][0]["status"], "Screening")
        retried = self.client.patch("/api/interviews/11", json={"interview_score": 80})
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(self.database.rows["public_applications"][0]["status"], "Selected")

    def test_score_zero_is_saved_and_locked(self):
        self.seed_candidate()
        saved = self.client.patch("/api/interviews/11", json={"interview_score": 0})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["hiring_average"], 40)
        self.assertEqual(self.database.rows["screening_history"][0]["interview_score"], 0)
        self.assertEqual(self.client.patch("/api/interviews/11", json={"interview_score": 1}).status_code, 409)

    def test_invalid_scores_do_not_change_records(self):
        self.seed_candidate()
        for score in [59.5, -1, 101, "NaN", "Infinity", "invalid", None]:
            with self.subTest(score=score):
                self.assertEqual(self.client.patch("/api/interviews/11", json={"interview_score": score}).status_code, 400)
        self.assertIsNone(self.database.rows["interviews"][0]["interview_score"])

    def test_concurrent_final_score_cannot_be_overwritten(self):
        self.seed_candidate()
        self.database.concurrent_score = 90
        response = self.client.patch("/api/interviews/11", json={"interview_score": 80})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.database.rows["interviews"][0]["interview_score"], 90)
        self.assertIsNone(self.database.rows["screening_history"][0]["interview_score"])

    def test_offer_requires_average_strictly_above_seventy(self):
        self.seed_candidate(score=80)
        saved = self.client.patch("/api/interviews/11", json={"interview_score": 60})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["decision_status"], "Interview Completed")
        self.assertEqual(self.client.post("/api/offers/preview.pdf", json={"candidate_ids": [7]}).status_code, 400)

    def test_ats_rerun_preserves_visibility_and_screening_priorities(self):
        candidate = self.seed_candidate()
        candidate["score_json"] = json.dumps({"priority_weights": {"skills": 70, "experience": 20, "education": 10}})
        self.ai.side_effect = lambda *_: ({"name": "Asha"}, {"overall_score": 50,
            "breakdown": {"skills_match": 90, "experience_fit": 40, "education_fit": 20}})
        response = self.client.post("/api/candidates/7/ats-rerun")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["score"], 73)
        bootstrap = self.client.get("/api/bootstrap")
        self.assertEqual(bootstrap.status_code, 200, bootstrap.text)
        self.assertEqual(len(bootstrap.json()["candidates"]), 1)
        self.assertEqual(bootstrap.json()["candidates"][0]["score"], 73)

    def test_ats_rerun_recalculates_offer_eligibility_after_final_score(self):
        candidate = self.seed_candidate(score=80, interview_score=70)
        candidate["decision_status"] = "Selected"
        self.ai.side_effect = lambda *_: ({"name": "Asha"}, {"overall_score": 60})
        response = self.client.post("/api/candidates/7/ats-rerun")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["decision_status"], "Interview Completed")
        self.assertEqual(self.database.rows["public_applications"][0]["status"], "Interview Completed")

    def test_ats_rerun_failed_portal_sync_does_not_report_complete_success(self):
        self.seed_candidate()
        self.database.fail_once = ("public_applications", "update")
        with self.assertLogs(web_app.logger, level="WARNING"):
            response = self.client.post("/api/candidates/7/ats-rerun")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertIn("ATS analysis was saved", response.json()["detail"])
        self.assertEqual(self.client.post("/api/candidates/7/ats-rerun").status_code, 200)
        self.assertEqual(self.database.rows["public_applications"][0]["status"], "Interview Eligible")

    def test_batch_screening_continues_after_unreadable_resume(self):
        with patch.object(web_app, "extract_text_from_bytes", side_effect=lambda name, _:
                          (_ for _ in ()).throw(ValueError("bad PDF")) if name == "bad.pdf" else "Resume evidence"):
            response = self.client.post("/api/screen", data={"job_role": "Engineer"}, files=[
                ("files", ("bad.pdf", b"bad", "application/pdf")),
                ("files", ("asha.pdf", b"resume", "application/pdf"))])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)
        self.assertEqual(response.json()["skipped"][0]["filename"], "bad.pdf")

    def test_unsupported_screening_upload_is_a_useful_client_error(self):
        response = self.client.post("/api/screen", data={"job_role": "Engineer"},
                                    files={"files": ("notes.txt", b"text", "text/plain")})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("Upload at least one", response.json()["detail"])

    def test_screening_does_not_display_a_candidate_that_was_not_saved(self):
        self.database.empty_once = ("screening_history", "insert")
        with self.assertLogs(web_app.logger, level="ERROR"):
            response = self.client.post("/api/screen", data={"job_role": "Engineer"},
                                        files={"files": ("asha.pdf", b"resume", "application/pdf")})
        self.assertEqual(response.status_code, 503, response.text)
        self.assertIn("could not be saved", response.json()["detail"])
        self.assertEqual(self.database.rows.get("screening_history", []), [])

    def test_ats_rerun_does_not_claim_success_when_candidate_update_is_not_saved(self):
        self.seed_candidate()
        self.database.empty_once = ("screening_history", "update")
        response = self.client.post("/api/candidates/7/ats-rerun")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.database.rows["public_applications"][0]["status"], "Screening")

    def test_job_update_cannot_move_company_and_missing_job_is_not_success(self):
        self.database.rows["jobs"] = [{"id": 3, "title": "Engineer", "company_id": "company"}]
        self.assertEqual(self.client.patch("/api/jobs/3", json={"company_id": "other"}).status_code, 400)
        self.assertEqual(self.database.rows["jobs"][0]["company_id"], "company")
        self.assertEqual(self.client.patch("/api/jobs/999", json={"published_to_portal": True}).status_code, 404)

    def test_reports_download_real_csv_excel_and_pdf_with_company_and_role_scope(self):
        candidate = self.seed_candidate(interview_score=80)
        candidate["decision_status"] = "Selected"
        self.database.rows["screening_history"].extend([
            {**candidate, "id": 8, "company_id": "other", "candidate_name": "Other Company Candidate"},
            {**candidate, "id": 9, "job_role": "Designer", "candidate_name": "Other Role Candidate"},
        ])
        for report_type in ("screened", "shortlisted", "selected", "interviews"):
            for file_type in ("csv", "xlsx", "pdf"):
                with self.subTest(report=report_type, format=file_type):
                    response = self.client.get(f"/api/reports/{report_type}.{file_type}?role=Engineer")
                    self.assertEqual(response.status_code, 200, response.text[:200] if file_type == "csv" else response.headers)
                    self.assertIn(f".{file_type}", response.headers["content-disposition"])
                    if file_type == "csv":
                        self.assertIn("Asha", response.text)
                        self.assertNotIn("Other Company Candidate", response.text)
                        self.assertNotIn("Other Role Candidate", response.text)
                    elif file_type == "pdf":
                        self.assertTrue(response.content.startswith(b"%PDF"))
                    else:
                        with zipfile.ZipFile(io.BytesIO(response.content)) as workbook:
                            self.assertIn("xl/workbook.xml", workbook.namelist())
        self.assertEqual(self.client.get("/api/reports/unknown.csv").status_code, 400)
        self.assertEqual(self.client.get("/api/reports/screened.exe").status_code, 400)

    def test_candidate_report_and_offer_archive_contain_pdf_documents(self):
        candidate = self.seed_candidate(interview_score=80)
        candidate["decision_status"] = "Selected"
        report = self.client.get("/api/candidates/7/report.pdf")
        self.assertEqual(report.status_code, 200)
        self.assertTrue(report.content.startswith(b"%PDF"))
        response = self.client.post("/api/offers.zip", json={"candidate_ids": [7]})
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(len(archive.namelist()), 1)
            self.assertTrue(archive.read(archive.namelist()[0]).startswith(b"%PDF"))

    def test_offer_delivery_reports_failure_and_enforces_eligibility(self):
        candidate = self.seed_candidate(interview_score=80)
        candidate["decision_status"] = "Selected"
        with patch.object(web_app, "send_email_with_pdf", return_value=(False, "Mock mail service unavailable")) as delivery:
            failed = self.client.post("/api/offers/send", json={"candidate_ids": [7]})
            self.assertEqual(failed.status_code, 200, failed.text)
            self.assertEqual(failed.json()["failed_count"], 1)
            self.assertEqual(failed.json()["sent_count"], 0)
            delivery.return_value = (True, "Mock delivery accepted")
            sent = self.client.post("/api/offers/send", json={"candidate_ids": [7]})
            self.assertEqual(sent.json()["sent_count"], 1)
            self.assertTrue(delivery.call_args.args[3].startswith(b"%PDF"))
            candidate["decision_status"] = "Interview Completed"
            self.assertEqual(self.client.post("/api/offers/send", json={"candidate_ids": [7]}).status_code, 400)
            self.assertEqual(self.client.post("/api/offers/send", json={"candidate_ids": []}).status_code, 400)
            self.assertEqual(delivery.call_count, 2)


if __name__ == "__main__":
    unittest.main()
