# -*- coding: utf-8 -*-
import csv,json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock,patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.workbench import WorkbenchStore
from core.operations import Operations
from core.service_followup import Followups
from core.reply_requests import ReplyRequests
from core.service_reference import chronology
from core.assistant_outputs import public_messages
from core.conversation_context import model_history
from core.olist_import import backfill_review_times
from api.workbench_routes import create_router
from api import main
from core.intent_recognizer import IntentCategory,UrgencyLevel

class TrialFixTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=WorkbenchStore(Path(self.tmp.name)/'db.sqlite');self.ops=Operations(self.store);self.follow=Followups(self.store)
  self.store.put('order',dict(id='o',status='delivered',total=528.78,currency='BRL',purchased_at='2018-02-21 11:45:07',estimated_at='2018-03-14 00:00:00',delivered_at='2018-03-20 14:32:41',items=[dict(product_id='p',price=1,freight=2)]*14))
  self.review=dict(id='r:o',review_id='r',order_id='o',score=1,content='Comprei 14 unidades e recebi somente 9.',created_at='2018-03-02 00:00:00',review_creation_date='2018-03-02 00:00:00',review_answer_timestamp='2018-03-03 00:44:54');self.store.put('review',self.review)
  opened=self.ops.feedback_case('alice','r:o');self.conv=opened['conversation'];self.conv['intake']['issue_type']='missing';self.store.put('conversation',self.conv)
  app=FastAPI();app.include_router(create_router(self.store,lambda:None,lambda:None));self.client=TestClient(app)
 def batch(self,**extra):return dict(keys=['quantity'],owner='alice',due_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),required=False,**extra)
 def test_legacy_reference_cannot_be_adopted_or_edited(self):
  m=self.store.append(self.conv['id'],'assistant','机器翻译',knowledge_status='source_translation',review_state='draft',revision=1)
  for adopt in [False,True]:
   with self.assertRaisesRegex(ValueError,'客服参考'):self.store.update_draft(self.conv['id'],m['id'],'alice','误用作客户回复',1,adopt)
  self.assertEqual(self.store.messages(self.conv['id'])[-1],m)
 def test_old_adopted_reference_does_not_enter_model_history_or_revision(self):
  m=self.store.append(self.conv['id'],'assistant','内部翻译不应成为已发送回复',knowledge_status='source_translation',review_state='adopted',knowledge_mode='business')
  self.assertFalse(any('内部翻译' in h['content'] for h in model_history(self.store,self.conv['id'],'business')))
  with self.assertRaisesRegex(ValueError,'客服参考'):self.ops.revise(self.conv['id'],m['id'],'alice')
 def test_old_staff_order_result_is_read_only_reference_but_customer_answer_is_not(self):
  self.store.append(self.conv['id'],'operation','核对时效',kind='staff_action',reply_request_id='request')
  a=self.store.append(self.conv['id'],'assistant','核对结果',knowledge_status='order_fact',reply_request_id='request',review_state='draft',revision=1)
  b=self.store.append(self.conv['id'],'assistant','对客事实答复',knowledge_status='order_fact',output_type='reply',review_state='draft',revision=1)
  public=public_messages(self.store,self.conv);self.assertEqual(next(m for m in public if m['id']==a['id'])['output_type'],'reference');self.assertEqual(next(m for m in public if m['id']==b['id'])['output_type'],'reply')
 def test_old_custom_analysis_and_its_revision_are_references(self):
  self.store.append(self.conv['id'],'operation','整理事实',kind='staff_action',action='custom',reply_request_id='old')
  parent=self.store.append(self.conv['id'],'assistant','旧内部核对',knowledge_status='no_match',reply_request_id='old',review_state='adopted')
  child=self.store.append(self.conv['id'],'assistant','旧修订内容',parent_message_id=parent['id'],knowledge_status='no_match',review_state='draft',revision=1)
  public=public_messages(self.store,self.conv);self.assertEqual(next(m for m in public if m['id']==child['id'])['output_type'],'reference')
  with self.assertRaisesRegex(ValueError,'客服参考'):self.store.update_draft(self.conv['id'],child['id'],'alice','正文',1,True)
 def test_public_time_enrichment_keeps_original_text_and_legacy_date(self):
  original=self.store.messages(self.conv['id'])[0];public=public_messages(self.store,self.conv)[0];self.assertEqual(public['source_created_at'],original['source_created_at']);self.assertEqual(public['source_answered_at'],'2018-03-03 00:44:54');self.assertEqual(public['content'],original['content']);self.assertEqual(self.store.messages(self.conv['id'])[0],original)
 def test_timeline_uses_answer_time_and_orders_all_events(self):
  text=chronology(self.store,self.conv,self.store.get('order','o'));self.assertIn('客户作答早于',text);self.assertIn('晚 6 个自然日',text);self.assertIn('源数据未提供时区',text)
  self.assertLess(text.index('客户评价作答：2018-03-03'),text.index('预计送达：2018-03-14'))
 def test_missing_answer_time_is_not_inferred_from_creation(self):
  r=self.review.copy();r.pop('review_answer_timestamp');self.store.put('review',r);text=chronology(self.store,self.conv,self.store.get('order','o'));self.assertIn('不能把评价创建时间',text);self.assertNotIn('客户作答早于',text)
 def test_manual_draft_from_reference_is_separate_traceable_and_idempotent(self):
  m=self.store.append(self.conv['id'],'assistant','内部事实分析',output_type='reference',review_state='reference');replies=ReplyRequests(self.store)
  draft=replies.manual(self.conv,'alice','nonce','单独写给客户的正文',m['id']);again=replies.manual(self.conv,'alice','nonce','单独写给客户的正文',m['id']);self.assertEqual(draft,again);self.assertEqual(draft['source_reference_id'],m['id']);self.assertTrue(draft['manual']);self.assertNotEqual(draft['id'],m['id']);self.assertEqual(self.store.messages(self.conv['id'])[-2],m)
 def test_manual_reference_cannot_point_to_another_conversation(self):
  other=self.store.conversation('alice');m=self.store.append(other['id'],'assistant','其他事项参考',output_type='reference')
  with self.assertRaisesRegex(ValueError,'参考记录不在'):ReplyRequests(self.store).manual(self.conv,'alice','nonce','正文',m['id'])
 def test_suggested_materials_are_opt_in_and_start_missing(self):
  before=self.follow.bundle(self.conv['id'],'alice');self.assertEqual(before['materials'],[]);self.assertEqual(len(before['material_suggestions']),2)
  made=self.follow.add_suggestions(self.conv['id'],'alice',self.batch());self.assertEqual(len(made),1);self.assertEqual(made[0]['status'],'missing');self.assertFalse(made[0]['required']);self.assertIn('客服选择',made[0]['history'][0]['note'])
 def test_suggestion_retries_do_not_reset_verified_existing_material(self):
  body=self.batch();first=self.follow.add_suggestions(self.conv['id'],'alice',body)[0];first.update(status='verified',required=True,revision=2);self.store.put('material',first)
  again=self.follow.add_suggestions(self.conv['id'],'alice',dict(body,required=False,owner='alice'))[0];self.assertEqual(first,again);self.assertEqual(len(self.store.list('material')),1)
 def test_suggestions_recognize_already_collected_manual_material(self):
  existing=self.follow.material(self.conv['id'],'alice',dict(name='客户数量说明',owner='alice',required=True,status='verified',due_at=self.batch()['due_at'],note='已有数量凭证完成核验'))
  self.assertEqual(self.follow.add_suggestions(self.conv['id'],'alice',self.batch())[0]['id'],existing['id']);self.assertEqual(len(self.store.list('material')),1)
 def test_suggestion_batch_validates_all_choices_before_any_write(self):
  with self.assertRaises(ValueError):self.follow.add_suggestions(self.conv['id'],'alice',dict(self.batch(),keys=['quantity','unknown']))
  self.assertEqual(self.store.list('material'),[])
 def test_suggestion_batch_concurrency_is_idempotent(self):
  body=self.batch()
  with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(lambda _:Followups(WorkbenchStore(self.store.path)).add_suggestions(self.conv['id'],'alice',body),range(2)))
  self.assertEqual(rows[0],rows[1]);self.assertEqual(len(self.store.list('material')),1)
 def test_suggestion_owner_and_scope_cannot_be_forged(self):
  with self.assertRaises(ValueError):self.follow.add_suggestions(self.conv['id'],'alice',dict(self.batch(),owner='eve'))
  with self.assertRaises(KeyError):self.follow.add_suggestions(self.conv['id'],'eve',self.batch())
  r=self.client.post('/conversations/'+self.conv['id']+'/material-suggestions',json=dict(self.batch(),user_id='alice',keys=[]));self.assertEqual(r.status_code,422)
 def test_required_suggestion_blocks_closure_until_reviewed(self):
  self.follow.add_suggestions(self.conv['id'],'alice',dict(self.batch(),required=True))
  with self.assertRaisesRegex(ValueError,'必要材料'):self.ops.patch_conversation(self.conv['id'],'alice',dict(status='resolved',resolution='不应提前结案',closure_exception='仅内部完成'))
 def test_time_migration_only_adds_source_columns_and_is_repeatable(self):
  raw=Path(self.tmp.name)/'raw';raw.mkdir();source=raw/'olist_order_reviews_dataset.csv'
  with source.open('w',newline='') as f:
   writer=csv.DictWriter(f,fieldnames=['review_id','order_id','review_creation_date','review_answer_timestamp']);writer.writeheader();writer.writerow(dict(review_id='r',order_id='o',review_creation_date='2018-03-02 00:00:00',review_answer_timestamp='2018-03-03 00:44:54'))
  old=self.review.copy();old.pop('review_creation_date');old.pop('review_answer_timestamp');self.store.put('review',old);order=self.store.get('order','o');messages=self.store.messages(self.conv['id'])
  self.assertEqual(backfill_review_times(raw,self.store)['updated'],1);self.assertEqual(backfill_review_times(raw,self.store)['updated'],0);enriched=self.store.get('review','r:o');self.assertEqual({k:enriched[k] for k in old},old);self.assertEqual(self.store.get('order','o'),order);self.assertEqual(self.store.messages(self.conv['id']),messages)

class TrialChatFixTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=WorkbenchStore(Path(self.tmp.name)/'db.sqlite')
  self.conv=self.store.conversation('alice','少件处理','o');self.conv.update(knowledge_mode='business',intake=dict(issue_type='missing'));self.store.put('conversation',self.conv)
  self.store.put('order',dict(id='o',status='delivered',total=100,currency='BRL',items=[dict(product_id='p',price=1,freight=2)]*14,estimated_at='2018-03-14',delivered_at='2018-03-20'))
  self.store.append(self.conv['id'],'user','Comprei 14 unidades e recebi somente 9.',source='真实葡萄牙语评价原文')
  intent=SimpleNamespace(intent=IntentCategory.OTHER,intent_group='other',urgency=UrgencyLevel.LOW,entities={},confidence=.7,source_scores={});self.orc=SimpleNamespace(recognize_intent=AsyncMock(return_value=intent),run=AsyncMock(side_effect=AssertionError('No-policy assistance must not use speculative generated policy')))
  for p in [patch.object(main,'_store',self.store),patch.object(main,'_orchestrator',self.orc),patch.object(main,'_chat_locks',{}),patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'no_match')))]:p.start();self.addCleanup(p.stop)
 async def send(self,text,**kw):return await main.chat(main.ChatRequest(message=text,user_id='alice',conv_id=self.conv['id'],**kw))
 async def test_no_policy_still_provides_fact_checklist_and_separate_draft(self):
  r=await self.send('请整理已知事实和下一步，并准备不承诺补发的回复',input_kind='staff_action',action='custom',request_id='reference')
  self.assertEqual(r.output_type,'reference');self.assertEqual(r.knowledge_status,'no_match');self.assertIn('待核实与下一步',r.response);self.assertIn('14 行',r.response);self.assertIn('不等于已核实',r.response);self.assertIn('Comprei 14',r.response);self.assertTrue(r.suggested_reply);self.assertNotIn('待核实与下一步',r.suggested_reply);self.orc.run.assert_not_called()
  messages=self.store.messages(self.conv['id']);self.assertEqual(messages[-1]['kind'],'assistant_reference');self.assertEqual(messages[-1]['review_state'],'reference')
  again=await self.send('请整理已知事实和下一步，并准备不承诺补发的回复',input_kind='staff_action',action='custom',request_id='reference');self.assertEqual(again,r);self.assertEqual(len(self.store.messages(self.conv['id'])),3)
 async def test_customer_request_without_policy_gets_cautious_reply_not_internal_analysis(self):
  r=await self.send('可以补发吗？');self.assertEqual(r.output_type,'reply');self.assertIn('无法确认',r.response);self.assertNotIn('###',r.response);self.assertFalse(r.suggested_reply)
 async def test_redraft_is_a_customer_draft_not_a_staff_reference(self):
  r=await self.send('根据最近原话重新准备回复',input_kind='staff_action',action='redraft');self.assertEqual(r.output_type,'reply');self.assertIn('无法确认',r.response)
 async def test_staff_timeline_does_not_require_model_or_policy(self):
  r=await self.send('请按时间线整理评价当时情况',input_kind='staff_action',action='custom');self.assertEqual(r.output_type,'reference');self.assertIn('历史时间线',r.response);self.assertIn('作答时间：未收录',r.response);self.orc.run.assert_not_called()

 async def test_explicit_human_transfer_still_creates_one_local_ticket_without_policy(self):
  r=await self.send('我要转人工客服');self.assertTrue(r.escalated);self.assertTrue(r.ticket_id);self.assertIn('未通知外部',r.response);self.assertEqual(len(self.store.list('ticket')),1)
