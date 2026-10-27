# -*- coding: utf-8 -*-
import asyncio,tempfile,unittest
from pathlib import Path
from core.workbench import WorkbenchStore,now
from core.operations import Operations
from core.service_followup import Followups
from core.closure_plans import followup_state
from core.handoff_tasks import preview
from core.draft_translation import create,source,digest
from core.reply_requests import ReplyRequests
from core.service_reference import responsibility_reference
from api.workbench_routes import create_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
class FlowFixes(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=WorkbenchStore(Path(self.tmp.name)/'db');self.ops=Operations(self.store);self.svc=Followups(self.store)
  self.ws=self.ops.workspace('a','试用');self.ops.member('a',self.ws['id'],'b','agent');self.conv=self.store.conversation('a');self.conv.update(workspace_id=self.ws['id'],owner='a');self.store.put('conversation',self.conv);self.t=self.store.ticket(self.conv,'测试')
  self.scope={'user_id':'a','workspace_id':self.ws['id']};self.due='2027-01-01T10:00:00+08:00';app=FastAPI();app.include_router(create_router(self.store,lambda:None,lambda:None));self.client=TestClient(app)
 def plan(self,kind='followup',**kw):return dict(kind=kind,note='完成内部核对，后续按安排处理',owner='a',next_action='约定回访',due_at=self.due,expected_result_revision=0,expected_plan_revision=0,**kw)
 def close(self,plan=None):return self.ops.update_ticket(self.t['id'],'a',dict(owner='a',status='resolved',note='核对完成',closure_plan=plan),self.ws['id'])
 def material(self,name='材料'):return self.svc.material(self.conv['id'],'a',dict(name=name,owner='a',due_at=self.due,status='missing',required=False),self.ws['id'])
 def outcome(self):return self.svc.customer_result(self.conv['id'],'a',dict(status='pending',occurred_at=now(),note='待客户确认',owner='a',next_action='回访客户',due_at=self.due,expected_revision=0),self.ws['id'])
 def offer(self,decisions):
  with self.store.connect() as db:p=preview(db,self.conv['id'])
  return self.ops.update_ticket(self.t['id'],'a',dict(owner='b',status='pending',note='交接',handoff_context_hash=p['context_hash'],handoff_tasks=[dict(key=x['key'],decision=decisions.get(x['kind'],'transfer')) for x in p['items']]),self.ws['id'])
 def test_unknown_cannot_close_without_explicit_plan(self):
  with self.assertRaises(ValueError):self.close()
  self.assertNotEqual(self.store.get('ticket',self.t['id'])['status'],'resolved')
 def test_internal_close_keeps_followup_without_inventing_customer_feedback(self):
  self.close(self.plan());c=self.store.get('conversation',self.conv['id']);self.assertIsNone(c.get('customer_result'));self.assertEqual(followup_state(c)['owner'],'a');self.assertEqual(followup_state(c)['source'],'closure_plan')
  response=self.client.get('/operations/followups',params=self.scope).json();self.assertEqual(len(response['customer_results']),1)
 def test_no_followup_requires_reason_and_survives_reload(self):
  p=self.plan('no_followup');p['note']=''
  with self.assertRaises(ValueError):self.close(p)
  self.close(self.plan('no_followup'));c=WorkbenchStore(self.store.path).get('conversation',self.conv['id']);self.assertIsNone(followup_state(c));self.assertTrue(c['closure_plan_history'])
 def test_cannot_fabricate_confirmation_or_silently_overwrite_new_result(self):
  with self.assertRaises(ValueError):self.close(self.plan('confirmed'))
  self.outcome()
  with self.assertRaises(ValueError):self.close(self.plan())
 def test_legacy_closed_unknown_is_auditable_and_can_be_corrected(self):
  self.conv.update(status='resolved');self.store.put('conversation',self.conv);self.assertEqual(followup_state(self.conv)['source'],'closure_review')
  self.svc.closure_plan(self.conv['id'],'a',self.plan('no_followup'),self.ws['id']);self.assertIsNone(followup_state(self.store.get('conversation',self.conv['id'])))
 def test_required_material_still_blocks_explicit_closure(self):
  m=self.material();m['required']=True;self.store.put('material',m)
  with self.assertRaises(ValueError):self.close(self.plan('no_followup'))
  self.assertNotIn('closure_plan',self.store.get('conversation',self.conv['id']))
 def test_reopen_invalidates_previous_no_followup(self):
  self.close(self.plan('no_followup'));self.ops.update_ticket(self.t['id'],'a',dict(owner='a',status='pending',note='新问题'),self.ws['id'],True)
  self.assertFalse(self.store.get('conversation',self.conv['id'])['closure_plan']['active'])
 def test_handoff_requires_complete_explicit_task_choices(self):
  self.material();self.outcome()
  with self.assertRaises(ValueError):self.ops.update_ticket(self.t['id'],'a',dict(owner='b',status='pending',note='交接'),self.ws['id'])
  self.assertEqual(self.store.get('ticket',self.t['id'])['owner'],'a')
 def test_mixed_transfer_preserves_feedback_history_and_retains_material(self):
  m=self.material();self.outcome();before=self.store.get('conversation',self.conv['id'])['customer_result_history'];t=self.offer({'material':'retain','customer':'transfer'})
  self.ops.handoff(t['id'],'b','accept','已逐项核对',t['revision'],self.ws['id']);c=self.store.get('conversation',self.conv['id']);self.assertEqual(c['owner'],'b');self.assertEqual(followup_state(c)['owner'],'b');self.assertEqual(self.store.get('material',m['id'])['owner'],'a');self.assertEqual(before,c['customer_result_history']);self.assertEqual(len(self.store.get('ticket',t['id'])['handoff']['applied_tasks']),2)
 def test_stale_handoff_rejected_without_partial_transfer(self):
  m=self.material();self.outcome();t=self.offer({});m['revision']+=1;self.store.put('material',m)
  with self.assertRaises(ValueError):self.ops.handoff(t['id'],'b','accept','核对',t['revision'],self.ws['id'])
  self.assertEqual(self.store.get('ticket',t['id'])['owner'],'a');self.assertEqual(followup_state(self.store.get('conversation',self.conv['id']))['owner'],'a')
  self.ops.handoff(t['id'],'b','return','清单变化',t['revision'],self.ws['id'])
 def test_three_responsibilities_read_live_owners(self):
  m=self.material();self.outcome();t=self.offer({'material':'transfer','customer':'retain'});self.ops.handoff(t['id'],'b','accept','核对',t['revision'],self.ws['id'])
  body,links=responsibility_reference(self.store,self.conv);self.assertIn('1. 工单责任',body);self.assertIn('材料：b',body);self.assertIn('3. 客户回访责任：a',body);self.assertNotIn('时间线',body);self.assertEqual(len(links),3)
 def draft(self):return ReplyRequests(self.store).manual(self.conv,'a','manual-1','我们正在核对商品情况，尚未确认退款方案。')
 def test_translation_uses_saved_body_is_separate_and_idempotent(self):
  m=self.draft();calls=[]
  async def translate(body,lang):calls.append((body,lang));return 'Estamos verificando o produto; o reembolso ainda não foi confirmado.'
  async def run():
   a=await create(self.store,self.conv['id'],'a',self.ws['id'],m['id'],'pt-BR',1,'r1',translate);b=await create(self.store,self.conv['id'],'a',self.ws['id'],m['id'],'pt-BR',1,'r1',translate);return a,b
  a,b=asyncio.run(run());self.assertEqual(a['id'],b['id']);self.assertNotEqual(a['id'],m['id']);self.assertEqual(a['translation_source_content'],m['content']);self.assertEqual(source(self.store,self.conv['id'],m['id'])['content'],m['content']);self.assertEqual(len(calls),1)
 def test_translation_stale_source_rejects_adoption_and_wrong_scope(self):
  m=self.draft()
  async def translate(body,lang):return 'Texto'
  a=asyncio.run(create(self.store,self.conv['id'],'a',self.ws['id'],m['id'],'pt-BR',1,'r1',translate))
  self.store.update_draft(self.conv['id'],m['id'],'a','已更新原稿',1,workspace_id=self.ws['id'])
  r=self.client.patch('/conversations/'+self.conv['id']+'/drafts/'+a['id'],json={**self.scope,'content':a['content'],'revision':1,'adopt':True});self.assertEqual(r.status_code,409)
  with self.assertRaises(KeyError):asyncio.run(create(self.store,self.conv['id'],'outsider',self.ws['id'],m['id'],'pt-BR',2,'r2',translate))
 def test_translation_detects_edit_during_generation(self):
  m=self.draft()
  async def translate(body,lang):self.store.update_draft(self.conv['id'],m['id'],'a','新稿',1,workspace_id=self.ws['id']);return 'Texto'
  with self.assertRaises(ValueError):asyncio.run(create(self.store,self.conv['id'],'a',self.ws['id'],m['id'],'pt-BR',1,'r1',translate))
  self.assertEqual(len(self.store.messages(self.conv['id'])),1)

 def test_material_transfer_and_customer_retention(self):
  m=self.material();self.outcome();t=self.offer({'material':'transfer','customer':'retain'});self.ops.handoff(t['id'],'b','accept','确认',t['revision'],self.ws['id'])
  self.assertEqual(self.store.get('material',m['id'])['owner'],'b');self.assertEqual(followup_state(self.store.get('conversation',self.conv['id']))['owner'],'a')
 def test_supervisor_candidate_cannot_bypass_task_acceptance(self):
  self.ops.member('a',self.ws['id'],'b','supervisor');self.material();t=self.offer({})
  with self.assertRaises(ValueError):self.ops.update_ticket(t['id'],'b',dict(owner='b',status='pending',note='自领绕过清单'),self.ws['id'])
  self.assertEqual(self.store.get('ticket',t['id'])['handoff']['state'],'pending')
 def test_translation_lineage_cannot_adopt_after_ancestor_edit(self):
  m=self.draft()
  async def translate(body,lang):return 'Texto '+lang
  a=asyncio.run(create(self.store,self.conv['id'],'a',self.ws['id'],m['id'],'pt-BR',1,'r1',translate));b=asyncio.run(create(self.store,self.conv['id'],'a',self.ws['id'],a['id'],'en',1,'r2',translate))
  self.store.update_draft(self.conv['id'],m['id'],'a','新原稿',1,workspace_id=self.ws['id'])
  r=self.client.patch('/conversations/'+self.conv['id']+'/drafts/'+b['id'],json={**self.scope,'content':b['content'],'revision':1,'adopt':True});self.assertEqual(r.status_code,409)
