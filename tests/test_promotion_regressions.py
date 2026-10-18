import unittest
from unittest.mock import patch
from source_cleanup import clean_source
from opportunity_quality import publication_block_reason
from routing import opportunity_category
from post_content import clean_details
import test_cloud, storage
from repair_source_posts import repair_requested_posts

ESM='''ዛሬ ያመልክቱ!
EUROPEAN STABILITY MECHANISM TRAINEESHIPS
Applications are open for paid traineeships in Luxembourg.
Apply: https://example.org/traineeships
Connect with us for updates and more:
Instagram | Telegram | LinkedIn | Facebook | TikTok | OHUB Opportunities
OHUB Educational Consultancy
Phone: +251911123456
Email: contact@ohubet.com
https://t.me/OHUB4AllET
Benefits:
Monthly stipend EUR 2000
Deadline: 2027-01-31'''

class PromotionRegressionTests(unittest.TestCase):
    def test_commercial_exam_ad_never_eligible_even_if_saved_as_job(self):
        self.assertTrue(publication_block_reason({'title':'IELTS Preparation Class + IELTS Exam Booking!', 'category':'Job','organization':'OHUB','raw_text':'IELTS Preparation Class + IELTS Exam Booking!\nRegister now https://example.org/book','apply_url':'https://example.org/book'}))
    def test_amharic_intro_does_not_hide_genuine_fellowship(self):
        raw='ዛሬ የመጨረሻ ቀን ነው ፍጠኑ!\nAIxBio RESEARCH FELLOWSHIP 2027\nApplications are open. Stipend £10,000.\nApply: https://example.org/apply\n'+ESM.split('Connect with us')[1]
        opp={'title':raw.splitlines()[0],'raw_text':raw,'apply_url':'https://example.org/apply'}
        self.assertFalse(publication_block_reason(opp))
        self.assertEqual(opportunity_category(opp),'Fellowship')
    def test_mid_post_promotion_removed_but_following_facts_survive(self):
        text=clean_source(ESM,'OHUB4AllET')
        for token in ['Instagram','OHUB','contact@','+251','t.me']:self.assertNotIn(token,text)
        for token in ['2000','Deadline','traineeships','https://example.org/traineeships']:self.assertIn(token,text)
        self.assertEqual(clean_source(text,'OHUB4AllET'),text)
    def test_source_contacts_removed_employer_contacts_retained(self):
        raw='Research assistant vacancy\nEmail: hiring@university.edu\nChannel contact @sourcechannel\nEmail: sourcechannel@gmail.com\nApply: https://university.edu/apply'
        result=clean_source(raw,'sourcechannel')
        self.assertNotIn('sourcechannel',result)
        self.assertIn('hiring@university.edu',result)
        self.assertIn('https://university.edu/apply',result)
    def test_social_anchors_inline_removed(self):
        result=clean_source('Learn more <a href="https://instagram.com/source">Instagram</a>\nApply: https://example.org/apply')
        self.assertNotIn('instagram',result.lower())
        self.assertIn('https://example.org/apply',result)
    def test_single_opportunity_has_only_selected_apply_link(self):
        details=clean_details({'title':'Research fellowship','description':'Apply https://example.org/apply\nMore https://example.org/extra\nBenefits: mentoring','apply_url':'https://example.org/apply'})
        self.assertNotIn('https://','\n'.join(details))
    def test_multiple_legitimate_links_are_not_ineligible(self):
        self.assertFalse(publication_block_reason({'title':'African Union vacancies','raw_text':'African Union is hiring\nFinance officer apply https://example.org/1\nDriver apply https://example.org/2','apply_url':'https://example.org/1'}))

class ExistingPostRepairTests(unittest.TestCase):
    setUp=test_cloud.CloudTests.setUp
    tearDown=test_cloud.CloudTests.tearDown
    def test_exact_promo_deleted_once_all_message_parts(self):
        storage.add_opportunity({'source_key':'ad','title':'IELTS Preparation Class + IELTS Exam Booking!','apply_url':'https://example.org/book'})
        with storage.db() as c:
            c.execute('UPDATE opportunities SET id=295')
            c.execute("INSERT INTO publications(opportunity_id,platform,slot_key,status,remote_id,destination,created_at,updated_at) VALUES(295,'telegram','old','posted','12','@general_channel','2026-10-18','2026-10-18')")
            for remote,kind in [('11','photo'),('12','details')]:c.execute("INSERT INTO publication_parts(opportunity_id,platform,remote_id,kind,created_at) VALUES(295,'telegram',?,?,'2026-10-18')",(remote,kind))
        with patch('repair_source_posts.telegram_action') as action:
            repair_requested_posts();repair_requested_posts()
        self.assertEqual(action.call_count,2)
        self.assertTrue(all(call.args[0]=='deleteMessage' for call in action.call_args_list))
        self.assertEqual(storage.get_opportunities()[0]['status'],'rejected')
    def test_existing_traineeship_is_edited_without_reposting(self):
        storage.add_opportunity({'source_key':'esm','title':'EUROPEAN STABILITY MECHANISM (ESM) TRAINEESHIPS','raw_text':ESM,'apply_url':'https://example.org/traineeships','source_name':'OHUB4AllET'})
        with storage.db() as c:
            c.execute('UPDATE opportunities SET id=318')
            c.execute("INSERT INTO publications(opportunity_id,platform,slot_key,status,remote_id,destination,created_at,updated_at) VALUES(318,'telegram','old','posted','13','@general_channel','2026-10-18','2026-10-18')")
            c.execute("INSERT INTO publication_parts(opportunity_id,platform,remote_id,kind,created_at) VALUES(318,'telegram','13','text','2026-10-18')")
        with patch('repair_source_posts.telegram_action') as action:
            repair_requested_posts();repair_requested_posts()
        self.assertEqual(action.call_count,1)
        method,payload=action.call_args.args
        self.assertEqual(method,'editMessageText')
        for value in ['OHUB','+251','contact@','Instagram']:self.assertNotIn(value,payload['text'])
        self.assertIn('2000',payload['text'])
        self.assertIn('https://example.org/traineeships',payload['text'])
