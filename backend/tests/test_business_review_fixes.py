# -*- coding: utf-8 -*-
import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.workbench import WorkbenchStore
from core.demo_cases import DemoCases
from core.service_followup import Followups
from core.fact_answers import order_fact,pure_order_question
from core.customer_reply import staff_labels,customer_text,responsibility_prompt
from api.workbench_routes import create_router
from agents.agent_orchestrator import AgentType
from core.intent_recognizer import IntentCategory,UrgencyLevel
from api import main

class BusinessFixTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=WorkbenchStore(Path(self.tmp.name)/'db.sqlite');self.demos=DemoCases(self.store);self.catalog=self.demos.ensure('finance-admin-123');self.ws=self.catalog['workspace_id'];self.actor='finance-admin-123';self.service=Followups(self.store)
  app=FastAPI();app.include_router(create_router(self.store,lambda:None,lambda:None));self.client=TestClient(app)
 def case(self,key):return self.store.get('conversation',next(c['conv_id'] for c in self.catalog['cases'] if c['id']==key))
 def test_service_questions_are_not_pure_order_queries(self):
  for text in ['我的商品少了一条连接线，可以补发吗？','商品破损怎么办','订单晚了几天，能赔偿吗','商品没有收到，下一步谁联系我','订单金额199元，但商品坏了']:
   with self.subTest(text=text):self.assertFalse(pure_order_question(text))
 def test_pure_facts_still_have_a_shortcut(self):
  for text in ['订单金额是多少','这笔订单比预计晚了几天','订单状态是什么','买了什么']:
   with self.subTest(text=text):self.assertTrue(pure_order_question(text))
 def test_generic_product_word_does_not_imply_an_order_fact_question(self):
  self.assertIsNone(order_fact('我的商品少了一条连接线，可以补发吗？',self.store.get('demo_order',self.case('missing')['order_id'])))
 def test_staff_identity_is_not_a_guessed_department(self):
  c=self.case('missing');prompt=responsibility_prompt(self.store,c);self.assertNotIn(self.actor,prompt);self.assertIn('当前负责客服',prompt);self.assertIn('禁止从标识推测角色',prompt)
 def test_structured_member_display_name_is_used(self):
  c=self.case('missing');w=self.store.get('workspace',self.ws);w['members'][0]['display_name']='小林';self.store.put('workspace',w);self.assertEqual(staff_labels(self.store,c)[self.actor],'小林')
 def test_internal_document_id_removed_but_citation_metadata_retained(self):
  c=self.case('missing');doc=self.store.get('demo_document',c['demo_policy_ids'][0]);sources=[dict(document_id=doc['id'],title=doc['title'],version=1)];text=customer_text('根据'+doc['id']+'，由 '+self.actor+' 联系。',sources,staff_labels(self.store,c));self.assertNotIn(doc['id'],text);self.assertNotIn(self.actor,text);self.assertIn(doc['title'],text);self.assertEqual(sources[0]['document_id'],doc['id'])
 def test_label_replacement_does_not_corrupt_longer_customer_tokens(self):
  self.assertEqual(customer_text('编号 alice-order 保持原文',[],{'alice':'当前负责客服'}),'编号 alice-order 保持原文')
 def test_readiness_lists_material_and_associated_ticket(self):
  c=self.case('missing');r=self.service.readiness(c['id'],self.actor,self.ws);self.assertEqual(r['phase'],'补齐并核验必要材料');self.assertTrue(r['requires_exception']);self.assertEqual({x['kind'] for x in r['blocks']},{'material','ticket'})
 def test_ticket_checklist_does_not_block_on_itself(self):
  c=self.case('missing');t=next(t for t in self.store.list('ticket') if t['conv_id']==c['id']);r=self.service.readiness(c['id'],self.actor,self.ws,t['id']);self.assertEqual([x['kind'] for x in r['blocks']],['material'])
 def test_readiness_is_scoped_and_validates_ticket_conversation(self):
  c=self.case('missing');wrong=next(t for t in self.store.list('ticket') if t['conv_id']==self.case('late')['id'])
  self.assertEqual(self.client.get('/conversations/'+c['id']+'/readiness',params=dict(user_id='stranger',workspace_id=self.ws)).status_code,404)
  self.assertEqual(self.client.get('/conversations/'+c['id']+'/readiness',params=dict(user_id=self.actor,workspace_id=self.ws,ticket_id=wrong['id'])).status_code,404)
 def test_readiness_does_not_mutate_or_weaken_closure_guards(self):
  c=self.case('missing');before=self.store.get('conversation',c['id']);self.service.readiness(c['id'],self.actor,self.ws);self.assertEqual(before,self.store.get('conversation',c['id']))
  r=self.client.patch('/conversations/'+c['id'],json=dict(user_id=self.actor,workspace_id=self.ws,status='resolved',resolution='尝试结案',closure_exception='仅内部完成'));self.assertEqual(r.status_code,409);self.assertIn('必要材料',r.json()['detail'])
 def test_demo_gap_options_only_include_current_case_policy(self):
  g=self.store.list('knowledge_gap')[0];r=self.client.get('/knowledge/gaps/'+g['id']+'/documents',params=dict(user_id=self.actor,workspace_id=self.ws));self.assertEqual(r.status_code,200);self.assertEqual([d['id'] for d in r.json()],self.case('knowledge')['demo_policy_ids'])
 def test_gap_options_do_not_leak_to_other_actors(self):
  g=self.store.list('knowledge_gap')[0];self.assertEqual(self.client.get('/knowledge/gaps/'+g['id']+'/documents',params=dict(user_id='stranger',workspace_id=self.ws)).status_code,404)
 def test_business_gap_options_exclude_draft_test_and_archived_docs(self):
  c=self.store.conversation(self.actor);g=self.service.create_gap(self.actor,c['id'],'缺规则',self.actor)
  for id,scope,published,deleted in [('ready','business',1,False),('draft','business',None,False),('test','test',1,False),('archived','business',1,True)]:self.store.put('document',dict(id=id,title=id,scope=scope,published_version=published,deleted=deleted))
  self.assertEqual([d['id'] for d in self.service.gap_documents(g['id'],self.actor)],['ready'])

class BusinessChatFixTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=WorkbenchStore(Path(self.tmp.name)/'db.sqlite');self.actor='finance-admin-123';cat=DemoCases(self.store).ensure(self.actor);self.ws=cat['workspace_id'];self.conv=self.store.get('conversation',next(c['conv_id'] for c in cat['cases'] if c['id']=='missing'))
  intent=SimpleNamespace(intent=IntentCategory.OTHER,intent_group='other',urgency=UrgencyLevel.LOW,entities={},confidence=.8,source_scores={});doc=self.conv['demo_policy_ids'][0]
  result=SimpleNamespace(response='根据 '+doc+'，由 '+self.actor+' 联系；补齐数量说明后核验，未执行补发。',intent=IntentCategory.OTHER,agent_type=AgentType.GENERAL,agent_types=[AgentType.GENERAL],primary_agent=AgentType.GENERAL,supporting_agents=[],routing_reason='test',routing_confidence=.8,escalated=False,latency_ms=1)
  self.orc=SimpleNamespace(recognize_intent=AsyncMock(return_value=intent),run=AsyncMock(return_value=result))
  for p in [patch.object(main,'_store',self.store),patch.object(main,'_orchestrator',self.orc),patch.object(main,'_chat_locks',{})]:p.start();self.addCleanup(p.stop)
 async def send(self,text):return await main.chat(main.ChatRequest(message=text,user_id=self.actor,conv_id=self.conv['id'],workspace_id=self.ws,request_id='check'))
 async def test_missing_item_request_reaches_service_reply_not_order_amount(self):
  r=await self.send('我的商品少了一条连接线，可以补发吗？');self.orc.run.assert_awaited_once();self.assertEqual(r.knowledge_status,'matched');self.assertIn('补发',r.response);self.assertNotIn('199',r.response)
 async def test_reply_and_prompt_hide_internal_staff_and_policy_ids(self):
  r=await self.send('谁负责联系我？');req=self.orc.run.call_args.args[0];self.assertNotIn(self.actor,req.context);self.assertNotIn(self.conv['demo_policy_ids'][0],req.context);self.assertNotIn(self.actor,r.response);self.assertNotIn(self.conv['demo_policy_ids'][0],r.response);self.assertEqual(r.sources[0]['document_id'],self.conv['demo_policy_ids'][0]);self.assertIn('当前负责客服',r.response)
 async def test_mixed_fact_and_policy_context_keeps_calculated_facts(self):
  r=await self.send('比预计晚了几天，补发怎么处理？');self.assertNotEqual(r.knowledge_status,'order_fact');self.assertIn('晚 3 个自然日',self.orc.run.call_args.args[0].context);self.assertTrue(r.data_sources)
