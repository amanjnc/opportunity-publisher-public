import unittest
from dedup import match, canonical_url, find_match
DESCRIPTION='Support marketing campaigns, build customer relationships, analyze sales performance and prepare regular reports for the sales team. Receive practical experience and structured supervision.'
class DedupTests(unittest.TestCase):
    def item(self,**kw):
        d=dict(title='Sales and Marketing Intern',organization='Example Company',apply_url='https://example.org/apply?job_id=123',location='Addis Ababa',deadline='2027-01-04',description=DESCRIPTION);d.update(kw);return d
    def level(self,a,b):return match(a,b)[0]
    def test_shared_link_similar_details(self):self.assertEqual(self.level(self.item(),self.item(title='Paid Sales & Marketing Internship Opportunity')),'exact')
    def test_company_description_deadline_different_link(self):self.assertEqual(self.level(self.item(),self.item(title='Paid Sales & Marketing Internship Opportunity',apply_url='https://forms.gle/other')),'exact')
    def test_different_roles_same_portal(self):self.assertEqual(self.level(self.item(),self.item(title='Finance Manager')),'')
    def test_seniority(self):self.assertEqual(self.level(self.item(title='Senior Marketing Analyst'),self.item(title='Junior Marketing Analyst')),'')
    def test_employer_conflict(self):self.assertEqual(self.level(self.item(),self.item(organization='Other Employer')),'')
    def test_location_conflict(self):self.assertEqual(self.level(self.item(),self.item(location='Nairobi')),'')
    def test_annual_cycle(self):self.assertEqual(self.level(self.item(title='Example Fellowship 2026'),self.item(title='Example Fellowship 2027')),'')
    def test_numbered_cohort(self):self.assertEqual(self.level(self.item(title='Example Fellowship Cohort 1'),self.item(title='Example Fellowship Cohort 2')),'')
    def test_season(self):self.assertEqual(self.level(self.item(title='Example Winter Fellowship'),self.item(title='Example Summer Fellowship')),'')
    def test_study_level(self):self.assertEqual(self.level(self.item(title='Example Undergraduate Scholarship'),self.item(title='Example Masters Scholarship')),'')
    def test_deadline_change(self):self.assertEqual(self.level(self.item(),self.item(deadline='2027-02-01')),'possible')
    def test_vacancy_conflict(self):self.assertEqual(self.level(self.item(vacancy_id='ABC123'),self.item(vacancy_id='ABC456')),'')
    def test_url_ids(self):self.assertNotEqual(canonical_url('https://example.org/apply?id=1'),canonical_url('https://example.org/apply?id=2'))
    def test_tracking(self):self.assertEqual(canonical_url('https://www.example.org/apply/?id=1&utm_source=x#top'),canonical_url('https://example.org/apply?id=1'))
    def test_missing_not_confirmation(self):self.assertNotEqual(self.level(self.item(title='',description='',organization=''),self.item(title='',description='',organization='')),'exact')
    def test_case_emoji(self):self.assertEqual(self.level(self.item(),self.item(title='🚀 SALES & MARKETING INTERN!',organization='EXAMPLE COMPANY')),'exact')
    def test_prefers_exact(self):
        a=self.item(id=3);b=self.item(id=1,deadline='2027-03-01');c=self.item(id=2)
        self.assertEqual(find_match(a,[b,c])[0]['id'],2)
