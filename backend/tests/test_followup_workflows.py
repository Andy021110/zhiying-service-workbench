# -*- coding: utf-8 -*-
import base64,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.workbench import WorkbenchStore
from core.operations import Operations
from core.service_followup import Followups,MAX_FILE
from api.workbench_routes import create_router

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2lX8AAAAASUVORK5CYII=')
class FollowupTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=WorkbenchStore(Path(self.tmp.name)/'db.sqlite')
  self.ops=Operations(self.store);self.service=Followups(self.store);self.ws=self.ops.workspace('alice','组');self.ops.member('alice',self.ws['id'],'bob','agent')
  self.scope=dict(user_id='alice',workspace_id=self.ws['id']);self.other={**self.scope,'user_id':'outsider'}
  self.conv=self.store.conversation('alice','测试事项');self.conv.update(workspace_id=self.ws['id'],owner='alice');self.store.put('conversation',self.conv)
  self.ticket=self.ops.ticket(self.conv,'事项');self.path='/conversations/'+self.conv['id'];self.due=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat();self.when=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
  app=FastAPI();app.include_router(create_router(self.store,lambda:None,lambda:None));self.client=TestClient(app)
 def outcome(self,**kw):
  return self.client.put(self.path+'/customer-result',json={**self.scope,'status':'pending','note':'已人工核对客户反馈','occurred_at':self.when,'owner':'alice','next_action':'继续联系','due_at':self.due,'expected_revision':0,**kw})
 def material(self,**kw):
  r=self.client.post(self.path+'/materials',json={**self.scope,'name':'缺件照片','required':True,'owner':'bob','due_at':self.due,**kw});self.assertEqual(r.status_code,200,r.text);return r.json()
 def change_material(self,m,**kw):
  return self.client.patch(self.path+'/materials/'+m['id'],json={**self.scope,**{k:m[k] for k in ['name','required','owner','due_at','status']},'note':'人工核验变更','expected_revision':m['revision'],**kw})
 def upload(self,m,**kw):
  args=dict(data={**self.scope,'material_id':m['id'],'source_note':'客服人工保存的客户照片','request_id':'upload-1'},files={'file':('原始凭证.png',PNG,'image/png')});args.update(kw)
  return self.client.post(self.path+'/attachments',**args)
 def gap(self,q='缺规则',conv=None):
  r=self.client.post('/knowledge/gaps',json={**self.scope,'conv_id':(conv or self.conv)['id'],'question':q,'owner':'alice'});self.assertEqual(r.status_code,200,r.text);return r.json()
 def edit_gap(self,g,**kw):
  return self.client.patch('/knowledge/gaps/'+g['id'],json={**self.scope,'owner':'alice','status':'pending','question':g['question'],'note':'维护说明','expected_revision':g.get('revision',1),**kw})
 def document(self,version=1,**kw):
  return self.store.put('document',dict(id='policy',title='正式规则',scope='business',published_version=version,deleted=False,**kw))
 def resolve(self,g):
  r=self.edit_gap(g,status='resolved',document_id='policy');self.assertEqual(r.status_code,200,r.text);return r.json()
 def close(self,**kw):
  return self.client.patch('/tickets/'+self.ticket['id'],json={**self.scope,'owner':'alice','status':'resolved','note':'内部事项已完成','resolution':'内部核实完成',**kw})
 def merge(self,a,b,**kw):
  return self.client.post('/knowledge/gaps/'+a['id']+'/merge',json={**self.scope,'target_id':b['id'],'note':'重复规则合并','expected_revision':a['revision'],'target_revision':b['revision'],**kw})
 def test_manual_results_are_separate_and_history_survives_reload(self):
  self.assertEqual(self.outcome(status='unreachable').status_code,200)
  self.assertEqual(self.outcome(status='confirmed',expected_revision=1).status_code,200)
  c=WorkbenchStore(self.store.path).get('conversation',self.conv['id']);self.assertEqual(c['status'],'pending');self.assertEqual(c['customer_result']['source'],'manual');self.assertEqual(len(c['customer_result_history']),2)
  self.assertEqual(c['customer_result_history'][0]['status'],'unreachable');self.assertIsNone(c['customer_result']['due_at'])
 def test_result_requires_followup_and_rejects_naive_or_future_times(self):
  self.assertEqual(self.outcome(owner='待分派').status_code,409);self.assertEqual(self.outcome(next_action='').status_code,409)
  self.assertEqual(self.outcome(due_at=None).status_code,409);self.assertEqual(self.outcome(owner='eve').status_code,409)
  self.assertEqual(self.outcome(occurred_at='2026-10-26T09:00').status_code,422)
  self.assertEqual(self.outcome(occurred_at=self.due).status_code,409)
 def test_result_conflict_and_outsider_cannot_overwrite(self):
  self.assertEqual(self.outcome().status_code,200);self.assertEqual(self.outcome(status='confirmed').status_code,409)
  self.assertEqual(self.outcome(user_id='outsider',expected_revision=1).status_code,404)
 def test_internal_closure_exception_does_not_clear_customer_followup(self):
  self.outcome();self.assertEqual(self.close().status_code,409)
  self.assertEqual(self.close(closure_exception='仅完成内部核对，约定继续联系客户').status_code,200)
  pending=self.client.get('/operations/followups',params=self.scope).json();self.assertEqual(len(pending['customer_results']),1)
  self.assertEqual(self.store.get('conversation',self.conv['id'])['customer_result']['status'],'pending')
 def test_material_required_blocks_ticket_and_case_closure_until_verified_or_waived(self):
  m=self.material();self.assertEqual(self.close().status_code,409)
  self.assertEqual(self.change_material(m,status='received').status_code,200);self.assertEqual(self.close().status_code,409)
  m=self.store.get('material',m['id']);self.assertEqual(self.change_material(m,status='waived',note='主管核实可按现有材料继续').status_code,200)
  self.assertEqual(self.close(closure_plan=dict(kind='no_followup',note='隔离测试样本，仅内部验证，无需客户回访',expected_result_revision=0,expected_plan_revision=0)).status_code,200)
 def test_case_without_ticket_also_honors_material_guard(self):
  c=self.store.conversation('alice','个人事项');body={k:v for k,v in self.scope.items() if k!='workspace_id'}
  self.client.post('/conversations/'+c['id']+'/materials',json={**body,'name':'材料','owner':'alice','due_at':self.due})
  r=self.client.patch('/conversations/'+c['id'],json={**body,'status':'resolved','resolution':'内部完成'});self.assertEqual(r.status_code,409)
 def test_material_change_requires_reason_version_and_scope(self):
  m=self.material();self.assertEqual(self.change_material(m,status='verified',note='').status_code,409)
  self.assertEqual(self.change_material(m,required=False,note='').status_code,409)
  self.assertEqual(self.change_material(m,status='verified').status_code,200)
  self.assertEqual(self.change_material(m,status='received').status_code,409)
  self.assertEqual(self.change_material(m,user_id='outsider').status_code,404)
 def test_attachment_retries_are_idempotent_and_bytes_durable(self):
  m=self.material();a=self.upload(m);self.assertEqual(a.status_code,200,a.text);a=a.json();self.assertEqual(self.upload(m).json()['id'],a['id'])
  self.assertEqual(len(self.store.list('attachment')),1);self.assertEqual(Followups(WorkbenchStore(self.store.path)).attachment(a['id'],'bob',self.ws['id'])[1],PNG)
  self.assertEqual(self.store.get('material',m['id'])['status'],'received')
 def test_upload_same_nonce_cannot_be_reused_for_another_file(self):
  m=self.material();self.upload(m)
  r=self.upload(m,files={'file':('different.png',PNG,'image/png')});self.assertEqual(r.status_code,409);self.assertEqual(len(self.store.list('attachment')),1)
 def test_attachment_download_checks_scope_and_conversation(self):
  m=self.material();a=self.upload(m).json();p=self.path+'/attachments/'+a['id']
  self.assertEqual(self.client.get(p,params=self.scope).content,PNG)
  self.assertEqual(self.client.get(p,params=self.other).status_code,404)
  self.assertEqual(self.client.get(p,params={'user_id':'alice'}).status_code,404)
  self.assertEqual(self.client.get('/conversations/wrong/attachments/'+a['id'],params=self.scope).status_code,404)
  self.assertIn('no-store',self.client.get(p,params=self.scope).headers['cache-control'])
 def test_attachment_failure_does_not_create_fake_record(self):
  m=self.material()
  for filename,content in [('fake.png',b'<html>bad</html>'),('page.html',PNG),('empty.png',b''),('too-large.png',b'x'*(MAX_FILE+1)),('bad.pdf',b'%PDF-invalid')]:
   self.assertEqual(self.upload(m,files={'file':(filename,content,'image/png')}).status_code,409)
  self.assertEqual(self.store.list('attachment'),[]);self.assertEqual(self.store.get('material',m['id'])['status'],'missing')
 def test_attachment_must_belong_to_material_in_same_case(self):
  m=self.material();c=self.store.conversation('alice','另一事项');c['workspace_id']=self.ws['id'];self.store.put('conversation',c)
  r=self.client.post('/conversations/'+c['id']+'/attachments',data={**self.scope,'material_id':m['id'],'source_note':'来源','request_id':'wrong'},files={'file':('a.png',PNG,'image/png')})
  self.assertEqual(r.status_code,404);self.assertEqual(self.store.list('attachment'),[])
 def test_new_attachment_or_archive_invalidates_previous_verification(self):
  m=self.material();m=self.change_material(m,status='verified').json();a=self.upload(m).json();self.assertEqual(self.store.get('material',m['id'])['status'],'received')
  m=self.store.get('material',m['id']);self.change_material(m,status='verified')
  r=self.client.post(self.path+'/attachments/'+a['id']+'/archive',json={**self.scope,'note':'凭证来源需重新核实','expected_revision':a['revision']})
  self.assertEqual(r.status_code,200);self.assertEqual(self.store.get('material',m['id'])['status'],'received');self.assertEqual(self.service.attachment(a['id'],'alice',self.ws['id'])[1],PNG)
 def test_gap_edit_withdraw_and_restore_preserve_original_and_report_count(self):
  g=self.gap('原问题');g=self.edit_gap(g,question='更正后问题').json();self.assertEqual(g['original_question'],'原问题');self.assertEqual(g['history'][0]['previous']['question'],'原问题')
  g=self.edit_gap(g,status='withdrawn').json();self.assertEqual(self.ops.report('alice',self.ws['id'])['knowledge_gaps'],0)
  self.assertNotEqual(self.store.get('conversation',self.conv['id'])['status'],'resolved')
  self.assertEqual(self.edit_gap(g,status='open').status_code,200)
 def test_gap_edits_reject_stale_missing_revision_and_outsider(self):
  g=self.gap();self.assertEqual(self.edit_gap(g).status_code,200);self.assertEqual(self.edit_gap(g,question='stale').status_code,409)
  self.assertEqual(self.edit_gap(g,user_id='outsider').status_code,404)
  self.assertEqual(self.client.patch('/knowledge/gaps/'+g['id'],json={**self.scope,'owner':'alice','status':'open','note':'无版本'}).status_code,422)
 def test_gap_merge_preserves_sources_and_rejects_cycles(self):
  a=self.gap('重复');b=self.gap('目标');self.assertEqual(self.merge(a,b).status_code,200)
  self.assertEqual(self.store.get('knowledge_gap',a['id'])['merged_into'],b['id']);b=self.store.get('knowledge_gap',b['id'])
  self.assertEqual(self.merge(b,self.store.get('knowledge_gap',a['id'])).status_code,409)
  self.assertEqual(self.merge(b,b).status_code,409);self.assertEqual(self.ops.report('alice',self.ws['id'])['knowledge_gaps'],1)
 def test_merge_stale_target_does_not_half_write(self):
  a=self.gap('a');b=self.gap('b');self.edit_gap(b)
  self.assertEqual(self.merge(a,b).status_code,409);self.assertEqual(self.store.get('knowledge_gap',a['id'])['status'],'open')
 def test_cross_scope_merge_is_rejected(self):
  a=self.gap('a');private=self.store.conversation('alice','private');b=self.service.create_gap('alice',private['id'],'private','alice')
  self.assertEqual(self.merge(a,b).status_code,404)
 def test_gap_resolution_rechecks_only_effective_business_rules(self):
  g=self.gap();self.assertEqual(self.edit_gap(g,status='resolved',document_id='policy').status_code,409);self.document();self.resolve(g)
  rs=self.service.rechecks('bob',self.ws['id']);self.assertEqual(len(rs),1);self.assertEqual(rs[0]['document_version'],1);self.assertTrue(rs[0]['document_current'])
  self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'pending')
 def test_recheck_refresh_is_idempotent_and_citation_links_are_explicit(self):
  self.document();g=self.resolve(self.gap());self.store.append(self.conv['id'],'assistant','业务引用',knowledge_mode='business',sources=[{'document_id':'policy','version':1}])
  for _ in range(2):self.service.refresh_rechecks('alice',self.ws['id'])
  rs=self.service.rechecks('alice',self.ws['id']);self.assertEqual(len(rs),1);self.assertEqual(len(rs[0]['references']),2)
 def test_test_mode_citations_do_not_create_business_rechecks(self):
  self.document();self.store.append(self.conv['id'],'assistant','测试引用',knowledge_mode='test',sources=[{'document_id':'policy'}]);self.service.sync_document('policy');self.assertEqual(self.store.list('knowledge_recheck'),[])
 def test_recheck_save_checks_document_revision_and_scope_without_changing_reply(self):
  self.document();self.resolve(self.gap());r=self.service.rechecks('alice',self.ws['id'])[0]
  msg=self.store.append(self.conv['id'],'assistant','已采用原稿',review_state='adopted');body={**self.scope,'status':'reviewed','note':'核对新规则，继续人工跟进','expected_revision':r['revision']}
  path='/knowledge/rechecks/'+r['id'];self.assertEqual(self.client.patch(path,json=body).status_code,200);self.assertEqual(self.client.patch(path,json=body).status_code,409)
  self.assertEqual(self.client.patch(path,json={**body,'user_id':'outsider'}).status_code,404)
  self.assertEqual(self.store.messages(self.conv['id'])[-1],msg)
 def test_new_rule_version_creates_pending_and_stale_review_is_rejected(self):
  self.document();self.resolve(self.gap());old=self.service.rechecks('alice',self.ws['id'])[0];self.document(2);self.service.sync_document('policy')
  rows=self.service.rechecks('alice',self.ws['id']);self.assertEqual(len(rows),2);self.assertEqual(sum(r['status']=='pending' for r in rows),1)
  self.assertEqual(self.client.patch('/knowledge/rechecks/'+old['id'],json={**self.scope,'status':'reviewed','note':'旧版本','expected_revision':old['revision']}).status_code,409)
 def test_archived_rule_blocks_recheck_and_refresh_scope_does_not_mutate_other_cases(self):
  self.document();self.resolve(self.gap());r=self.service.rechecks('alice',self.ws['id'])[0];doc=self.store.get('document','policy');doc['deleted']=True;self.store.put('document',doc)
  self.assertFalse(self.service.rechecks('alice',self.ws['id'])[0]['document_current'])
  with self.assertRaises(ValueError):self.service.review(r['id'],'alice','reviewed','失效规则',r['revision'],self.ws['id'])
  self.document();private=self.store.conversation('other','他人事项');g=self.service.create_gap('other',private['id'],'其他规则','other');g.update(status='resolved',document_id='policy');self.store.put('knowledge_gap',g)
  self.service.refresh_rechecks('alice',self.ws['id']);self.assertFalse(any(x['conv_id']==private['id'] for x in self.store.list('knowledge_recheck')))
 def test_merging_into_resolved_gap_adds_original_case_to_recheck(self):
  self.document();a=self.gap('a');c=self.store.conversation('alice','第二个事项');c.update(workspace_id=self.ws['id'],owner='bob');self.store.put('conversation',c);b=self.resolve(self.gap('b',c))
  self.assertEqual(self.merge(a,b).status_code,200)
  self.assertEqual({r['conv_id'] for r in self.service.rechecks('alice',self.ws['id'])},{self.conv['id'],c['id']})
 def test_concurrent_upload_retry_and_gap_intake_create_one_record(self):
  m=self.material()
  with ThreadPoolExecutor(max_workers=4) as pool:values=list(pool.map(lambda _:self.service.upload(self.conv['id'],'alice',m['id'],'a.png',PNG,'来源','nonce',self.ws['id']),range(8)))
  self.assertEqual(len({v['id'] for v in values}),1)
  with ThreadPoolExecutor(max_workers=4) as pool:gaps=list(pool.map(lambda _:self.service.create_gap('alice',self.conv['id'],'重复问题','alice',self.ws['id']),range(8)))
  self.assertEqual(len({g['id'] for g in gaps}),1)
 def test_unassigned_case_recheck_has_actionable_gap_owner(self):
  c=self.store.get('conversation',self.conv['id']);c['owner']='待分派';self.store.put('conversation',c)
  self.document();g=self.gap();g=self.edit_gap(g,owner='bob').json();self.resolve(g)
  row=self.service.rechecks('alice',self.ws['id'])[0];self.assertEqual(row['current_owner'],'alice')
  # Resolution above explicitly set owner alice; a later assignment is reflected without discarding history.
  latest=self.store.get('knowledge_gap',g['id']);self.edit_gap(latest,status='resolved',document_id='policy',owner='bob')
  self.assertEqual(self.service.rechecks('alice',self.ws['id'])[0]['current_owner'],'bob')
 def test_personal_followup_cannot_be_assigned_to_unreachable_other_identity(self):
  c=self.store.conversation('alice','个人材料');body=dict(user_id='alice',name='照片',owner='bob',due_at=self.due)
  self.assertEqual(self.client.post('/conversations/'+c['id']+'/materials',json=body).status_code,409)
  r=dict(user_id='alice',status='pending',note='人工反馈',occurred_at=self.when,owner='bob',next_action='继续联系',due_at=self.due,expected_revision=0)
  self.assertEqual(self.client.put('/conversations/'+c['id']+'/customer-result',json=r).status_code,409)
 def test_recheck_uses_published_title_when_a_new_draft_exists(self):
  self.document();doc=self.store.get('document','policy');self.store.put('document_version',dict(doc,id='policy:1',document_id='policy'))
  doc.update(version=2,title='待审新版标题',review_status='pending');self.store.put('document',doc)
  self.resolve(self.gap());r=self.service.rechecks('alice',self.ws['id'])[0]
  self.assertEqual(r['document_version'],1);self.assertEqual(r['document_title'],'正式规则')
