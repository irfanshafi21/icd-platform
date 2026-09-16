import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import web_app


class TrackingTests(unittest.TestCase):
    def test_owner_directory_hides_deactivated_company_and_request(self):
        client = MagicMock()
        tables = {name: MagicMock() for name in ('company_registrations', 'owner_company_profiles')}
        client.table.side_effect = tables.__getitem__
        tables['company_registrations'].select.return_value.order.return_value.execute.return_value.data = [
            {'id': 'hidden-request', 'company_id': 'inactive'},
            {'id': 'pending-request', 'company_id': None},
            {'id': 'active-request', 'company_id': 'active'}]
        tables['owner_company_profiles'].select.return_value.order.return_value.execute.return_value.data = [
            {'id': 'inactive', 'verification_status': 'suspended'},
            {'id': 'active', 'verification_status': 'approved'}]
        result = web_app.owner_registrations(SimpleNamespace(client=client))
        self.assertEqual([c['id'] for c in result['companies']], ['active'])
        self.assertEqual([r['id'] for r in result['registrations']], ['pending-request', 'active-request'])

    def test_repeat_approval_does_not_provision_again(self):
        owner = MagicMock()
        owner.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{'status':'approved','access_code':'0123'}]
        with patch.object(web_app, '_public_client') as provision:
            result = web_app.decide_registration('request', web_app.OwnerDecision(decision='approved'), SimpleNamespace(client=owner))
        self.assertEqual(result['access_code'], '0123')
        provision.assert_not_called()

    def test_interrupted_approval_reuses_existing_workspace(self):
        owner = MagicMock()
        owner.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{'status':'pending','company_name':'Example','website':'https://example.test/','access_code':'0123'}]
        owner.table.return_value.select.return_value.execute.return_value.data = [{'id':'existing','name':'example','website':'https://example.test','access_code':'0123','approved_by':web_app.OWNER_EMAIL}]
        with patch.object(web_app, '_public_client') as provision:
            web_app.decide_registration('request', web_app.OwnerDecision(decision='approved'), SimpleNamespace(client=owner))
        provision.assert_not_called()
        self.assertEqual(owner.table.return_value.update.call_args.args[0]['company_id'], 'existing')

    def test_existing_organization_does_not_issue_different_access(self):
        owner = MagicMock()
        owner.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{'status':'pending','company_name':'Example','access_code':'0123'}]
        owner.table.return_value.select.return_value.execute.return_value.data = [{'id':'existing','name':'Example','access_code':'9999','approved_by':web_app.OWNER_EMAIL}]
        with patch.object(web_app, '_public_client') as provision, self.assertRaises(web_app.HTTPException) as caught:
            web_app.decide_registration('request',web_app.OwnerDecision(decision='approved'),SimpleNamespace(client=owner))
        self.assertEqual(caught.exception.status_code,409)
        provision.assert_not_called()

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
