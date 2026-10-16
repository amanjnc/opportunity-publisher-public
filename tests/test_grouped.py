import unittest
from unittest.mock import patch
from grouped_posts import is_grouped, group_category, render_group, split_messages
from message_layout import visible_text, visible_units
from image_assets import attachment_image
from publish import send_telegram
from transform import format_post

RAW = """🌍 FAO Africa & Headquarters Opportunities

Internship Programme – Africa (RAF)
📅 Deadline: January 1, 2027
https://example.org/internship

Regular Volunteer Programme – HQ
📅 Deadline: January 1, 2027
https://example.org/volunteer

Fellows Programme – HQ
📅 Deadline: January 1, 2027
https://example.org/fellows

📢 Follow AbiLink for more Job & Scholarship opportunities"""

class GroupedTests(unittest.TestCase):
    def test_mixed_group_preserves_every_program_and_link(self):
        self.assertTrue(is_grouped(RAW))
        self.assertEqual(group_category(RAW),'Other')
        text=format_post({'raw_text':RAW,'title':'FAO','category':'Volunteering'},'telegram')
        self.assertEqual(text.count('January 1, 2027'),3)
        for url in ('internship','volunteer','fellows'):
            self.assertIn('https://example.org/'+url,text)
        self.assertNotIn('Follow AbiLink',text)
    def test_native_html_keeps_hidden_links_and_bold(self):
        html='<b>Internship Programme</b>\n<a href="https://example.org/a">Apply</a>\n\n<b>Fellows Programme</b>\n<a href="https://example.org/b">Apply</a>'
        text=render_group(RAW,html)
        self.assertEqual(text,html)
    def test_education_only_group(self):
        raw='Scholarship in France\nhttps://example.org/a\nFellowship in Sweden\nhttps://example.org/b'
        self.assertTrue(is_grouped(raw))
        self.assertEqual(group_category(raw),'Scholarship')
    def test_single_program_with_multiple_links_not_grouped(self):
        self.assertFalse(is_grouped('Internship Programme\nApply: https://example.org/a\nDetails: https://example.org/b'))
    def test_no_source_image_no_generated_fallback(self):
        self.assertIsNone(attachment_image({'title':'Example'}))
        self.assertIsNone(attachment_image({'image_path':'../../private.png'}))
    def test_text_only_sender_records_confirmed_text(self):
        with patch('publish.env',return_value='configured'),patch('publish.send_telegram_text',return_value='51') as send:
            parts=[]
            self.assertEqual(send_telegram('<b>Opportunity</b>',on_part=lambda *a:parts.append(a)),'51')
            send.assert_called_once_with('<b>Opportunity</b>',channel='configured')
            self.assertEqual(parts,[('51','text')])
    def test_long_html_preserves_all_visible_text(self):
        original='<b>'+('Title 🎓 &amp; details\n'*400)+'</b><a href="https://example.org/apply">Apply</a>'
        pieces=split_messages(original)
        self.assertGreater(len(pieces),1)
        self.assertTrue(all(visible_units(x)<=4096 for x in pieces))
        self.assertEqual(''.join(visible_text(x) for x in pieces),visible_text(original))
        self.assertIn('https://example.org/apply',pieces[-1])
