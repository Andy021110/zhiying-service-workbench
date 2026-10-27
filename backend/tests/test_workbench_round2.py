import tempfile
import threading
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.workbench import WorkbenchStore
from core.conversation_context import build_memory, model_history, resolve_followup, recall_customer_fact
from core.knowledge_policy import eligible_version
from api.workbench_routes import create_router
from mcp.knowledge_base import KnowledgeBase
from test_knowledge_lifecycle import FakeCollection


class Round2Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=WorkbenchStore(Path(self.temp.name)/'db.sqlite')
        self.kb=KnowledgeBase.__new__(KnowledgeBase);self.kb.store=self.store;self.kb._collection=FakeCollection();self.kb._document_lock=threading.RLock()
        app=FastAPI();app.include_router(create_router(self.store,lambda:self.kb,lambda:None));self.client=TestClient(app)
        self.conv=self.store.conversation('alice')
    def draft(self,**metadata):
        return self.store.append(self.conv['id'],'assistant','初稿',kind='reply_draft',review_state='draft',revision=1,knowledge_mode='test',**metadata)
    def patch_draft(self,msg,**changes):
        return self.client.patch(f"/conversations/{self.conv['id']}/drafts/{msg['id']}",json=dict(user_id='alice',content='人工核对后的回复',revision=1,**changes))
    def approve(self,doc):
        self.kb.review_document(doc['id'],'submit',doc['version'],'alice','提交本地验收')
        return self.kb.review_document(doc['id'],'approve',doc['version'],'reviewer','已核对测试文本')


class DraftWorkflowTests(Round2Fixture):
    def test_edits_and_adoption_preserve_original_and_audit(self):
        msg=self.draft();r=self.patch_draft(msg);self.assertEqual(r.status_code,200)
        edited=r.json();self.assertEqual(edited['original_content'],'初稿');self.assertEqual(edited['revision'],2)
        r=self.client.patch(f"/conversations/{self.conv['id']}/drafts/{msg['id']}",json=dict(user_id='alice',content=edited['content'],revision=2,adopt=True))
        self.assertEqual(r.status_code,200);adopted=r.json()
        self.assertEqual(adopted['review_state'],'adopted');self.assertEqual(adopted['delivery_status'],'local_only');self.assertEqual(len(adopted['draft_history']),2)
        restored=WorkbenchStore(self.store.path).messages(self.conv['id'])[0]
        self.assertEqual(restored['content'],'人工核对后的回复');self.assertEqual(restored['original_content'],'初稿')
    def test_revision_conflict_and_adopted_reply_are_not_overwritten(self):
        msg=self.draft();self.assertEqual(self.patch_draft(msg,adopt=True).status_code,200)
        self.assertEqual(self.patch_draft(msg).status_code,409)
    def test_other_user_cannot_edit_or_add_note(self):
        msg=self.draft()
        self.assertEqual(self.client.patch(f"/conversations/{self.conv['id']}/drafts/{msg['id']}",json=dict(user_id='bob',content='改写',revision=1)).status_code,404)
        self.assertEqual(self.client.post(f"/conversations/{self.conv['id']}/notes",json=dict(user_id='bob',content='私密')).status_code,404)
    def test_internal_notes_dont_replace_queue_preview_or_enter_memory(self):
        self.store.append(self.conv['id'],'user','客户问题')
        r=self.client.post(f"/conversations/{self.conv['id']}/notes",json=dict(user_id='alice',content='内部凭据 PRIVATE-NOTE-42'))
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['role'],'note')
        self.assertEqual(self.store.get('conversation',self.conv['id'])['preview'],'客户问题')
        self.assertNotIn('PRIVATE-NOTE-42',str(build_memory(self.store,self.conv['id'])))
        self.assertNotIn('PRIVATE-NOTE-42',str(model_history(self.store,self.conv['id'],'test')))
    def test_drafts_only_enter_model_history_after_adoption(self):
        msg=self.draft();self.assertEqual(model_history(self.store,self.conv['id'],'test'),[])
        self.patch_draft(msg,adopt=True)
        self.assertIn('人工核对后的回复',str(model_history(self.store,self.conv['id'],'test')))
    def test_adoption_rejects_stale_source_or_mode_change(self):
        doc=self.kb.save_document('测试政策','旧版政策',scope='test')
        msg=self.draft(sources=[dict(document_id=doc['id'],version=1)])
        self.kb.save_document('测试政策','新版政策',doc['id'],'测试',1)
        self.assertEqual(self.patch_draft(msg,adopt=True).status_code,409)
        other=self.draft();conv=self.store.get('conversation',self.conv['id']);conv['knowledge_mode']='business';self.store.put('conversation',conv)
        self.assertEqual(self.patch_draft(other,adopt=True).status_code,409)
    def test_empty_note_and_draft_rejected(self):
        msg=self.draft()
        self.assertEqual(self.client.post(f"/conversations/{self.conv['id']}/notes",json=dict(user_id='alice',content=' ')).status_code,422)
        self.assertEqual(self.client.patch(f"/conversations/{self.conv['id']}/drafts/{msg['id']}",json=dict(user_id='alice',content=' ',revision=1)).status_code,422)
    def test_concurrent_updates_have_one_winner(self):
        msg=self.draft()
        def edit(text):
            try:self.store.update_draft(self.conv['id'],msg['id'],'alice',text,1);return 'ok'
            except ValueError:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(edit,['一','二']))
        self.assertEqual(sorted(results),['conflict','ok'])


class GovernanceTests(Round2Fixture):
    def test_draft_business_and_test_examples_are_not_business_sources(self):
        self.kb.save_document('业务规则','42天',scope='business')
        self.kb.save_document('示例规则','99天',scope='test')
        self.assertEqual(self.kb.search('规则',mode='business'),[])
        self.assertEqual(len(self.kb.search('规则',mode='test')),2)
    def test_only_approved_business_version_is_effective(self):
        doc=self.kb.save_document('业务规则','42天',scope='business');self.approve(doc)
        self.assertEqual(self.kb.search('规则',mode='business')[0]['version'],1)
        self.kb.save_document('业务规则','84天',doc['id'],'本地验收',1)
        self.assertEqual(self.kb.search('规则',mode='business')[0]['content'],'42天')
        self.assertEqual(self.kb.search('规则',mode='test')[0]['content'],'84天')
        self.approve(self.store.get('document',doc['id']))
        self.assertEqual(self.kb.search('规则',mode='business')[0]['version'],2)
        self.assertEqual(len(self.kb._collection.rows),1)
    def test_test_approval_does_not_grant_business_visibility(self):
        doc=self.kb.save_document('测试规则','仅测试',scope='test');self.approve(doc)
        self.assertEqual(self.kb.search('规则',mode='business'),[])
    def test_review_requires_pending_and_current_version(self):
        doc=self.kb.save_document('业务规则','42天',scope='business')
        body=dict(actor='alice',action='approve',version=1,note='核对')
        self.assertEqual(self.client.post(f"/knowledge/documents/{doc['id']}/review",json=body).status_code,409)
        body.update(action='submit',note=' ')
        self.assertEqual(self.client.post(f"/knowledge/documents/{doc['id']}/review",json=body).status_code,422)
        self.kb.save_document('业务规则','84天',doc['id'],'本地',1)
        body.update(note='提交旧版')
        self.assertEqual(self.client.post(f"/knowledge/documents/{doc['id']}/review",json=body).status_code,409)
    def test_rejection_keeps_previous_published_version(self):
        doc=self.kb.save_document('业务规则','42天',scope='business');self.approve(doc)
        self.kb.save_document('业务规则','84天',doc['id'],'本地',1)
        self.kb.review_document(doc['id'],'submit',2,'alice','提交')
        rejected=self.kb.review_document(doc['id'],'reject',2,'reviewer','需要修订')
        self.assertEqual(rejected['review_status'],'draft');self.assertEqual(self.kb.search('规则',mode='business')[0]['version'],1)
    def test_archive_with_pending_draft_withdraws_published_version(self):
        doc=self.kb.save_document('业务规则','42天',scope='business');self.approve(doc)
        self.kb.save_document('业务规则','84天',doc['id'],'本地',1)
        self.kb.archive_document(doc['id']);self.assertEqual(self.kb.search('规则',mode='business'),[])
        restored=self.kb.restore_document(doc['id']);self.assertEqual(restored['review_status'],'draft');self.assertFalse(restored['published_version'])
        self.assertEqual(self.kb.search('规则',mode='business'),[])
    def test_stale_adopted_reply_is_removed_from_future_context(self):
        doc=self.kb.save_document('测试规则','42天',scope='test')
        msg=self.draft(sources=[dict(document_id=doc['id'],version=1)]);self.patch_draft(msg,adopt=True)
        self.kb.archive_document(doc['id'])
        self.assertEqual(model_history(self.store,self.conv['id'],'test'),[])


class MemoryTests(Round2Fixture):
    def test_long_conversation_keeps_customer_fact_and_survives_restart(self):
        original=self.store.append(self.conv['id'],'user','我叫小林。我的订单号是QA-ORDER-42。我的诉求是先查物流再决定是否退款。')
        for i in range(30):self.store.append(self.conv['id'],'user',f'补充描述{i}：请记录处理进度。')
        self.store.append(self.conv['id'],'note','内部秘密 N-PRIVATE-99')
        self.draft()
        memory=build_memory(self.store,self.conv['id'])
        self.assertEqual(memory['facts']['order_id']['value'],'QA-ORDER-42');self.assertEqual(memory['facts']['order_id']['message_id'],original['id'])
        self.assertNotIn('N-PRIVATE-99',str(memory));self.assertNotIn('初稿',str(memory))
        restarted=WorkbenchStore(self.store.path).get('conversation_memory',self.conv['id'])
        self.assertEqual(restarted['facts']['name']['value'],'小林')
        self.assertIn('QA-ORDER-42',recall_customer_fact('我之前提供过的订单号是什么？',restarted)['response'])
    def test_customer_correction_replaces_old_fact_with_provenance(self):
        self.store.append(self.conv['id'],'user','我的订单号是OLD-42')
        latest=self.store.append(self.conv['id'],'user','订单号更正为NEW-84')
        fact=build_memory(self.store,self.conv['id'])['facts']['order_id']
        self.assertEqual(fact['value'],'NEW-84');self.assertEqual(fact['message_id'],latest['id'])
    def test_new_conversation_never_recalls_other_conversation(self):
        self.store.append(self.conv['id'],'user','我的订单号是ONLY-A-42')
        other=self.store.conversation('alice');memory=build_memory(self.store,other['id'])
        self.assertEqual(memory['facts'],{});self.assertNotIn('ONLY-A-42',str(memory))
        self.assertIn('尚未记录',recall_customer_fact('我的订单号是什么？',memory)['response'])
    def test_followup_adds_customer_topic_but_never_notes_or_draft(self):
        messages=[dict(role='user',content='金卡会员有哪些积分权益？'),dict(role='note',content='PRIVATE'),dict(role='assistant',content='假造的政策')]
        query=resolve_followup('那银卡呢？',messages)
        self.assertIn('金卡会员',query);self.assertNotIn('PRIVATE',query);self.assertNotIn('假造',query)
    def test_policy_question_is_not_customer_fact_recall(self):
        memory=build_memory(self.store,self.conv['id'])
        self.assertIsNone(recall_customer_fact('会员退款政策是什么？',memory))
