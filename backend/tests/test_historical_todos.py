# -*- coding: utf-8 -*-
import tempfile,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.workbench import WorkbenchStore
from core.historical_todos import HistoricalTodos,EXAMPLES
from core.operations import Operations
from api.workbench_routes import create_router

class HistoricalTodoTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=WorkbenchStore(Path(self.tmp.name)/'db.sqlite');self.service=HistoricalTodos(self.store);self.ops=Operations(self.store)
  self.store.put('dataset',dict(id='olist',source_url='https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce',imported_reviews=120,model_calls=0,embedding_calls=0))
  for index,spec in enumerate(EXAMPLES):
   oid='order-'+str(index);self.store.put('order',dict(id=oid,status='delivered',currency='BRL',total=100,estimated_at='2018-01-02',delivered_at='2018-01-05',items=[]));self.store.put('review',dict(id=spec['review_id']+':'+oid,review_id=spec['review_id'],order_id=oid,score=1,content='Original português '+str(index),created_at='2018-01-03 00:00:00'))
 def test_creates_six_actionable_tasks_with_original_sources(self):
  result=self.service.ensure('alice');self.assertEqual(len(result['items']),6)
  for item in result['items']:
   conv=self.store.get('conversation',item['conv_id']);messages=self.store.messages(conv['id']);self.assertEqual(len(messages),1);self.assertEqual(messages[0]['content'],item['review']['content']);self.assertEqual(messages[0]['source_created_at'],item['review']['created_at']);self.assertNotIn('guide',messages[0]);self.assertNotEqual(conv['practice_guide'],messages[0]['content']);self.assertTrue(item['next_action']);self.assertEqual(item['owner'],'alice')
 def test_concurrent_initialization_does_not_duplicate_cases(self):
  with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(lambda _:HistoricalTodos(WorkbenchStore(self.store.path)).ensure('alice'),range(3)))
  self.assertEqual(results[0],results[1]);self.assertEqual(results[1],results[2]);self.assertEqual(len(self.store.list('conversation')),6);self.assertEqual(len(self.store.list('ticket')),6)
 def test_returning_does_not_overwrite_processing_or_messages(self):
  result=self.service.ensure('alice');item=result['items'][0];t=self.store.get('ticket',item['ticket_id']);t.update(status='resolved',next_action='人工已完成核对',revision=2);self.store.put('ticket',t);self.store.append(item['conv_id'],'note','我的处理笔记')
  again=self.service.ensure('alice');updated=next(i for i in again['items'] if i['key']==item['key']);self.assertEqual(updated['status'],'resolved');self.assertEqual(updated['next_action'],'人工已完成核对');self.assertEqual(len(self.store.messages(item['conv_id'])),2);self.assertEqual(self.store.get('ticket',t['id'])['revision'],2)
 def test_practice_does_not_mix_with_personal_or_synthetic_spaces(self):
  normal=self.store.conversation('alice','个人已有事项');result=self.service.ensure('alice');ws=result['workspace_id'];self.assertEqual([c['id'] for c in self.ops.visible('conversation','alice')],[normal['id']]);self.assertEqual(len(self.ops.visible('conversation','alice',ws)),6)
  with self.assertRaises(KeyError):self.ops.visible('ticket','eve',ws)
  other=self.service.ensure('eve');self.assertNotEqual(ws,other['workspace_id']);self.assertTrue(set(i['conv_id'] for i in other['items']).isdisjoint(i['conv_id'] for i in result['items']))
 def test_reusing_feedback_entry_opens_same_practice_record(self):
  result=self.service.ensure('alice');item=result['items'][0];opened=self.ops.feedback_case('alice',item['review']['id'],result['workspace_id']);self.assertTrue(opened['already_exists']);self.assertEqual(opened['conversation']['id'],item['conv_id']);self.assertEqual(len(self.store.list('ticket')),6)
 def test_read_only_dataset_orders_reviews_and_knowledge_unchanged(self):
  kinds=['dataset','order','review','document','document_version'];before={k:self.store.list(k) for k in kinds};self.service.ensure('alice');self.assertEqual(before,{k:self.store.list(k) for k in kinds})
 def test_missing_source_order_is_omitted_without_fabrication(self):
  with self.store.connect() as db:db.execute("DELETE FROM records WHERE kind='order' AND id='order-0'")
  result=self.service.ensure('alice');self.assertEqual(len(result['items']),5);self.assertNotIn('not_received',[i['key'] for i in result['items']]);self.assertIsNone(self.store.get('order','order-0'))
 def test_empty_source_returns_explanation_without_creating_records(self):
  empty=WorkbenchStore(Path(self.tmp.name)/'empty.sqlite');result=HistoricalTodos(empty).ensure('alice');self.assertEqual(result['items'],[]);self.assertIsNone(result['workspace_id']);self.assertIn('导入',result['scope']);self.assertEqual(empty.list('workspace'),[])
 def test_practice_deadline_starts_now_and_owner_queue_is_actionable(self):
  result=self.service.ensure('alice');queue=self.ops.queue('alice',result['workspace_id']);self.assertEqual(len(queue['items']),6);self.assertTrue(all(t['assigned_to_me'] and not t['overdue'] for t in queue['items']))
  hours=(datetime.fromisoformat(queue['items'][0]['due_at'])-datetime.now(timezone.utc)).total_seconds()/3600;self.assertGreater(hours,3.9);self.assertLessEqual(hours,4);self.assertEqual(self.ops.report('alice')['open_cases'],0)
 def test_api_actor_validation_and_restart_persistence(self):
  app=FastAPI();app.include_router(create_router(self.store,lambda:None,lambda:None));client=TestClient(app);self.assertEqual(client.post('/historical-todos/ensure',json=dict(user_id=' ')).status_code,422)
  result=client.post('/historical-todos/ensure',json=dict(user_id='alice')).json();self.assertEqual(len(result['items']),6);self.assertEqual(result,HistoricalTodos(WorkbenchStore(self.store.path)).ensure('alice'))
