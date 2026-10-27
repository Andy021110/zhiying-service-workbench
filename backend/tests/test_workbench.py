import asyncio
import tempfile
import unittest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.workbench import WorkbenchStore
from api.workbench_routes import create_router
from api.main import _should_use_knowledge


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'db.sqlite'
        self.store = WorkbenchStore(self.path)
    def tearDown(self):
        self.temp.cleanup()
    def test_full_history_survives_new_store(self):
        c = self.store.conversation('alice')
        for i in range(30):
            self.store.append(c['id'], 'user', f'持久化消息{i}')
        self.assertEqual(len(WorkbenchStore(self.path).messages(c['id'])), 30)
    def test_conversations_do_not_share_context(self):
        a, b = self.store.conversation('alice'), self.store.conversation('alice')
        self.store.append(a['id'], 'user', 'A私有上下文')
        self.assertEqual(self.store.messages(b['id']), [])
    def test_ticket_creation_is_idempotent_for_open_case(self):
        c = self.store.conversation('alice')
        a = self.store.ticket(c, '真实摘要')
        b = self.store.ticket(c, '重复点击')
        self.assertEqual(a['id'], b['id'])
        self.assertEqual(len(self.store.list('ticket')), 1)


class RoutesTests(StoreTests):
    def setUp(self):
        super().setUp()
        app = FastAPI(); app.include_router(create_router(self.store, lambda:None, lambda:None))
        self.client = TestClient(app)
        self.conv = self.store.conversation('alice')
    def test_other_user_cannot_read_or_patch_conversation(self):
        id = self.conv['id']
        self.assertEqual(self.client.get(f'/conversations/{id}?user_id=bob').status_code,404)
        self.assertEqual(self.client.patch(f'/conversations/{id}',json={'user_id':'bob','status':'resolved'}).status_code,404)
    def test_unknown_order_cannot_be_linked(self):
        r = self.client.patch('/conversations/'+self.conv['id'],json={'user_id':'alice','order_id':'missing'})
        self.assertEqual(r.status_code,404)
    def test_ticket_status_owner_and_audit_survive_reload(self):
        t=self.client.post('/tickets',json={'user_id':'alice','conv_id':self.conv['id']}).json()
        r=self.client.patch('/tickets/'+t['id'],json={'user_id':'alice','owner':'客服林','status':'resolved','note':'人工核对完成；本地记录，未退款','closure_plan':dict(kind='no_followup',note='隔离测试样本，仅内部验证，无需客户回访',expected_result_revision=0,expected_plan_revision=0)})
        self.assertEqual(r.status_code,200)
        restored=WorkbenchStore(self.path).get('ticket',t['id'])
        self.assertEqual(restored['status'],'resolved')
        self.assertEqual(restored['owner'],'客服林')
        self.assertEqual(len(restored['history']),2)
        self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'resolved')
    def test_invalid_status_or_empty_note_rejected(self):
        t=self.store.ticket(self.conv,'摘要')
        for changes in [{'status':'refunded','note':'核对'},{'status':'resolved','note':' '}]:
            self.assertEqual(self.client.patch('/tickets/'+t['id'],json={'user_id':'alice','owner':'客服',**changes}).status_code,422)
    def test_feedback_case_keeps_order_and_original_text(self):
        self.store.put('review',dict(id='review',order_id='order',score=1,content='Não recebi o produto'))
        first=self.client.post('/feedback/review/case',json={'user_id':'alice'}).json()
        second=self.client.post('/feedback/review/case',json={'user_id':'alice'}).json()
        self.assertEqual(first['conversation']['id'],second['conversation']['id'])
        self.assertEqual(first['ticket']['order_id'],'order')
        self.assertEqual(self.store.messages(first['conversation']['id'])[0]['content'],'Não recebi o produto')


class RoutingRegression(unittest.TestCase):
    def test_membership_with_other_intent_still_retrieves(self):
        self.assertTrue(_should_use_knowledge('会员权益有哪些？', 'other'))
    def test_unknown_policy_and_escalation_do_not_skip_retrieval(self):
        self.assertTrue(_should_use_knowledge('月球配送的赔付标准？','other'))
        self.assertTrue(_should_use_knowledge('我要退款并转人工','escalation'))
    def test_greetings_do_not_retrieve(self):
        self.assertFalse(_should_use_knowledge('你好','greeting'))
