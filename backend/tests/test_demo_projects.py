# -*- coding: utf-8 -*-
import tempfile,unittest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.workbench import WorkbenchStore
from core.demo_cases import DemoCases
from core.demo_projects import DemoProjects,project_id
from core.operations import Operations
from core.service_followup import Followups
from api.demo_routes import create_demo_router

class DemoProjectTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=WorkbenchStore(Path(self.tmp.name)/'db.sqlite');self.demo=DemoCases(self.store);self.catalog=self.demo.ensure('alice');self.ws=self.catalog['workspace_id'];self.projects=DemoProjects(self.store)
  app=FastAPI();app.include_router(create_demo_router(self.store));self.client=TestClient(app)
 def view(self):return self.projects.get('alice',self.ws)
 def case(self,key):return self.store.get('conversation',next(c['conv_id'] for c in self.catalog['cases'] if c['id']==key))
 def pending(self):return next(a for a in self.view()['approvals'] if a['status']=='pending')
 def decision(self,a,action,**extra):return dict(action=action,note='人工核对示例计划和所列依据',expected_revision=a['revision'],expected_context_hash=a['context_hash'],**extra)
 def test_complete_project_is_idempotent_and_persisted(self):
  before=self.view();self.demo.ensure('alice');after=DemoProjects(WorkbenchStore(self.store.path)).get('alice',self.ws)
  self.assertEqual(before,after);self.assertEqual((after['completed'],after['total']),(9,12));self.assertEqual(after['approval_pending'],1);self.assertEqual(after['approval_approved'],1)
  self.assertEqual({s['kind'] for s in after['sources']},{'customer','order','material','attachment','policy','gap','recheck'})
  self.assertTrue(any(t['kind']=='approval' for t in after['todos']));self.assertTrue(any(e['kind']=='recheck' for e in after['events']))
 def test_upgrade_existing_cases_does_not_replace_work(self):
  c=self.case('missing');self.store.append(c['id'],'user','补充的原始客户说明')
  with self.store.connect() as db:db.execute("DELETE FROM records WHERE kind IN ('demo_project','demo_approval')")
  self.demo.ensure('alice');self.assertEqual(self.case('missing')['id'],c['id']);self.assertEqual(len(self.store.messages(c['id'])),7);self.assertEqual(len(self.view()['approvals']),2)
 def test_sources_are_original_records_and_attachment_bytes_survive(self):
  for s in self.view()['sources']:
   detail=self.projects.source('alice',self.ws,s['id']);self.assertEqual(detail['conv_id'],s['conv_id']);self.assertTrue(detail['is_demo'])
   if s['kind']=='customer':self.assertEqual(detail['data']['content'],self.store.messages(s['conv_id'])[0]['content'])
   if s['kind']=='attachment':self.assertTrue(Followups(self.store).attachment(detail['data']['id'],'alice',self.ws)[1].startswith(b'\x89PNG'))
  policy=next(s for s in self.view()['sources'] if s['kind']=='policy' and s['version']==2);self.assertIn('content',self.projects.source('alice',self.ws,policy['id'])['data'])
 def test_return_resubmit_approve_keeps_history_and_does_not_finish_business(self):
  before=self.case('missing');mats=self.store.list('material');a=self.pending()
  self.projects.decide('alice',self.ws,a['id'],self.decision(a,'return'));a=next(a for a in self.view()['approvals'] if a['id']==a['id'] and a['status']=='returned')
  self.projects.decide('alice',self.ws,a['id'],self.decision(a,'resubmit',plan='补充计划：继续收集数量说明，并回访客户。'));a=self.pending()
  self.projects.decide('alice',self.ws,a['id'],self.decision(a,'approve'));approved=next(x for x in self.view()['approvals'] if x['id']==a['id'])
  self.assertEqual([h['action'] for h in approved['history']],['submit','return','resubmit','approve']);self.assertEqual(approved['revision'],4)
  self.assertEqual(approved['plan'],'补充计划：继续收集数量说明，并回访客户。');self.assertFalse(approved['source_changed'])
  self.assertEqual(before,self.case('missing'));self.assertEqual(mats,self.store.list('material'));self.assertEqual(self.view()['completed'],9);self.assertEqual(self.view()['status'],'in_progress')
  self.assertTrue(any(t['kind']=='customer' for t in self.view()['todos']));self.assertEqual(self.store.list('document'),[]);self.assertEqual(self.store.list('order'),[])
 def test_stale_revision_cannot_duplicate_decision(self):
  a=self.pending();body=self.decision(a,'return');self.projects.decide('alice',self.ws,a['id'],body)
  with self.assertRaisesRegex(ValueError,'方案已被更新'):self.projects.decide('alice',self.ws,a['id'],body)
  updated=next(x for x in self.view()['approvals'] if x['id']==a['id']);self.assertEqual(len(updated['history']),2)
 def test_source_change_requires_refresh_and_captures_current_snapshot(self):
  a=self.pending();m=next(m for m in self.store.list('material') if m['conv_id']==a['conv_id'] and m['status']=='missing');m.update(status='received',revision=m['revision']+1);self.store.put('material',m)
  with self.assertRaisesRegex(ValueError,'关联材料或规则已更新'):self.projects.decide('alice',self.ws,a['id'],self.decision(a,'approve'))
  fresh=self.pending();self.assertNotEqual(fresh['context_hash'],a['context_hash']);self.assertTrue(fresh['source_changed'])
  self.projects.decide('alice',self.ws,a['id'],self.decision(fresh,'approve'));approved=next(x for x in self.view()['approvals'] if x['id']==a['id']);snapshot=next(s for s in approved['decision_sources'] if s['id']=='material:'+m['id']);self.assertIn('待核验',snapshot['summary'])
 def test_new_round_preserves_old_approval_and_sources_but_is_read_only(self):
  old=self.pending();old_conv=self.case('missing');self.store.append(old_conv['id'],'user','保留旧轮对话')
  self.demo.reset('alice','missing',1);view=self.view();self.assertEqual(len(view['approvals']),2);self.assertEqual(len(view['past_approvals']),1);past=view['past_approvals'][0]
  self.assertEqual(past['id'],old['id']);self.assertTrue(past['historical']);self.assertEqual(len(past['history']),1)
  self.assertEqual(len(self.store.messages(old_conv['id'])),7);self.assertTrue(self.projects.source('alice',self.ws,past['source_ids'][0]))
  with self.assertRaisesRegex(ValueError,'以前轮次'):self.projects.decide('alice',self.ws,old['id'],self.decision(past,'approve'))
 def test_scope_and_approver_are_enforced(self):
  other=self.demo.ensure('eve');normal=Operations(self.store).workspace('alice','普通项目空间');a=self.pending()
  for actor,ws in [('eve',self.ws),('alice',other['workspace_id']),('alice',normal['id'])]:
   with self.assertRaises(KeyError):self.projects.get(actor,ws)
  with self.assertRaises(KeyError):self.projects.source('alice',other['workspace_id'],a['source_ids'][0])
  self.assertTrue(self.projects.get('示例·上一班客服',self.ws))
  with self.assertRaisesRegex(ValueError,'示例主管'):self.projects.decide('示例·上一班客服',self.ws,a['id'],self.decision(a,'approve'))
  self.store.put('document',dict(id='formal-rule',content='正式规则'))
  with self.assertRaises(KeyError):self.projects.source('alice',self.ws,'policy:formal-rule')
  c=self.store.conversation('alice')
  with self.assertRaises(KeyError):self.projects.source('alice',self.ws,'customer:'+c['id'])
 def test_checkpoints_and_todos_reflect_underlying_records(self):
  c=self.case('missing');before=self.view();m=next(m for m in self.store.list('material') if m['conv_id']==c['id'] and m['status']=='missing');m['status']='verified';self.store.put('material',m)
  after=self.view();self.assertEqual(after['completed'],before['completed']+1);self.assertFalse(any(t['id']=='material:'+m['id'] for t in after['todos']))
  self.assertTrue(any(t['id']=='customer:'+c['id'] for t in after['todos']))
 def test_api_validates_input_and_exposes_readable_conflicts(self):
  a=self.pending();params=dict(user_id='alice',workspace_id=self.ws);url='/demos/project/approvals/'+a['id']+'/decision';body=dict(params,**self.decision(a,'approve'))
  self.assertEqual(self.client.get('/demos/project',params=params).status_code,200);self.assertEqual(self.client.get('/demos/project',params=dict(params,user_id='eve')).status_code,404)
  self.assertEqual(self.client.post(url,json=dict(body,note='  ')).status_code,422);self.assertEqual(self.client.post(url,json=dict(body,action='execute_refund')).status_code,422)
  self.assertEqual(self.client.post(url,json=body).status_code,200);retry=self.client.post(url,json=body);self.assertEqual(retry.status_code,409);self.assertIn('方案已被更新',retry.json()['detail'])
