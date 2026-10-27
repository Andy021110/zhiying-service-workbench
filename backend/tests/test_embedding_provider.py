import os
import unittest
from unittest.mock import patch
import httpx
from core.embedding_provider import ConfiguredEmbeddings, configured_embeddings

class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ, {'EMBEDDING_API_KEY':'private-test-key','EMBEDDING_BASE_URL':'https://example.invalid/v1','EMBEDDING_DIMENSIONS':'2'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_batching_and_response_order(self):
        calls=[]
        def post(url,headers,json,timeout):
            self.assertEqual(headers['Authorization'],'Bearer private-test-key')
            self.assertEqual(url,'https://example.invalid/v1/embeddings')
            calls.append(json['input'])
            return httpx.Response(200,json={'data':[{'index':i,'embedding':[float(x),0.]} for i,x in reversed(list(enumerate(json['input'])))]})
        with patch('core.embedding_provider.httpx.post',side_effect=post):
            vectors=ConfiguredEmbeddings()([str(i) for i in range(12)])
        self.assertEqual([len(x) for x in calls],[10,2])
        self.assertEqual([v[0] for v in vectors],list(range(12)))

    def test_dimension_mismatch_fails(self):
        with patch('core.embedding_provider.httpx.post',return_value=httpx.Response(200,json={'data':[{'index':0,'embedding':[1.]}]})):
            with self.assertRaisesRegex(ValueError,'dimension'): ConfiguredEmbeddings()(['text'])

    def test_errors_do_not_expose_provider_body(self):
        with patch('core.embedding_provider.httpx.post',return_value=httpx.Response(401,text='private-test-key')):
            with self.assertRaises(RuntimeError) as error: ConfiguredEmbeddings()(['text'])
        self.assertNotIn('private-test-key',str(error.exception))

    def test_unconfigured_preserves_original_default(self):
        with patch.dict(os.environ,{'EMBEDDING_API_KEY':''}): self.assertEqual(configured_embeddings(),{})

if __name__=='__main__': unittest.main()
