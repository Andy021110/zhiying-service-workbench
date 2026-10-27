import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from core.workbench import WorkbenchStore
from core.operations import Operations
from agents.agent_orchestrator import AgentType
from core.intent_recognizer import IntentCategory,UrgencyLevel
from api import main

class ChatTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=WorkbenchStore(Path(self.temp.name)/'db.sqlite');self.ops=Operations(self.store)
        result=SimpleNamespace(response='译文：客户未收到商品。',intent=IntentCategory.OTHER,agent_type=AgentType.GENERAL,agent_types=[AgentType.GENERAL],primary_agent=AgentType.GENERAL,supporting_agents=[],routing_reason='test',routing_confidence=.7,escalated=False,latency_ms=2)
        intent=SimpleNamespace(intent=IntentCategory.OTHER,intent_group='other',urgency=UrgencyLevel.LOW,entities={},confidence=.7,source_scores={})
        self.orchestrator=SimpleNamespace(recognize_intent=AsyncMock(return_value=intent),run=AsyncMock(return_value=result))
        for item in [patch.object(main,'_store',self.store),patch.object(main,'_orchestrator',self.orchestrator),patch.object(main,'_chat_locks',{})]:item.start();self.addCleanup(item.stop)
        self.store.put('order',dict(id='order',status='delivered',total=20,estimated_at='2018-03-26',delivered_at='2018-04-10 16:54:36'))
        self.conv=self.store.conversation('alice',order_id='order');self.conv['knowledge_mode']='business';self.store.put('conversation',self.conv)
    async def send(self,text,**kw):return await main.chat(main.ChatRequest(message=text,user_id='alice',conv_id=self.conv['id'],**kw))
    async def test_factual_date_math_does_not_require_any_policy_or_model(self):
        with patch.object(main,'_retrieve_knowledge',AsyncMock()) as retrieval:
            result=await self.send('这个订单比预计晚了多少天？不要引用示例政策')
        self.assertIn('晚 15 个自然日',result.response);self.assertEqual(result.knowledge_status,'order_fact')
        retrieval.assert_not_called();self.orchestrator.run.assert_not_called()
        self.assertEqual(self.store.messages(self.conv['id'])[-1]['data_sources'][0]['id'],'order')
    async def test_mixed_policy_request_keeps_date_facts_but_does_not_invent_policy(self):
        with patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'no_match'))):result=await self.send('晚到几天，退款怎么处理？')
        self.assertIn('晚 15 个自然日',result.response);self.assertIn('无法确认',result.response);self.assertEqual(result.knowledge_status,'no_match')
    async def test_translation_bypasses_policy_gate_and_has_original_reference(self):
        original=self.store.append(self.conv['id'],'user','Não recebi o produto',source='真实葡萄牙语评价原文')
        self.store.append(self.conv['id'],'note','INTERNAL-SECRET-NOTE')
        with patch.object(main,'_retrieve_knowledge',AsyncMock()) as retrieval:result=await self.send('翻译原文并概括客户诉求')
        self.assertEqual(result.knowledge_status,'source_translation');self.assertEqual(result.context_reference_ids,[original['id']]);retrieval.assert_not_called()
        request=self.orchestrator.run.call_args.args[0];self.assertIn(original['content'],request.context);self.assertNotIn('INTERNAL-SECRET-NOTE',request.context)
        self.assertIn('机器翻译',result.response);self.assertIsNone(request.history)
    async def test_translation_without_original_does_not_call_model(self):
        result=await self.send('翻译客户原文');self.orchestrator.run.assert_not_called();self.assertIn('请先录入',result.response)
    async def test_translation_with_order_words_still_translates(self):
        self.store.append(self.conv['id'],'user','Não recebi o produto',source='真实葡萄牙语评价原文')
        result=await self.send('翻译商品原文');self.assertEqual(result.knowledge_status,'source_translation')
    async def test_new_customer_message_reopens_resolved_case_with_history(self):
        ticket=self.store.ticket(self.conv,'摘要');self.ops.update_ticket(ticket['id'],'alice',dict(owner='alice',status='resolved',note='原处理完成',closure_plan=dict(kind='no_followup',note='隔离测试样本，仅内部验证，无需客户回访',expected_result_revision=0,expected_plan_revision=0)))
        await self.send('订单状态是什么')
        reopened=self.store.get('ticket',ticket['id']);self.assertEqual(reopened['status'],'pending');self.assertEqual(reopened['reopened_count'],1)
        self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'pending')
    async def test_new_customer_message_reopens_case_without_ticket(self):
        self.ops.patch_conversation(self.conv['id'],'alice',dict(status='resolved',resolution='原事项完成',closure_plan=dict(kind='no_followup',note='隔离测试样本，仅内部验证，无需客户回访',expected_result_revision=0,expected_plan_revision=0)))
        await self.send('订单状态是什么');self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'open')
    async def test_team_member_can_generate_in_shared_case(self):
        ws=self.ops.workspace('alice','团队');self.ops.member('alice',ws['id'],'bob','agent');self.conv['workspace_id']=ws['id'];self.store.put('conversation',self.conv)
        result=await main.chat(main.ChatRequest(message='订单状态是什么',user_id='bob',conv_id=self.conv['id'],workspace_id=ws['id']))
        self.assertEqual(result.knowledge_status,'order_fact');self.assertEqual(len(self.store.messages(self.conv['id'])),2)
