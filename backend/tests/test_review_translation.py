# -*- coding: utf-8 -*-
import asyncio,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.workbench import WorkbenchStore
from core.review_translation import ReviewTranslations
from api.review_translation_routes import create_review_translation_router

class ReviewTranslationTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=WorkbenchStore(Path(self.tmp.name)/'db');self.service=ReviewTranslations(self.store)
  self.review=dict(id='review:order',title='Não chegou',content='Comprei 14 unidades e recebi somente 9. Ainda não foi resolvida.',score=1,order_id='order')
  self.store.put('review',self.review);self.translate=AsyncMock(return_value='我购买了14件，只收到9件，问题尚未解决。')
 def test_no_translation_does_not_call_model(self):
  self.assertEqual(self.service.get(self.review['id'])['state'],'missing');self.translate.assert_not_called();self.assertEqual(self.store.list('review_translation'),[])
 async def test_caches_full_review_translation_without_changing_original(self):
  a=await self.service.ensure(self.review['id'],'alice',self.translate);b=await self.service.ensure(self.review['id'],'bob',self.translate)
  self.assertEqual(a,b);self.translate.assert_awaited_once_with(self.review);self.assertEqual(a['original_content'],self.review['content']);self.assertEqual(a['original_title'],self.review['title']);self.assertTrue(a['machine_translated']);self.assertEqual(self.store.get('review',self.review['id']),self.review);self.assertEqual(self.store.list('conversation'),[])
 async def test_persisted_translation_can_be_read_offline(self):
  a=await self.service.ensure(self.review['id'],'alice',self.translate);other=ReviewTranslations(WorkbenchStore(self.store.path));self.assertEqual(other.get(self.review['id']),a)
 async def test_edited_original_invalidates_old_translation(self):
  old=await self.service.ensure(self.review['id'],'alice',self.translate);self.review['content']='Recebi 10 unidades.';self.store.put('review',self.review)
  self.assertEqual(self.service.get(self.review['id'])['state'],'missing');new=await self.service.ensure(self.review['id'],'alice',self.translate);self.assertNotEqual(old['id'],new['id']);self.assertEqual(len(self.store.list('review_translation')),2)
 async def test_edit_during_generation_rejects_stale_output(self):
  async def translate(review):self.store.put('review',dict(review,content='Outro texto'));return '旧译文'
  with self.assertRaises(ValueError):await self.service.ensure(self.review['id'],'alice',translate)
  self.assertEqual(self.store.list('review_translation'),[])
 async def test_failure_and_empty_output_do_not_cache_fake_success(self):
  for translator in [AsyncMock(side_effect=RuntimeError('provider unavailable')),AsyncMock(return_value='')]:
   with self.assertRaises(RuntimeError):await self.service.ensure(self.review['id'],'alice',translator)
  self.assertEqual(self.service.get(self.review['id'])['state'],'missing')
 async def test_unknown_review_does_not_use_model(self):
  with self.assertRaises(KeyError):await self.service.ensure('unknown','alice',self.translate)
  self.translate.assert_not_called()
 def test_routes_return_missing_cached_and_safe_retry_errors(self):
  app=FastAPI();app.include_router(create_review_translation_router(lambda:self.store,self.translate));client=TestClient(app);path='/feedback/review:order/translation'
  self.assertEqual(client.get(path).json()['state'],'missing');first=client.post(path,json={'user_id':'alice'});self.assertEqual(first.status_code,200);self.assertEqual(client.get(path).json()['text'],first.json()['text']);self.assertEqual(client.post(path,json={'user_id':'bob'}).json()['id'],first.json()['id']);self.assertEqual(self.translate.await_count,1)
  self.assertEqual(client.get('/feedback/unknown/translation').status_code,404);self.assertEqual(client.post(path,json={'user_id':''}).status_code,422)
 def test_provider_failure_route_is_retryable_and_does_not_leak(self):
  app=FastAPI();app.include_router(create_review_translation_router(lambda:self.store,AsyncMock(side_effect=RuntimeError('secret upstream detail'))));client=TestClient(app)
  r=client.post('/feedback/review:order/translation',json={'user_id':'alice'});self.assertEqual(r.status_code,503);self.assertNotIn('secret',r.text);self.assertEqual(self.service.get(self.review['id'])['state'],'missing')
 async def test_prompt_uses_full_review_only_and_requests_faithful_translation(self):
  from api import main
  orchestrator=SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(response='完整译文')))
  with patch.object(main,'_orchestrator',orchestrator),patch.object(main,'_store',self.store):text=await main._translate_customer_review(self.review,'alice')
  request=orchestrator.run.call_args.args[0];self.assertIn(self.review['content'],request.context);self.assertIn('只输出中文译文',request.message);self.assertIn('不补写缺失内容',request.context);self.assertIsNone(request.history);self.assertEqual(text,'完整译文')
 async def test_concurrent_route_requests_share_one_generation(self):
  from httpx import AsyncClient,ASGITransport
  app=FastAPI();app.include_router(create_review_translation_router(lambda:self.store,self.translate))
  async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
   a,b=await asyncio.gather(client.post('/feedback/review:order/translation',json={'user_id':'alice'}),client.post('/feedback/review:order/translation',json={'user_id':'bob'}))
  self.assertEqual(a.status_code,200);self.assertEqual(a.json()['id'],b.json()['id']);self.translate.assert_awaited_once()
