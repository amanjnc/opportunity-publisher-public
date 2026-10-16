import unittest
from unittest.mock import patch
import test_cloud
import storage, cloud_run
from opportunity_quality import publication_block_reason

PROMO={
    'title':"PLANNING TO PURSUE YOUR MASTER’S OR PhD IN THE USA?",
    'category':'Other','apply_url':'https://example.org/finder',
    'description':"""A professor shared Grad School Finder, a free web app.
FREE ACCESS FOR THE FIRST 100 STUDENTS. Sign up within 48 hours.
Request access with your email. Enjoy 7 DAYS OF FREE ACCESS
with up to 10 searches per week. Find universities for graduate studies.""",
    'organization':'','deadline':''
}

class QualityTests(unittest.TestCase):
    def test_user_example_blocked_despite_length_and_link(self):
        self.assertTrue(publication_block_reason(PROMO))
    def test_tool_name_is_not_an_institution_exception(self):
        self.assertTrue(publication_block_reason(dict(PROMO,organization='Grad School Finder')))
    def test_vague_generic_announcement_blocked(self):
        self.assertTrue(publication_block_reason({'title':'Great opportunities abroad','description':'Explore your future today. Apply now!'}))
    def test_rolling_named_institution_can_pass(self):
        self.assertFalse(publication_block_reason({'title':'Research assistant','organization':'Example University','description':'Maintain laboratory records. Requirements: biology degree. Rolling applications accepted.'}))
    def test_missing_deadline_does_not_block_named_group(self):
        self.assertFalse(publication_block_reason({'title':'African Union vacancies','description':'African Union: Internship Programme, Finance Director, Driver.'}))
    def test_real_software_job_not_confused_with_tool_ad(self):
        item=dict(PROMO,title='Software engineer',organization='Example Labs',description='Responsibilities: develop a web app supporting trial users and sign up flows. Requirements: computer science degree.')
        self.assertFalse(publication_block_reason(item))

class QualityQueueTests(unittest.TestCase):
    setUp=test_cloud.CloudTests.setUp
    tearDown=test_cloud.CloudTests.tearDown
    def test_previously_approved_promo_skipped_and_next_valid_item_claimed(self):
        storage.add_opportunity(dict(PROMO,source_key='promo',status='approved'))
        # Approval predates the new screening rule.
        item=storage.get_opportunities()[0]
        with storage.db() as c:c.execute("UPDATE opportunities SET status='approved' WHERE id=?",(item['id'],))
        storage.add_opportunity({'source_key':'valid','title':'Research assistant at Example University','organization':'Example University','description':'Research responsibilities and degree requirements.','apply_url':'https://example.org/job'})
        good=next(x for x in storage.get_opportunities() if x['source_key']=='valid')
        storage.update_opportunity(good['id'],{},status='approved')
        self.assertEqual(storage.claim_next('telegram','quality',destination='@general_channel')['id'],good['id'])
        self.assertFalse(any(x['opportunity_id']==item['id'] for x in storage.get_publications()))
    def test_auto_approval_holds_promotional_item(self):
        storage.add_opportunity(dict(PROMO,source_key='promo'))
        with patch('cloud_run.config',return_value={'cloud_auto_approve':1}):
            self.assertEqual(cloud_run.auto_approve(),0)
        self.assertEqual(storage.get_opportunities()[0]['status'],'review')

class SocialAnnouncementTests(unittest.TestCase):
    def test_exact_livestream_example_blocked_even_with_bad_category(self):
        item={'title':'Am live in TikTok','category':'Scholarship','organization':'TikTok',
              'deadline':'2027-01-01','apply_url':'https://vt.tiktok.com/ZS9D3Vy8NprRx-f4Nf1'}
        self.assertTrue(publication_block_reason(item))
    def test_live_title_blocked_even_with_non_social_link(self):
        self.assertTrue(publication_block_reason({'title':"I'm live on Instagram",'organization':'Example','apply_url':'https://example.org'}))
    def test_social_only_links_blocked_regardless_of_title(self):
        for host in ('vm.tiktok.com','m.facebook.com','www.instagram.com','youtu.be','youtube.com'):
            self.assertTrue(publication_block_reason({'title':'Opportunity alert','organization':'Example','apply_url':'https://'+host+'/abc'}))
    def test_valid_vacancy_link_not_blocked_for_mentioning_platform(self):
        self.assertFalse(publication_block_reason({'title':'TikTok software engineer','organization':'TikTok','description':'Requirements: computer science. Responsibilities: develop software.','apply_url':'https://careers.example.org/jobs/123'}))
    def test_shortened_social_link_removed_by_footer_cleaner(self):
        from source_cleanup import clean_source
        self.assertEqual(clean_source('Details\nhttps://vt.tiktok.com/abc'),'Details')
