import unittest
from pydantic import ValidationError
from api.main import ChatRequest
class ChatInputTests(unittest.TestCase):
    def test_empty_and_whitespace_messages_are_rejected(self):
        for message in ['', ' \t\n']:
            with self.subTest(message=repr(message)), self.assertRaises(ValidationError): ChatRequest(message=message)
    def test_normal_message_is_trimmed(self):
        self.assertEqual(ChatRequest(message='  退款多久到账？  ').message,'退款多久到账？')
if __name__=='__main__': unittest.main()
