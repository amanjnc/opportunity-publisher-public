import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
from repair_cloud_login import decode_login

class LoginRepairTests(unittest.TestCase):
    def test_encrypted_login_round_trip(self):
        key=Fernet.generate_key()
        value=Fernet(key).encrypt(b'test-session').decode()
        with patch('repair_cloud_login.env',return_value=key.decode()):
            self.assertEqual(decode_login(value),'test-session')
    def test_wrong_key_reports_no_sensitive_content(self):
        value=Fernet(Fernet.generate_key()).encrypt(b'private-session').decode()
        with patch('repair_cloud_login.env',return_value=Fernet.generate_key().decode()):
            with self.assertRaisesRegex(RuntimeError,'Cannot decrypt repaired login') as error:
                decode_login(value)
        self.assertNotIn('private-session',str(error.exception))
        self.assertNotIn(value,str(error.exception))
