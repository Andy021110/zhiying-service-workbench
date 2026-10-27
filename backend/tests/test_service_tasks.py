import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.workbench import WorkbenchStore
from core.operations import Operations
from core.fact_answers import order_fact,wants_policy
from core.conversation_context import model_history
from api.workbench_routes import create_router

class ServiceTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=WorkbenchStore(Path(self.temp.name)/'db.sqlite');self.ops=Operations(self.store)
        app=FastAPI();app.include_router(create_router(self.store,lambda:None,lambda:None));self.client=TestClient(app)
        self.ws=self.ops.workspace('alice','售后组');self.ops.member('alice',self.ws['id'],'bob','agent')
        self.scope=dict(user_id='alice',workspace_id=self.ws['id'])
        self.store.put('review',dict(id='real-review',order_id='historical-order',score=1,content='Não recebi o produto',created_at='2018-03-28 00:00:00'))
        self.case=self.ops.feedback_case('alice','real-review',self.ws['id']);self.conv=self.case['conversation'];self.ticket=self.case['ticket']
    def patch(self,**fields):
        if fields.get('status')=='resolved':fields.setdefault('closure_plan',dict(kind='no_followup',note='隔离测试样本，仅内部验证，无需客户回访',expected_result_revision=0,expected_plan_revision=0))
        return self.client.patch('/tickets/'+self.ticket['id'],json={**self.scope,'owner':'alice','status':'pending','note':'本次核对已记录',**fields})
    def test_shared_case_visible_to_member_not_outsider_or_personal_scope(self):
        self.assertEqual(len(self.ops.visible('conversation','bob',self.ws['id'])),1)
        self.assertEqual(self.ops.visible('conversation','bob'),[])
        self.assertEqual(self.ops.visible('conversation','alice'),[])
        self.assertEqual(self.client.get('/conversations/'+self.conv['id'],params=dict(user_id='bob',workspace_id=self.ws['id'])).status_code,200)
        self.assertEqual(self.client.get('/conversations/'+self.conv['id'],params=dict(user_id='outsider',workspace_id=self.ws['id'])).status_code,404)
        self.assertEqual(self.client.post('/conversations',json=dict(user_id='outsider',workspace_id=self.ws['id'])).status_code,404)
    def test_personal_records_retained_when_team_space_created(self):
        private=self.store.conversation('alice','个人记录')
        self.assertIn(private,self.ops.visible('conversation','alice'))
        self.assertNotIn(private,self.ops.visible('conversation','alice',self.ws['id']))
        self.assertEqual(self.client.get('/conversations/'+private['id'],params=dict(user_id='bob',workspace_id=self.ws['id'])).status_code,404)
    def test_concurrent_team_feedback_intake_creates_exactly_one_case_and_ticket(self):
        with ThreadPoolExecutor(max_workers=6) as executor:
            results=list(executor.map(lambda i:self.ops.feedback_case('alice' if i%2 else 'bob','real-review',self.ws['id']),range(12)))
        self.assertEqual(len({r['conversation']['id'] for r in results}),1)
        self.assertEqual(len(self.store.list('ticket')),1)
        self.assertEqual(len(self.store.messages(self.conv['id'])),1)
        self.assertEqual(self.store.messages(self.conv['id'])[0]['source_created_at'],'2018-03-28 00:00:00')
    def test_personal_feedback_dedup_is_per_user_not_global(self):
        a=self.ops.feedback_case('alice','real-review');b=self.ops.feedback_case('bob','real-review')
        self.assertNotEqual(a['conversation']['id'],b['conversation']['id'])
        self.assertEqual(len(self.ops.visible('ticket','alice')),1)
    def test_nonmember_assignment_rejected_and_member_can_take_over_same_ticket(self):
        self.assertEqual(self.patch(owner='outsider').status_code,409)
        response=self.patch(owner='bob');self.assertEqual(response.status_code,200)
        pending=response.json();self.assertEqual(pending['owner'],'alice');self.assertEqual(pending['handoff']['state'],'pending')
        self.ops.handoff(self.ticket['id'],'bob','accept','核对后接手',pending['revision'],self.ws['id'])
        shared=self.ops.owned('ticket',self.ticket['id'],'bob',self.ws['id']);self.assertEqual(shared['owner'],'bob')
        response=self.client.patch('/tickets/'+shared['id'],json=dict(user_id='bob',workspace_id=self.ws['id'],owner='bob',status='in_progress',note='同事接班继续处理'))
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['history'][-1]['actor'],'bob')
    def test_member_maintenance_only_supervisor_and_last_supervisor_preserved(self):
        r=self.client.post('/workspaces/'+self.ws['id']+'/members',json=dict(user_id='bob',member_id='eve'))
        self.assertEqual(r.status_code,409)
        with self.assertRaises(ValueError):self.ops.member('alice',self.ws['id'],'alice','agent')
    def test_due_requires_owner_action_and_timezone(self):
        due=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        self.assertEqual(self.patch(owner='待分派',due_at=due,next_action='回访核对').status_code,409)
        self.assertEqual(self.patch(due_at=due,next_action='').status_code,409)
        self.assertEqual(self.patch(due_at='2026-10-25T10:00',next_action='回访核对').status_code,422)
        self.assertEqual(self.patch(due_at=due,next_action='回访核对').status_code,200)
        self.assertEqual(self.patch(owner='待分派').status_code,409)
    def test_queue_flags_clear_when_resolved_and_sync_case_then_reopen(self):
        due=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
        self.assertEqual(self.patch(owner='bob',priority='high',due_at=due,next_action='回访核对').status_code,200)
        pending=self.store.get('ticket',self.ticket['id']);self.ops.handoff(self.ticket['id'],'bob','accept','核对后接手',pending['revision'],self.ws['id'])
        queue=self.ops.queue('bob',self.ws['id'])['items'];self.assertTrue(queue[0]['overdue']);self.assertTrue(queue[0]['assigned_to_me'])
        self.assertEqual(self.patch(owner='bob',status='resolved',resolution='已核实并记录解决意见').status_code,200)
        self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'resolved')
        self.assertFalse(self.ops.queue('bob',self.ws['id'])['items'][0]['overdue'])
        self.assertEqual(self.patch().status_code,409)
        r=self.client.post('/tickets/'+self.ticket['id']+'/reopen',json={**self.scope,'note':'客户补充材料'})
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['reopened_count'],1)
        self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'pending')
        self.assertIn('客户补充材料',r.json()['history'][-1]['action'])
    def test_cannot_close_case_while_any_ticket_open(self):
        result=self.client.patch('/conversations/'+self.conv['id'],json={**self.scope,'status':'resolved','resolution':'草稿已准备'})
        self.assertEqual(result.status_code,409)
        self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'pending')
    def test_version_conflict_rejects_lost_updates(self):
        self.assertEqual(self.patch(expected_revision=1).status_code,200)
        self.assertEqual(self.patch(expected_revision=1,next_action='过期内容').status_code,409)
        self.assertNotEqual(self.store.get('ticket',self.ticket['id'])['next_action'],'过期内容')
    def test_ticket_creation_does_not_duplicate_already_resolved_case(self):
        self.patch(status='resolved',resolution='处理完成')
        again=self.ops.ticket(self.store.get('conversation',self.conv['id']),'重复创建')
        self.assertEqual(again['id'],self.ticket['id']);self.assertEqual(again['status'],'resolved')
    def test_intake_persistence_and_validation(self):
        path='/conversations/'+self.conv['id'];data={**self.scope,'intake':dict(issue_type='missing',quantity=2,product_id='sku-demo',desired_outcome='核对补发条件',evidence_note='照片待收集')}
        self.assertEqual(self.client.patch(path,json=data).status_code,200)
        self.assertEqual(WorkbenchStore(self.store.path).get('conversation',self.conv['id'])['intake']['quantity'],2)
        data['intake']['quantity']=0;self.assertEqual(self.client.patch(path,json=data).status_code,422)
    def test_gap_cannot_finish_with_test_draft_or_archived_document(self):
        gap=self.client.post('/knowledge/gaps',json={**self.scope,'conv_id':self.conv['id'],'question':'延迟赔付规则'}).json()
        same=self.client.post('/knowledge/gaps',json={**self.scope,'conv_id':self.conv['id'],'question':'延迟赔付规则'}).json();self.assertEqual(gap['id'],same['id'])
        data={**self.scope,'owner':'bob','status':'resolved','note':'补齐审核依据','document_id':'policy','expected_revision':gap['revision']}
        for doc in [dict(scope='test',published_version=1),dict(scope='business',published_version=None),dict(scope='business',published_version=1,deleted=True)]:
            self.store.put('document',dict(id='policy',**doc));self.assertEqual(self.client.patch('/knowledge/gaps/'+gap['id'],json=data).status_code,409)
        self.store.put('document',dict(id='policy',scope='business',published_version=1,deleted=False))
        self.assertEqual(self.client.patch('/knowledge/gaps/'+gap['id'],json=data).status_code,200)
    def test_adopted_revision_preserves_original_and_replaces_only_after_new_adoption(self):
        msg=self.store.append(self.conv['id'],'assistant','原稿内容',review_state='draft',revision=1,knowledge_mode='business',sources=[])
        parent=self.store.update_draft(self.conv['id'],msg['id'],'alice','原采用稿',1,True,workspace_id=self.ws['id'])
        new=self.ops.revise(self.conv['id'],parent['id'],'bob',self.ws['id'])
        self.assertEqual(new['parent_message_id'],parent['id']);self.assertEqual(new['review_state'],'draft')
        self.assertIn('原采用稿',str(model_history(self.store,self.conv['id'],'business')))
        self.store.update_draft(self.conv['id'],new['id'],'bob','修订采用稿',1,True,workspace_id=self.ws['id'])
        history=str(model_history(self.store,self.conv['id'],'business'));self.assertNotIn('原采用稿',history);self.assertIn('修订采用稿',history)
        self.assertEqual(self.store.messages(self.conv['id'])[1]['content'],'原采用稿')
    def test_report_counts_actual_case_outcomes_not_adoption(self):
        self.store.append(self.conv['id'],'assistant','采用内容',review_state='adopted')
        report=self.ops.report('alice',self.ws['id']);self.assertEqual(report['open_cases'],1);self.assertEqual(report['resolved_cases'],0)
        self.patch(status='resolved',resolution='核对完成');self.assertEqual(self.ops.report('bob',self.ws['id'])['resolved_cases'],1)
    def test_fact_reply_adoption_blocked_after_order_link_changes(self):
        self.store.put('order',dict(id='other-order'))
        msg=self.store.append(self.conv['id'],'assistant','旧订单事实',review_state='draft',revision=1,knowledge_mode='business',sources=[],data_sources=[dict(kind='order',id='historical-order')])
        self.ops.patch_conversation(self.conv['id'],'alice',dict(order_id='other-order'),self.ws['id'])
        result=self.client.patch('/conversations/'+self.conv['id']+'/drafts/'+msg['id'],json={**self.scope,'content':'旧订单事实','revision':1,'adopt':True})
        self.assertEqual(result.status_code,409);self.assertIn('关联订单已变化',result.json()['detail'])
    def test_task_map_has_outcomes_entries_and_future_boundaries(self):
        catalog=self.client.get('/task-map').json();self.assertEqual(len(catalog['tasks']),31)
        for task in catalog['tasks']:
            for key in ['trigger','steps','done','exception','view','availability']:self.assertTrue(task[key])
        self.assertEqual(len([t for t in catalog['tasks'] if t['availability']=='local']),24)

class OrderFactTests(unittest.TestCase):
    def setUp(self):self.order=dict(id='historical-order',status='delivered',total=100,estimated_at='2018-03-26 00:00:00',delivered_at='2018-04-10 16:54:36',items=[dict(product_id='sku',price=90.,freight=10.)])
    def test_late_is_calendar_date_difference_not_rounding_elapsed_hours(self):
        fact=order_fact('这笔订单比预计晚了几天？不要引用示例政策',self.order)
        self.assertIn('晚 15 个自然日',fact['response']);self.assertIn('historical-order',fact['data_sources'][0]['url'])
    def test_missing_actual_does_not_invent_delivery(self):
        self.order['delivered_at']=None;self.assertIn('无法计算',order_fact('晚了几天',self.order)['response'])
    def test_item_and_freight_are_from_order_fields(self):
        self.assertIn('运费 10.00 BRL',order_fact('买了什么商品，运费多少',self.order)['response'])
    def test_mixed_policy_and_fact_queries_are_identified(self):
        for query in ['晚了几天，能不能退款？','晚到几天？退款怎么处理','晚到几天，赔付标准是多少']:self.assertTrue(wants_policy(query))
        self.assertFalse(wants_policy('只比较晚到多少天，不要引用示例政策'))
