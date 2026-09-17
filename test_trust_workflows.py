"""Privacy request boundaries and durable interview delivery regressions."""
from types import SimpleNamespace
from unittest.mock import patch
from test_backend_workflows import BackendWorkflowTests
import web_app


class TrustWorkflowTests(BackendWorkflowTests):
    # Reuse the isolated fixture, not the inherited workflow test suite.
    def test_privacy_request_identity_is_server_owned(self):
        result = self.client.post('/api/privacy-requests', json={'kind':'deletion','details':'My old application','user_id':'other','email':'other@example.test'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['user_id'],'user')
        self.assertEqual(result.json()['email'],'asha@example.com')

    def test_request_list_is_scoped(self):
        self.database.rows['privacy_requests']=[{'id':1,'user_id':'user'}, {'id':2,'user_id':'other'}]
        self.assertEqual([r['id'] for r in self.client.get('/api/privacy-requests').json()['requests']],[1])

    def test_candidate_cannot_review(self):
        result=self.client.patch('/api/owner/privacy-requests/1',json={'status':'completed','response':'Done'})
        self.assertEqual(result.status_code,403)

    def test_closure_requires_explanation(self):
        with self.assertRaises(web_app.HTTPException) as error:
            web_app.review_privacy_request('1',web_app.PrivacyRequestReview(status='completed'),self.candidate_session)
        self.assertEqual(error.exception.status_code,400)

    def test_failed_invitation_is_recorded_and_retry_is_claimed_once(self):
        self.database.rows['interviews']=[{'id':3,'company_id':'company','status':'Scheduled'}]
        self.database.rows['interview_delivery_jobs']=[{'id':1,'company_id':'company','interview_id':3,'status':'queued','recipient':'asha@example.test','subject':'Interview','body':'Details'}]
        with patch.object(web_app,'_send_company_email',return_value=(False,'Unavailable')):
            web_app._deliver_interview_invitation(self.session.company,'a','s','b','badge',self.session,1)
        self.assertEqual(self.database.rows['interview_delivery_jobs'][0]['status'],'failed')
        tasks=web_app.BackgroundTasks()
        web_app.retry_interview_delivery(1,tasks,self.session)
        task=tasks.tasks[0]
        with patch.object(web_app,'_send_company_email',return_value=(True,'Accepted')) as send:
            task.func(*task.args,**task.kwargs)
            task.func(*task.args,**task.kwargs)
            self.assertEqual(send.call_count,1)
        self.assertEqual(self.database.rows['interview_delivery_jobs'][0]['status'],'sent')

    def test_uncertain_delivery_is_not_automatically_retried(self):
        self.database.rows['interview_delivery_jobs']=[{'id':1,'company_id':'company','status':'sending'}]
        with self.assertRaises(web_app.HTTPException) as error:
            web_app.retry_interview_delivery(1,web_app.BackgroundTasks(),self.session)
        self.assertEqual(error.exception.status_code,409)

    def test_delivery_cross_company_denied(self):
        self.database.rows['interview_delivery_jobs']=[{'id':1,'company_id':'other','status':'queued'}]
        with self.assertRaises(web_app.HTTPException) as error:
            web_app.retry_interview_delivery(1,web_app.BackgroundTasks(),self.session)
        self.assertEqual(error.exception.status_code,404)


# Only run tests defined here; shared fixtures retain their own separate suite.
def load_tests(loader, tests, pattern):
    import unittest
    return unittest.TestSuite(TrustWorkflowTests(name) for name in TrustWorkflowTests.__dict__ if name.startswith('test_'))

