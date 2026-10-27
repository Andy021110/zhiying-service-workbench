import unittest
from types import SimpleNamespace
from core.llm_utils import generation_options
class ProviderOptionsTests(unittest.TestCase):
    def test_deepseek_uses_output_budget_for_structured_text(self):
        client=SimpleNamespace(base_url='https://api.deepseek.com/anthropic/')
        self.assertEqual(generation_options(client), {'extra_body':{'thinking':{'type':'disabled'}}})
    def test_other_providers_keep_their_defaults(self):
        for url in ['https://api.anthropic.com/','https://api.deepseek.com.evil.invalid/']:
            self.assertEqual(generation_options(SimpleNamespace(base_url=url)),{})
if __name__=='__main__': unittest.main()
