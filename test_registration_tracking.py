import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import web_app


class TrackingTests(unittest.TestCase):
    def test_pending_cannot_change_code(self):
        with self.assertRaises(web_app.HTTPException) as caught:
            web_app.change_access_code({'access_code':'1234'},SimpleNamespace(company={'verification_status':'pending'}))
        self.assertEqual(caught.exception.status_code,403)

    def test_approved_changes_code_without_owner(self):
        client=MagicMock()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value.data=[{'id':'company','access_code':'0042','verification_status':'approved'}]
        result=web_app.change_access_code({'access_code':'0042'},SimpleNamespace(client=client,company={'id':'company','verification_status':'approved'}))
        self.assertTrue(result['ok'])

    def test_submission_issues_code_and_pending_only(self):
        client = MagicMock()
        with patch.object(web_app, '_public_client', return_value=client):
            result = web_app.register_company(web_app.CompanyRegistration(company_name='Example', contact_name='Person', business_email='person@example.test'))
        row = client.table.return_value.insert.call_args.args[0]
        self.assertRegex(result['access_code'], r'^[0-9]{4}$')
        self.assertEqual(row['access_code'], result['access_code'])
        self.assertEqual(row['status'], 'pending')
        self.assertNotIn('company_id', row)

    def test_approval_preserves_code(self):
        code = '0123'
        owner = MagicMock()
        owner.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{'status':'pending','company_name':'Example','access_code':code}]
        company = MagicMock()
        company.auth.sign_up.return_value = SimpleNamespace(user=SimpleNamespace(id='user'), session=True)
        company.table.return_value.insert.return_value.execute.return_value.data = [{'id':'company'}]
        with patch.object(web_app, '_public_client', return_value=company):
            result = web_app.decide_registration('request',web_app.OwnerDecision(decision='approved'),SimpleNamespace(client=owner))
        self.assertEqual(result['access_code'], code)
        self.assertEqual(company.table.return_value.insert.call_args.args[0]['access_code'], code)

    def test_tracking_wrong_code_fails(self):
        client = MagicMock()
        client.rpc.return_value.execute.return_value.data = []
        with patch.object(web_app, '_public_client', return_value=client), self.assertRaises(web_app.HTTPException) as caught:
            web_app.track_registration(web_app.RegistrationTracking(business_email='person@example.test',access_code='9999'))
        self.assertEqual(caught.exception.status_code,404)
