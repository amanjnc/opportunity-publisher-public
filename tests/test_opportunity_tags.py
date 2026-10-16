import unittest
from opportunity_tags import classify_tags
from transform import format_post
from message_layout import telegram_layout,visible_units

class OpportunityTagTests(unittest.TestCase):
    def test_software_role_with_description_evidence(self):
        tags=classify_tags({'category':'Job','title':'Developer','description':"Build software systems. Bachelor's degree in computer science. Remote work available."})
        self.assertTrue({'#IT','#Software','#Bachelors','#RemoteJobs','#Jobs'}<=set(tags))
    def test_no_work_mode_inferred_from_city_or_online_application(self):
        tags=classify_tags({'category':'Job','title':'Finance Officer','location':'Addis Ababa','description':'Apply online. Attend an in-person interview. Basic computer skills.'})
        self.assertIn('#Finance',tags)
        self.assertFalse({'#IT','#RemoteJobs','#HybridJobs','#InPersonJobs'}&set(tags))
    def test_hybrid_and_inperson_explicit(self):
        self.assertIn('#HybridJobs',classify_tags({'category':'Job','description':'Hybrid work schedule'}))
        self.assertIn('#InPersonJobs',classify_tags({'category':'Job','location':'On-site'}))
    def test_no_remote_when_negated_or_remote_sensing(self):
        for description in ('Not remote. Remote sensing research.','No remote work.'):
            self.assertNotIn('#RemoteJobs',classify_tags({'category':'Job','description':description}))
    def test_multiple_degrees_fields_and_funding(self):
        tags=classify_tags({'category':'Scholarship','title':'Fully funded Masters and PhD scholarships','description':'Study law, economics or mechanical engineering.'})
        self.assertTrue({'#Masters','#PhD','#FullyFunded','#Law','#Economics','#MechanicalEngineering','#Scholarships'}<=set(tags))
        self.assertNotIn('#Engineering',tags)
    def test_source_hashtags_do_not_establish_evidence(self):
        tags=classify_tags({'category':'Job','title':'Receptionist','raw_text':'#RemoteJobs #FullyFunded #REZONBRIDGE'})
        self.assertEqual(tags,['#Jobs'])
    def test_footer_on_short_post_and_compacted_caption(self):
        opp={'title':'Finance officer','category':'Job','apply_url':'https://example.org/apply','description':'Finance and accounting duties.\n'+('A complete factual detail about the responsibilities.\n'*80)}
        text=format_post(opp,'telegram')
        self.assertTrue(text.endswith('#Finance #Jobs'))
        caption,rest=telegram_layout(text)
        self.assertLessEqual(visible_units(caption),1024)
        self.assertTrue(caption.endswith('#Finance #Jobs'))
        self.assertFalse(rest)
        self.assertIn('https://example.org/apply',caption)
    def test_ngo_government_and_freshgraduate_require_evidence(self):
        self.assertIn('#NGOJobs',classify_tags({'category':'Job','description':'A humanitarian organization seeks fresh graduates.'}))
        self.assertIn('#FreshGraduate',classify_tags({'category':'Job','description':'No previous experience required.'}))
        self.assertIn('#GovernmentJobs',classify_tags({'category':'Job','organization':'Ministry of Education'}))
    def test_group_keeps_multiple_tags_and_no_placeholder(self):
        raw='Scholarship for Masters\nhttps://example.org/a\nFellowship in medicine\nhttps://example.org/b'
        text=format_post({'category':'Scholarship','title':'Education opportunities','raw_text':raw},'telegram')
        self.assertTrue(text.endswith('#Healthcare #Masters #Scholarships #Fellowships'))
        self.assertNotIn('@YourChannel',text)
