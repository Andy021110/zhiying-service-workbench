import tempfile
import unittest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.workbench_routes import create_router
from core.workbench import WorkbenchStore
from core.operations import Operations

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=WorkbenchStore(Path(self.temp.name)/'db.sqlite');self.ops=Operations(self.store)
        self.ws=self.ops.workspace('alice','售后组');self.ops.member('alice',self.ws['id'],'bob','agent');self.ops.member('alice',self.ws['id'],'carol','agent')
        self.conv=self.store.conversation('alice');self.conv.update(workspace_id=self.ws['id']);self.store.put('conversation',self.conv);self.ticket=self.store.ticket(self.conv,'交接摘要')
        app=FastAPI();app.include_router(create_router(self.store,lambda:None,lambda:None));self.client=TestClient(app)
    def assign(self,target='bob',**changes):
        body=dict(owner=target,status='pending',note='下班交接，请核对原材料',expected_revision=self.store.get('ticket',self.ticket['id'])['revision']);body.update(changes)
        return self.ops.update_ticket(self.ticket['id'],'alice',body,self.ws['id'])
    def decide(self,actor='bob',action='accept',note='已核对原事项',revision=None):
        return self.client.post('/tickets/'+self.ticket['id']+'/handoff',json=dict(user_id=actor,workspace_id=self.ws['id'],action=action,note=note,expected_revision=revision or self.store.get('ticket',self.ticket['id'])['revision']))
    def test_assignment_keeps_current_owner_until_acceptance(self):
        ticket=self.assign();self.assertEqual(ticket['owner'],'alice');self.assertEqual(ticket['handoff']['candidate'],'bob');self.assertEqual(ticket['handoff']['state'],'pending')
        self.assertEqual(self.store.get('conversation',self.conv['id'])['owner'],'alice')
        q=self.ops.queue('bob',self.ws['id'])['items'][0];self.assertTrue(q['awaiting_me']);self.assertFalse(q['assigned_to_me'])
        report=self.ops.report('alice',self.ws['id']);self.assertEqual(report['awaiting_acceptance'],1)
        accepted=self.decide().json();self.assertEqual(accepted['owner'],'bob');self.assertEqual(accepted['handoff']['state'],'accepted');self.assertEqual(accepted['status'],'in_progress')
        self.assertEqual(self.store.get('conversation',self.conv['id'])['owner'],'bob')
    def test_return_keeps_original_responsibility_and_reason(self):
        self.assign();returned=self.decide(action='return',note='材料缺少商品编号，请补齐').json()
        self.assertEqual(returned['owner'],'alice');self.assertEqual(returned['handoff']['state'],'returned');self.assertIn('商品编号',returned['history'][-1]['action'])
        self.assertFalse(self.ops.queue('bob',self.ws['id'])['items'][0]['awaiting_me']);self.assertTrue(self.ops.queue('alice',self.ws['id'])['items'][0]['handoff_returned'])
        resent=self.assign();self.assertEqual(resent['handoff']['state'],'pending');self.assertEqual(self.decide().status_code,200)
    def test_only_candidate_can_decide_and_return_requires_reason(self):
        self.assign();self.assertEqual(self.decide(actor='alice').status_code,409);self.assertEqual(self.decide(actor='carol').status_code,409)
        self.assertEqual(self.decide(action='return',note=' ').status_code,422);self.assertEqual(self.decide(actor='outsider').status_code,404)
    def test_stale_double_confirmation_rejected(self):
        ticket=self.assign();revision=ticket['revision'];self.assertEqual(self.decide(revision=revision).status_code,200);self.assertEqual(self.decide(revision=revision).status_code,409)
        self.assertEqual(sum('接受交接' in h['action'] for h in self.store.get('ticket',self.ticket['id'])['history']),1)
    def test_pending_handoff_cannot_close_or_be_bypassed_through_case(self):
        self.assign()
        with self.assertRaises(ValueError):self.ops.update_ticket(self.ticket['id'],'alice',dict(owner='alice',status='resolved',note='试图提前关闭'),self.ws['id'])
        with self.assertRaises(ValueError):self.ops.patch_conversation(self.conv['id'],'alice',dict(owner='bob'),self.ws['id'])
        with self.assertRaises(ValueError):self.ops.update_ticket(self.ticket['id'],'bob',dict(owner='bob',status='in_progress',note='绕过接受'),self.ws['id'])
    def test_shared_case_without_ticket_cannot_bypass_handoff(self):
        case=self.store.conversation('alice');case['workspace_id']=self.ws['id'];self.store.put('conversation',case)
        with self.assertRaises(ValueError):self.ops.patch_conversation(case['id'],'alice',dict(owner='bob'),self.ws['id'])
        self.assertEqual(self.store.get('conversation',case['id'])['owner'],'待分派')
    def test_other_member_cannot_reassign_responsibility_after_accept(self):
        self.assign();self.decide()
        with self.assertRaises(ValueError):self.ops.update_ticket(self.ticket['id'],'carol',dict(owner='carol',status='pending',note='抢占'),self.ws['id'])
    def test_acceptance_keeps_deadline_and_next_action(self):
        self.assign(due_at='2026-10-25T09:00:00+08:00',next_action='核对后回访')
        accepted=self.decide().json();self.assertEqual(accepted['next_action'],'核对后回访');self.assertTrue(accepted['due_at'])
    def test_personal_assignment_stays_local_without_team_handoff(self):
        conv=self.store.conversation('alice');ticket=self.store.ticket(conv,'个人事项')
        changed=self.ops.update_ticket(ticket['id'],'alice',dict(owner='个人负责人',status='pending',note='本地记录'))
        self.assertEqual(changed['owner'],'个人负责人');self.assertNotIn('handoff',changed)
    def test_self_claim_is_explicit_and_does_not_wait_for_itself(self):
        claimed=self.assign(target='alice');self.assertEqual(claimed['owner'],'alice');self.assertEqual(claimed['handoff']['state'],'accepted')
    def test_owner_can_offer_new_handoff_after_acceptance(self):
        self.assign();self.decide();ticket=self.ops.update_ticket(self.ticket['id'],'bob',dict(owner='carol',status='pending',note='下一班交接'),self.ws['id'])
        self.assertEqual(ticket['owner'],'bob');self.assertEqual(ticket['handoff']['candidate'],'carol');self.assertEqual(self.decide(actor='carol').json()['owner'],'carol')
