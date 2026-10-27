"""Business regression for customer confirmation across handling rounds."""
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from core.workbench import WorkbenchStore, now
from core.operations import Operations
from core.service_followup import Followups
from core.closure_plans import has_current_confirmation, followup_state

class ReopenConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=WorkbenchStore(Path(self.tmp.name)/'db.sqlite');self.ops=Operations(self.store);self.follow=Followups(self.store)
        self.conv=self.store.conversation('alice');self.ticket=self.ops.ticket(self.conv,'验收')
    def current(self):return self.store.get('conversation',self.conv['id'])
    def confirm(self,revision=None):
        return self.follow.customer_result(self.conv['id'],'alice',dict(status='confirmed',occurred_at=now(),note='人工记录本轮客户反馈',expected_revision=self.current().get('result_revision',0) if revision is None else revision))
    def plan(self,kind='confirmed'):
        c=self.current();return dict(kind=kind,note='测试内部安排',expected_result_revision=c.get('result_revision',0),expected_plan_revision=(c.get('closure_plan') or {}).get('revision',0))
    def close(self,plan=None):
        return self.ops.update_ticket(self.ticket['id'],'alice',dict(owner='alice',status='resolved',note='核对完成',closure_plan=plan))
    def reopen(self):return self.ops.update_ticket(self.ticket['id'],'alice',dict(owner='alice',status='pending',note='客户再次反馈未解决'),reopen=True)
    def test_reopen_preserves_history_but_requires_new_round_confirmation(self):
        original=self.confirm();self.close(self.plan());self.reopen();c=self.current()
        self.assertEqual(c['status'],'pending');self.assertTrue(c['customer_confirmation_required'])
        self.assertEqual(c['customer_result']['status'],'pending');self.assertEqual(c['customer_result']['source'],'case_reopen')
        self.assertIn(original,c['customer_result_history']);self.assertFalse(c['closure_plan']['active']);self.assertFalse(has_current_confirmation(c))
        self.assertEqual(followup_state(c)['owner'],'alice');self.assertEqual(self.follow.bundle(c['id'],'alice')['customer_confirmation_required'],True)
    def test_stale_plan_and_fresh_plan_cannot_reuse_old_confirmation(self):
        self.confirm();self.close(self.plan());old_plan=self.plan();self.reopen()
        for plan in [old_plan,self.plan(),None]:
            with self.assertRaises(ValueError):self.close(plan)
        self.assertEqual(self.store.get('ticket',self.ticket['id'])['status'],'pending')
        self.assertTrue(self.follow.readiness(self.conv['id'],'alice',ticket_id=self.ticket['id'])['requires_exception'])
    def test_old_result_form_conflicts_and_new_confirmation_allows_closure(self):
        self.confirm();self.close(self.plan());stale=self.current()['result_revision'];self.reopen()
        with self.assertRaises(ValueError):self.confirm(stale)
        saved=self.confirm();self.assertEqual(saved['service_round'],1);self.assertTrue(has_current_confirmation(self.current()))
        self.close(self.plan());self.assertEqual(self.current()['status'],'resolved')
    def test_internal_closure_remains_possible_without_inventing_confirmation(self):
        self.confirm();self.close(self.plan());self.reopen();self.close(self.plan('no_followup'))
        self.assertEqual(self.current()['customer_result']['status'],'pending');self.assertFalse(has_current_confirmation(self.current()))
        self.assertEqual(self.current()['closure_plan']['kind'],'no_followup')
    def test_reopening_without_ticket_invalidates_confirmation_too(self):
        c=self.store.conversation('alice');self.conv=c;self.confirm()
        self.ops.patch_conversation(c['id'],'alice',dict(status='resolved',resolution='完成',closure_plan=self.plan()))
        self.ops.patch_conversation(c['id'],'alice',dict(status='open'))
        self.assertTrue(self.current()['customer_confirmation_required']);self.assertNotIn('resolved_at',self.current())
        with self.assertRaises(ValueError):self.ops.patch_conversation(c['id'],'alice',dict(status='resolved',resolution='不能复用',closure_plan=self.plan()))
    def test_reopening_preserves_existing_pending_followup_responsibility(self):
        due=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
        self.follow.customer_result(self.conv['id'],'alice',dict(status='disputed',occurred_at=now(),note='客户不认可',owner='alice',next_action='原定回访',due_at=due,expected_revision=0))
        self.close(self.plan('no_followup'));self.reopen();r=followup_state(self.current())
        self.assertEqual((r['status'],r['next_action'],r['due_at']),('disputed','原定回访',due))
