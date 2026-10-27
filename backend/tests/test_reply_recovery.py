import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from api import main
from api.workbench_routes import create_router
from agents.agent_orchestrator import AgentType
from core.intent_recognizer import IntentCategory,UrgencyLevel
from core.operations import Operations
from core.reply_requests import ReplyRequests
from core.workbench import WorkbenchStore
from core.conversation_context import build_memory,model_history

class ReplyRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'db.sqlite';self.store=WorkbenchStore(self.path);self.requests=ReplyRequests(self.store)
        result=SimpleNamespace(response='模型草稿',intent=IntentCategory.OTHER,agent_type=AgentType.GENERAL,agent_types=[AgentType.GENERAL],primary_agent=AgentType.GENERAL,supporting_agents=[],routing_reason='test',routing_confidence=.7,escalated=False,latency_ms=2)
        intent=SimpleNamespace(intent=IntentCategory.OTHER,intent_group='other',urgency=UrgencyLevel.LOW,entities={},confidence=.7,source_scores={})
        self.orchestrator=SimpleNamespace(recognize_intent=AsyncMock(return_value=intent),run=AsyncMock(return_value=result))
        for item in [patch.object(main,'_store',self.store),patch.object(main,'_orchestrator',self.orchestrator),patch.object(main,'_chat_locks',{}),patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'not_searched')))]:item.start();self.addCleanup(item.stop)
        self.conv=self.store.conversation('alice');self.conv['knowledge_mode']='business';self.store.put('conversation',self.conv)
    def request(self,**kw):return main.ChatRequest(**dict(message='客户希望核对包裹',user_id='alice',conv_id=self.conv['id'],request_id='request-1',**kw))
    async def test_duplicate_success_and_concurrent_retry_only_one_input_and_draft(self):
        req=self.request();a,b=await asyncio.gather(main.chat(req),main.chat(req))
        self.assertEqual(a,b);self.assertEqual(len(self.store.messages(self.conv['id'])),2);self.assertEqual(self.orchestrator.run.call_count,1)
        self.assertEqual(self.requests.get(self.conv['id'],'request-1')['state'],'succeeded')
    async def test_failure_retry_survives_store_reload_without_duplicate_customer(self):
        self.orchestrator.run.side_effect=RuntimeError('PRIVATE-PROVIDER-DETAIL')
        req=self.request()
        with self.assertRaises(HTTPException):await main.chat(req)
        receipt=self.requests.get(self.conv['id'],'request-1');self.assertEqual(receipt['state'],'failed');self.assertNotIn('PRIVATE-PROVIDER',str(receipt))
        self.orchestrator.run.side_effect=None
        with patch.object(main,'_store',WorkbenchStore(self.path)):await main.chat(req)
        messages=self.store.messages(self.conv['id']);self.assertEqual(sum(m['role']=='user' for m in messages),1);self.assertEqual(sum(m['role']=='assistant' for m in messages),1)
        self.assertEqual(self.requests.get(self.conv['id'],'request-1')['attempts'],2)
    async def test_request_key_conflict_does_not_append_new_text(self):
        await main.chat(self.request())
        for changes in [dict(message='不同内容'),dict(input_kind='staff_action',action='custom')]:
            data=self.request().model_dump();data.update(changes)
            with self.assertRaises(HTTPException) as error:await main.chat(main.ChatRequest(**data))
            self.assertEqual(error.exception.status_code,409)
        self.assertEqual(len(self.store.messages(self.conv['id'])),2)
    async def test_staff_action_does_not_become_customer_fact_or_history(self):
        self.store.append(self.conv['id'],'user','我的订单号是CUSTOMER-42')
        req=main.ChatRequest(user_id='alice',conv_id=self.conv['id'],message='我的订单号是STAFF-99999',request_id='staff-1',input_kind='staff_action',action='custom')
        await main.chat(req);memory=build_memory(self.store,self.conv['id']);self.assertEqual(memory['customer_message_count'],1);self.assertEqual(memory['facts']['order_id']['value'],'CUSTOMER-42')
        history=str(model_history(self.store,self.conv['id'],'business'));self.assertNotIn('STAFF-99999',history)
        self.assertEqual(self.store.messages(self.conv['id'])[1]['role'],'operation')
        self.assertNotIn('STAFF-99999',self.orchestrator.run.call_args.args[0].context)
    async def test_redraft_uses_latest_customer_without_repeating_it(self):
        self.store.append(self.conv['id'],'user','客户询问包裹去向')
        req=main.ChatRequest(user_id='alice',conv_id=self.conv['id'],message='重新准备回复',request_id='staff-redraft',input_kind='staff_action',action='redraft')
        await main.chat(req);self.assertEqual(self.orchestrator.run.call_args.args[0].message,'客户询问包裹去向')
        self.assertEqual(sum(m['role']=='user' for m in self.store.messages(self.conv['id'])),1)
    async def test_local_fact_action_available_without_model_and_without_customer_input(self):
        self.store.put('order',dict(id='order',status='delivered',total=20,estimated_at='2018-03-26',delivered_at='2018-04-10'))
        self.conv['order_id']='order';self.store.put('conversation',self.conv)
        with patch.object(main,'_orchestrator',None):
            result=await main.chat(main.ChatRequest(user_id='alice',conv_id=self.conv['id'],message='晚到几天',request_id='fact-1',input_kind='staff_action',action='order_facts'))
        self.assertIn('晚 15 个自然日',result.response);self.assertEqual(build_memory(self.store,self.conv['id'])['customer_message_count'],0)
    async def test_missing_prerequisite_has_failed_receipt_and_can_stop_retry(self):
        req=main.ChatRequest(user_id='alice',conv_id=self.conv['id'],message='重新准备回复',request_id='no-customer',input_kind='staff_action',action='redraft')
        with self.assertRaises(HTTPException):await main.chat(req)
        self.assertEqual(self.requests.get(self.conv['id'],'no-customer')['state'],'failed')
        self.requests.dismiss(self.conv['id'],'no-customer','alice')
        with self.assertRaises(HTTPException) as error:await main.chat(req)
        self.assertEqual(error.exception.status_code,409)
    async def test_running_request_can_recover_after_server_restart(self):
        self.requests.begin(self.conv,'alice','request-1','客户希望核对包裹')
        await main.chat(self.request());self.assertEqual(sum(m['role']=='user' for m in self.store.messages(self.conv['id'])),1)
        self.assertEqual(self.requests.get(self.conv['id'],'request-1')['state'],'succeeded')
    async def test_customer_saved_even_when_model_is_unavailable(self):
        with patch.object(main,'_orchestrator',None):
            with self.assertRaises(HTTPException):await main.chat(self.request())
        self.assertEqual(self.store.messages(self.conv['id'])[0]['content'],'客户希望核对包裹');self.assertEqual(self.requests.get(self.conv['id'],'request-1')['state'],'failed')
    async def test_wrong_user_rejected_before_durable_input(self):
        req=self.request().model_copy(update={'user_id':'bob'})
        with self.assertRaises(HTTPException):await main.chat(req)
        self.assertEqual(self.store.messages(self.conv['id']),[])
    async def test_action_cannot_be_recorded_as_customer_by_mistake(self):
        req=self.request().model_copy(update={'action':'translate'})
        with self.assertRaises(HTTPException) as error:await main.chat(req)
        self.assertEqual(error.exception.status_code,422);self.assertEqual(self.store.messages(self.conv['id']),[])
    async def test_staff_action_does_not_reopen_closed_case_but_customer_does(self):
        self.conv.update(status='resolved',resolution='原事项完成');self.store.put('conversation',self.conv)
        req=main.ChatRequest(user_id='alice',conv_id=self.conv['id'],message='翻译原文',request_id='staff-closed',input_kind='staff_action',action='translate')
        await main.chat(req);self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'resolved')
        await main.chat(self.request());self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'open')
    async def test_new_customer_invalidates_confirmation_with_or_without_ticket(self):
        from core.service_followup import Followups
        from core.workbench import now
        follow=Followups(self.store)
        for with_ticket in (False,True):
            c=self.store.conversation('alice');c['knowledge_mode']='business';self.store.put('conversation',c)
            if with_ticket:t=Operations(self.store).ticket(c,'新问题')
            follow.customer_result(c['id'],'alice',dict(status='confirmed',occurred_at=now(),note='上一轮人工确认',expected_revision=0))
            plan=dict(kind='confirmed',expected_result_revision=1,expected_plan_revision=0)
            if with_ticket:Operations(self.store).update_ticket(t['id'],'alice',dict(owner='alice',status='resolved',note='本轮完成',closure_plan=plan))
            else:Operations(self.store).patch_conversation(c['id'],'alice',dict(status='resolved',resolution='本轮完成',closure_plan=plan))
            req=main.ChatRequest(user_id='alice',conv_id=c['id'],message='客户再次反馈问题未解决',request_id='new-customer-'+str(with_ticket))
            await main.chat(req);saved=self.store.get('conversation',c['id'])
            self.assertTrue(saved['customer_confirmation_required']);self.assertEqual(saved['service_round'],1)
            self.assertEqual(saved['customer_result']['status'],'pending');self.assertFalse(saved['closure_plan']['active'])
            self.assertEqual(saved['customer_result_history'][0]['status'],'confirmed')
            # Request retries must not start an additional round or duplicate the feedback history.
            await main.chat(req);self.assertEqual(self.store.get('conversation',c['id'])['service_round'],1)
            if with_ticket:self.assertEqual(self.store.get('ticket',t['id'])['reopened_count'],1)

    async def test_restart_between_persisting_customer_and_reopening_case_recovers(self):
        from core.workbench import now
        self.conv.update(status='resolved',resolution='旧结果',resolved_at=now());self.store.put('conversation',self.conv)
        self.requests.begin(self.conv,'alice','request-1','客户希望核对包裹')
        await main.chat(self.request())
        self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'open')
    async def test_retry_old_failed_generation_does_not_reopen_a_newer_manual_closure(self):
        self.orchestrator.run.side_effect=RuntimeError('temporary failure')
        with self.assertRaises(HTTPException):await main.chat(self.request())
        Operations(self.store).patch_conversation(self.conv['id'],'alice',dict(status='resolved',resolution='后续已人工处理',closure_plan=dict(kind='no_followup',note='隔离测试样本，仅内部验证，无需客户回访',expected_result_revision=0,expected_plan_revision=0)))
        self.orchestrator.run.side_effect=None
        await main.chat(self.request())
        self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'resolved')
    async def test_no_knowledge_has_explicit_not_run_trace_and_keeps_technical_collection(self):
        with patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'no_match'))):
            response=await main.chat(self.request().model_copy(update={'message':'进口税能退吗？我无法登录，页面HTTP 401。'}))
        self.orchestrator.run.assert_not_awaited()
        self.assertEqual((response.execution_path,response.agent_execution_status,response.agent_types,response.agent_type),('knowledge_guard','not_run',[],''))
        self.assertIn('发生时间',response.response);self.assertIn('401',response.response);self.assertIn('设备',response.response)
        self.assertIn('进口税',response.response);self.assertIn('依据不足',response.response)
        saved=self.store.messages(self.conv['id'])[-1];self.assertEqual(saved['agent_execution_status'],'not_run')
    async def test_order_facts_button_does_not_call_intent_or_reply_model(self):
        self.store.put('order',dict(id='order',status='delivered',total=20,estimated_at='2018-03-26',delivered_at='2018-04-10'))
        self.conv['order_id']='order';self.store.put('conversation',self.conv)
        response=await main.chat(main.ChatRequest(user_id='alice',conv_id=self.conv['id'],message='只根据订单核对时效，不推断赔付规则',request_id='facts-trace',input_kind='staff_action',action='order_facts'))
        self.orchestrator.recognize_intent.assert_not_awaited();self.orchestrator.run.assert_not_awaited()
        self.assertEqual((response.execution_path,response.agent_execution_status),('record_query','not_run'))
        self.assertIn('晚 15 个自然日',response.response)
    async def test_actual_agent_trace_uses_requested_and_returned_outcomes(self):
        result=self.orchestrator.run.return_value
        result.agent_outcomes=[dict(requested_agent='technical',agent_type='general',state='fallback')]
        result.execution_status='degraded'
        response=await main.chat(self.request())
        self.orchestrator.run.assert_awaited_once()
        self.assertEqual((response.execution_path,response.agent_execution_status),('agent','degraded'))
        self.assertEqual(response.agent_outcomes[0]['requested_agent'],'technical')
    async def test_direct_clarification_does_not_claim_general_executed(self):
        result=self.orchestrator.run.return_value
        result.agent_outcomes=[];result.agent_types=[];result.routing_reason='低置信度OTHER，先澄清用户需求'
        response=await main.chat(self.request())
        self.assertEqual((response.execution_path,response.agent_execution_status,response.agent_type),('clarification','not_run',''))

    async def test_redraft_without_knowledge_still_labels_original_customer_as_customer(self):
        self.store.append(self.conv['id'],'user','进口税能退吗？另外我无法登录，页面401。',kind='customer_input')
        with patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'no_match'))):
            response=await main.chat(main.ChatRequest(user_id='alice',conv_id=self.conv['id'],message='根据原话重新准备回复',request_id='redraft-trace',input_kind='staff_action',action='redraft'))
        self.assertIn('客户最新自述',response.response);self.assertNotIn('客服假设练习',response.response)
        self.assertEqual(response.agent_execution_status,'not_run');self.assertIn('发生时间',response.response)
        self.assertEqual(sum(m['role']=='user' for m in self.store.messages(self.conv['id'])),1)

    async def test_current_customer_not_duplicated_in_model_history(self):
        self.store.append(self.conv['id'],'user','原客户上下文')
        await main.chat(self.request());request=self.orchestrator.run.call_args.args[0]
        self.assertEqual(request.history,[dict(role='user',content='原客户上下文')]);self.assertIn('客户希望核对包裹',request.context)

class ManualAndReceiptRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=WorkbenchStore(Path(self.temp.name)/'db.sqlite');self.conv=self.store.conversation('alice')
        app=FastAPI();app.include_router(create_router(self.store,lambda:None,lambda:None));self.client=TestClient(app)
    def manual(self,**kw):
        body=dict(user_id='alice',content='人工核对后的回复',request_id='manual-1');body.update(kw)
        return self.client.post('/conversations/'+self.conv['id']+'/drafts/manual',json=body)
    def test_manual_save_retry_and_adoption_without_model(self):
        a=self.manual();b=self.manual();self.assertEqual(a.status_code,200);self.assertEqual(a.json()['id'],b.json()['id']);self.assertTrue(a.json()['manual'])
        self.assertEqual(len(self.store.messages(self.conv['id'])),1);self.assertEqual(build_memory(self.store,self.conv['id'])['customer_message_count'],0)
        r=self.client.patch('/conversations/'+self.conv['id']+'/drafts/'+a.json()['id'],json=dict(user_id='alice',content='采用的人工回复',revision=1,adopt=True))
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['review_state'],'adopted');self.assertEqual(r.json()['sources'],[])
    def test_manual_key_conflict_or_wrong_user_not_saved(self):
        self.manual();self.assertEqual(self.manual(content='其他内容').status_code,409);self.assertEqual(self.manual(user_id='bob').status_code,404)
        self.assertEqual(len(self.store.messages(self.conv['id'])),1)
    def test_manual_empty_or_too_long_rejected(self):
        self.assertEqual(self.manual(content=' ').status_code,422);self.assertEqual(self.manual(content='字'*16001).status_code,422)
    def test_receipt_scoped_to_conversation_and_original_actor(self):
        requests=ReplyRequests(self.store);requests.begin(self.conv,'alice','r-1','客户输入')
        path='/conversations/'+self.conv['id']+'/requests/r-1'
        self.assertEqual(self.client.get(path+'?user_id=alice').status_code,200);self.assertEqual(self.client.get(path+'?user_id=bob').status_code,404)
        self.assertEqual(self.client.post(path+'/dismiss',json=dict(user_id='alice')).status_code,409)
        requests.fail(self.conv['id'],'r-1');self.assertEqual(self.client.post(path+'/dismiss',json=dict(user_id='alice')).json()['state'],'dismissed')
    def test_result_and_receipt_commit_atomically(self):
        requests=ReplyRequests(self.store);requests.begin(self.conv,'alice','r-1','客户输入')
        from core.reply_requests import write as original
        def fail_on_receipt(db,kind,data):
            if kind=='reply_request' and data['state']=='succeeded':raise RuntimeError('disk transaction test')
            return original(db,kind,data)
        with patch('core.reply_requests.write',side_effect=fail_on_receipt),self.assertRaises(RuntimeError):requests.finish(self.conv['id'],'r-1',dict(response='成功回复',conv_id=self.conv['id']))
        self.assertEqual(len(self.store.messages(self.conv['id'])),1);self.assertEqual(requests.get(self.conv['id'],'r-1')['state'],'running')
