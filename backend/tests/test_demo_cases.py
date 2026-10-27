# -*- coding: utf-8 -*-
import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.workbench import WorkbenchStore
from core.operations import Operations
from core.demo_cases import DemoCases,demo_order,source_document,demo_knowledge
from core.conversation_context import model_history
from core.service_followup import Followups
from api.workbench_routes import create_router
from agents.agent_orchestrator import AgentType
from core.intent_recognizer import IntentCategory,UrgencyLevel
from api import main

class DemoCaseTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=WorkbenchStore(Path(self.tmp.name)/'db.sqlite');self.demo=DemoCases(self.store);self.catalog=self.demo.ensure('alice');self.ws=self.catalog['workspace_id'];self.ops=Operations(self.store)
  app=FastAPI();app.include_router(create_router(self.store,lambda:None,lambda:None));self.client=TestClient(app)
 def case(self,key):return self.store.get('conversation',next(c['conv_id'] for c in self.catalog['cases'] if c['id']==key))
 def test_three_complete_cases_are_idempotent_and_durable(self):
  again=DemoCases(WorkbenchStore(self.store.path)).ensure('alice');self.assertEqual(self.catalog,again)
  for c in self.catalog['cases']:
   conv=self.store.get('conversation',c['conv_id']);self.assertEqual(len(self.store.messages(conv['id'])),6);self.assertTrue(conv['is_demo']);self.assertEqual(len(model_history(self.store,conv['id'],'test')),6);self.assertTrue(demo_order(self.store,conv));self.assertEqual(len(self.demo.guide(conv['id'],'alice',self.ws)['policies']),1)
  self.assertEqual(self.store.list('document'),[]);self.assertEqual(self.store.list('order'),[]);self.assertEqual(self.store.list('document_version'),[])
 def test_concurrent_ensure_creates_only_one_round(self):
  with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(lambda _:DemoCases(WorkbenchStore(self.store.path)).ensure('bob'),range(3)))
  self.assertEqual(len({r['cases'][0]['conv_id'] for r in results}),1);self.assertEqual(len([c for c in self.store.list('conversation') if c['user_id']=='bob']),3)
 def test_new_round_preserves_old_messages_and_retry_is_idempotent(self):
  c=self.case('missing');self.store.append(c['id'],'user','练习补充内容');fresh=self.demo.reset('alice','missing',1);again=self.demo.reset('alice','missing',1)
  self.assertEqual(fresh,again);current=next(x for x in fresh['cases'] if x['id']=='missing');self.assertEqual(current['generation'],2);self.assertNotEqual(current['conv_id'],c['id']);self.assertEqual(current['history'][0]['id'],c['id']);self.assertEqual(len(self.store.messages(c['id'])),7)
 def test_scoped_orders_policies_and_cases_are_not_public(self):
  c=self.case('late');oid=c['order_id'];doc=c['demo_policy_ids'][0]
  for path in ['/orders/'+oid,'/demos/documents/'+doc,'/conversations/'+c['id']]:
   self.assertEqual(self.client.get(path,params={'user_id':'eve','workspace_id':self.ws}).status_code,404)
   self.assertNotEqual(self.client.get(path,params={'user_id':'alice'}).status_code,200)
   self.assertEqual(self.client.get(path,params={'user_id':'alice','workspace_id':self.ws}).status_code,200)
  self.assertEqual(self.client.get('/orders').json(),[]);self.assertEqual(len(self.client.get('/orders',params={'user_id':'alice','workspace_id':self.ws}).json()),3)
 def test_reports_and_normal_conversations_exclude_demo_data(self):
  report=self.ops.report('alice');self.assertEqual(report['open_cases'],0);self.assertEqual(report['resolved_cases'],0);self.assertEqual(self.ops.visible('conversation','alice'),[])
  self.assertIn('练习',self.ops.report('alice',self.ws)['scope']);self.assertEqual(len(self.ops.visible('conversation','alice',self.ws)),3)
 def test_materials_attachment_and_handoff_survive_restart(self):
  c=self.case('missing');bundle=Followups(WorkbenchStore(self.store.path)).bundle(c['id'],'alice',self.ws);self.assertEqual(sorted(m['status'] for m in bundle['materials']),['missing','verified']);a=bundle['attachments'][0];self.assertTrue(Followups(self.store).attachment(a['id'],'alice',self.ws)[1].startswith(b'\x89PNG'));self.assertTrue(a['is_demo']);t=next(t for t in self.store.list('ticket') if t['conv_id']==c['id']);self.assertEqual(t['handoff']['state'],'accepted')
 def test_rechecks_refresh_does_not_duplicate_or_invalidate_seed(self):
  f=Followups(self.store);rows=f.refresh_rechecks('alice',self.ws);self.assertEqual(len(rows),3);knowledge=[r for r in rows if r['conv_id']==self.case('knowledge')['id']];self.assertEqual(len(knowledge),1);r=knowledge[0];self.assertTrue(r['document_current']);self.assertEqual(r['status'],'reviewed');self.assertEqual(f.review(r['id'],'alice','reviewed','继续跟进',r['revision'],self.ws)['status'],'reviewed')
 def test_demo_knowledge_is_case_scoped_and_rejects_cross_case_sources(self):
  a=self.case('late');b=self.case('missing');src=demo_knowledge(self.store,a)[1][0];self.assertTrue(source_document(self.store,src,a));self.assertIsNone(source_document(self.store,src,b));self.assertIsNone(source_document(self.store,src,self.store.conversation('alice')))
 def test_demo_mode_cannot_switch_to_business_or_real_orders(self):
  c=self.case('missing');self.store.put('order',dict(id='real'))
  for patch_body in [dict(knowledge_mode='business'),dict(order_id='real')]:self.assertNotEqual(self.client.patch('/conversations/'+c['id'],json=dict(user_id='alice',workspace_id=self.ws,**patch_body)).status_code,200)
  fresh=self.client.post('/conversations',json=dict(user_id='alice',workspace_id=self.ws,knowledge_mode='business')).json();self.assertTrue(fresh['is_demo']);self.assertEqual(fresh['knowledge_mode'],'test')
 def test_normal_gap_cannot_use_demo_policy(self):
  normal=self.store.conversation('alice');f=Followups(self.store);gap=f.create_gap('alice',normal['id'],'规则','alice');doc=self.case('knowledge')['demo_policy_ids'][0]
  with self.assertRaises(ValueError):f.edit_gap(gap['id'],'alice',dict(owner='alice',status='resolved',document_id=doc,note='不可混用',expected_revision=1))
 def test_demo_gap_cannot_link_another_cases_policy(self):
  c=self.case('missing');f=Followups(self.store);gap=f.create_gap('alice',c['id'],'核对规则','alice',self.ws)
  with self.assertRaises(ValueError):f.edit_gap(gap['id'],'alice',dict(owner='alice',status='resolved',document_id=self.case('late')['demo_policy_ids'][0],note='错误案例的规则',expected_revision=1),self.ws)
 def test_question_does_not_replace_previously_stated_customer_facts(self):
  from core.conversation_context import build_memory
  c=self.case('missing');before=build_memory(self.store,c['id'])['facts'];self.store.append(c['id'],'user','你还记得我的诉求是什么吗？我叫什么名字？我的订单号是什么？');after=build_memory(self.store,c['id'])['facts'];self.assertEqual(before,after)
 def test_demo_space_members_are_fixed(self):
  with self.assertRaises(ValueError):self.ops.member('alice',self.ws,'eve','agent')

class DemoChatTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=WorkbenchStore(Path(self.tmp.name)/'db.sqlite');self.demo=DemoCases(self.store);self.catalog=self.demo.ensure('alice');self.ws=self.catalog['workspace_id']
  intent=SimpleNamespace(intent=IntentCategory.OTHER,intent_group='other',urgency=UrgencyLevel.LOW,entities={},confidence=.8,source_scores={})
  result=SimpleNamespace(response='仅演示规则：继续补齐数量说明。',intent=IntentCategory.OTHER,agent_type=AgentType.GENERAL,agent_types=[AgentType.GENERAL],primary_agent=AgentType.GENERAL,supporting_agents=[],routing_reason='test',routing_confidence=.8,escalated=False,latency_ms=1)
  self.orc=SimpleNamespace(recognize_intent=AsyncMock(return_value=intent),run=AsyncMock(return_value=result))
  for p in [patch.object(main,'_store',self.store),patch.object(main,'_orchestrator',self.orc),patch.object(main,'_chat_locks',{})]:p.start();self.addCleanup(p.stop)
 async def send(self,key,text,nonce):
  id=next(c['conv_id'] for c in self.catalog['cases'] if c['id']==key);return await main.chat(main.ChatRequest(message=text,conv_id=id,user_id='alice',workspace_id=self.ws,request_id=nonce))
 async def test_followup_recalls_seed_and_reopens_without_false_confirmation(self):
  r=await self.send('late','你还记得我的诉求是什么吗？','recall');self.assertIn('核对晚到天数',r.response);conv=self.store.get('conversation',r.conv_id);self.assertEqual(conv['status'],'pending');self.assertEqual(conv['customer_result']['status'],'pending');self.assertEqual(len(conv['customer_result_history']),2)
  self.assertEqual(conv['customer_result_history'][0]['status'],'confirmed');self.assertEqual(len(self.store.messages(r.conv_id)),8);await self.send('late','你还记得我的诉求是什么吗？','recall');self.assertEqual(len(self.store.messages(r.conv_id)),8);self.assertEqual(self.store.get('conversation',r.conv_id)['result_revision'],2)
 async def test_demo_uses_existing_history_materials_and_only_its_policy(self):
  with patch.object(main,'_retrieve_knowledge',AsyncMock(side_effect=AssertionError('global retrieval forbidden'))) as retrieval:r=await self.send('missing','那接下来该怎么继续核对？','next')
  retrieval.assert_not_called();request=self.orc.run.call_args.args[0];self.assertEqual(len(request.history),6);self.assertIn('verified',request.context);self.assertIn('配件数量说明',request.context);self.assertIn('许晴',request.context);self.assertEqual(r.sources[0]['kind'],'demo_policy');self.assertNotIn('周禾',request.context)
 async def test_demo_order_fact_is_synthetic_and_correct_currency(self):
  r=await self.send('late','这笔订单比预计晚了几天？','fact');self.assertIn('晚 3 个自然日',r.response);self.assertIn('合成演示订单',r.response);self.assertNotIn('Olist',r.response)
  r=await self.send('missing','订单金额是什么','amount');self.assertIn('CNY',r.response);self.assertNotIn('BRL',r.response)
