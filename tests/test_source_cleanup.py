import unittest
from source_cleanup import clean_source
from grouped_posts import render_group, is_grouped
from transform import format_post, basic_extract

class SourceCleanupTests(unittest.TestCase):
    def source(self):
        roles=['Internship Program','Finance Director','Head of Unit Treasury',
               'Director Center for Laboratory Diagnostics','Director General',
               'Driver VIP','Interpreter Translator Geneva']
        sections=['🌍 AFRICAN UNION IS HIRING!', '7 active job opportunities']
        for index,role in enumerate(roles):
            sections += ['', '🔹 '+role, '📍 Ethiopia', '👉 Apply: https://lnkd.in/job'+str(index)]
        sections += ['', '📌 Official AU Jobs Portal:', 'https://jobs.au.int/', '',
                     '🔵 LinkedIn: https://lnkd.in/brandLinkedIn',
                     '📲 Telegram: https://t.me/Rez_On_Bridge',
                     '📘 Facebook: https://lnkd.in/brandFacebook',
                     '▶️ YouTube: https://lnkd.in/brandYouTube',
                     '🎵 TikTok: https://lnkd.in/brandTikTok',
                     '#AfricanUnion #AUJobs #REZONBRIDGE']
        return '\n'.join(sections)

    def assert_clean(self,text):
        self.assertNotIn('REZONBRIDGE',text)
        self.assertNotIn('Rez_On_Bridge',text)
        self.assertNotIn('#AfricanUnion',text)
        self.assertNotIn('brand',text)
        for index in range(7):
            self.assertIn('https://lnkd.in/job'+str(index),text)
        self.assertIn('https://jobs.au.int/',text)

    def test_seven_au_roles_keep_application_links_remove_social_footer(self):
        raw=self.source()
        self.assertTrue(is_grouped(raw))
        self.assert_clean(render_group(raw))

    def test_existing_queued_html_is_cleaned_again_at_publish_time(self):
        raw=self.source()
        html=raw.replace('Finance Director','<b>Finance Director</b>')
        text=format_post({'raw_text':raw,'telegram_text':html},'telegram')
        self.assert_clean(text)
        self.assertIn('<b>Finance Director</b>',text)

    def test_native_hidden_social_links_and_appended_copies_removed(self):
        raw='Internship Programme\nhttps://example.org/apply\n<a href="https://lnkd.in/brand">🔵 LinkedIn:</a>\nhttps://lnkd.in/brand'
        text=clean_source(raw)
        self.assertNotIn('brand',text)
        self.assertIn('https://example.org/apply',text)

    def test_fragment_links_email_and_linkedin_job_survive(self):
        raw='C# developer job\nEmail: hiring@example.org\nhttps://example.org/apply#requirements\nhttps://www.linkedin.com/jobs/view/123'
        self.assertEqual(clean_source(raw),raw)

    def test_social_footer_not_selected_as_application_url(self):
        raw='Research assistant job\nApply: https://example.org/apply\n🔵 LinkedIn: https://lnkd.in/brand\n#Job #SourceBrand'
        result=basic_extract(raw,'channel')
        self.assertEqual(result['apply_url'],'https://example.org/apply')
        self.assertNotIn('brand',result['description'])
        self.assertNotIn('SourceBrand',result['description'])

    def test_facts_on_hashtag_line_are_retained(self):
        self.assertEqual(clean_source('Salary USD 500 #Jobs'),'Salary USD 500')

    def test_idempotent(self):
        once=clean_source(self.source())
        self.assertEqual(once,clean_source(once))
