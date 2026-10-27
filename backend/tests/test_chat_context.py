import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from core.workbench import WorkbenchStore
from agents.agent_orchestrator import AgentType
from core.intent_recognizer import IntentCategory, UrgencyLevel
from api import main


class ChatContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=WorkbenchStore(Path(self.temp.name)/'db.sqlite')
        self.intent=SimpleNamespace(intent=IntentCategory.OTHER,intent_group='other',urgency=UrgencyLevel.LOW,entities={},confidence=.7,source_scores={})
        result=SimpleNamespace(response='模型回复',intent=IntentCategory.OTHER,agent_type=AgentType.GENERAL,agent_types=[AgentType.GENERAL],primary_agent=AgentType.GENERAL,supporting_agents=[],routing_reason='test',routing_confidence=.7,escalated=False,latency_ms=2)
        self.orchestrator=SimpleNamespace(recognize_intent=AsyncMock(return_value=self.intent),run=AsyncMock(return_value=result))
        for item in [patch.object(main,'_store',self.store),patch.object(main,'_orchestrator',self.orchestrator),patch.object(main,'_chat_locks',{})]:
            item.start();self.addCleanup(item.stop)
    async def test_active_conversation_is_only_model_history(self):
        a=self.store.conversation('alice');b=self.store.conversation('alice')
        self.store.append(a['id'],'user','仅A会话的私有代号')
        self.store.append(b['id'],'user','仅B会话的内容')
        with patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'not_searched'))):
            await main.chat(main.ChatRequest(message='你好',user_id='alice',conv_id=b['id']))
        request=self.orchestrator.run.call_args.args[0]
        self.assertIn('仅B会话的内容',request.context)
        self.assertNotIn('仅A会话的私有代号',request.context)
        self.assertEqual(request.history,[{'role':'user','content':'仅B会话的内容'}])
    async def test_wrong_user_rejected_before_model_call(self):
        c=self.store.conversation('alice')
        with self.assertRaises(HTTPException) as error:
            await main.chat(main.ChatRequest(message='你好',user_id='bob',conv_id=c['id']))
        self.assertEqual(error.exception.status_code,404);self.orchestrator.run.assert_not_called()
    async def test_generation_failure_preserves_user_message(self):
        c=self.store.conversation('alice');self.orchestrator.run.side_effect=RuntimeError('private provider failure')
        with patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'not_searched'))):
            with self.assertRaises(HTTPException) as error:
                await main.chat(main.ChatRequest(message='你好',user_id='alice',conv_id=c['id']))
        self.assertEqual(error.exception.status_code,502)
        self.assertEqual(self.store.messages(c['id'])[0]['content'],'你好')
        self.assertNotIn('private provider failure',str(self.store.messages(c['id'])))
    async def test_no_match_blocks_ungrounded_policy(self):
        c=self.store.conversation('alice')
        with patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'no_match'))):
            r=await main.chat(main.ChatRequest(message='不存在的政策',user_id='alice',conv_id=c['id']))
        self.assertIn('无法确认',r.response);self.assertFalse(r.knowledge_used)
    async def test_fallback_and_archived_candidates_are_not_sources(self):
        candidates=[dict(fallback=True,title='错误降级',content='不是政策',score=1),dict(document_id='archived',version=1,score=.9,content='归档内容')]
        self.store.put('document',dict(id='archived',version=1,deleted=True))
        manager=SimpleNamespace(search_with_rewrite=AsyncMock(return_value=SimpleNamespace(success=True,data=candidates)))
        with patch.object(main,'_tool_manager',manager):
            _,sources,status=await main._retrieve_knowledge('会员权益','other')
        self.assertEqual(sources,[]);self.assertEqual(status,'no_match')

    async def test_notes_and_unadopted_drafts_never_reach_model(self):
        c=self.store.conversation('alice')
        self.store.append(c['id'],'user','客户想核对物流')
        self.store.append(c['id'],'note','STAFF-PRIVATE-42')
        self.store.append(c['id'],'assistant','UNREVIEWED-POLICY-99',review_state='draft')
        with patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'not_searched'))):
            await main.chat(main.ChatRequest(message='你好',user_id='alice',conv_id=c['id']))
        request=self.orchestrator.run.call_args.args[0]
        self.assertNotIn('STAFF-PRIVATE-42',request.context)
        self.assertNotIn('UNREVIEWED-POLICY-99',request.context)
        self.assertNotIn('STAFF-PRIVATE-42',str(request.history))

    async def test_older_customer_fact_is_in_actual_model_context(self):
        c=self.store.conversation('alice')
        self.store.append(c['id'],'user','我的订单号是LONG-CONTEXT-42。我的诉求是核对物流。')
        for i in range(20):self.store.append(c['id'],'user',f'其他补充{i}')
        with patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'not_searched'))):
            await main.chat(main.ChatRequest(message='你好',user_id='alice',conv_id=c['id']))
        request=self.orchestrator.run.call_args.args[0]
        self.assertIn('LONG-CONTEXT-42',request.context)
        self.assertNotIn('LONG-CONTEXT-42',str(request.history))

    async def test_personal_fact_recall_does_not_call_model_or_leak_other_case(self):
        c=self.store.conversation('alice')
        self.store.append(c['id'],'user','我的订单号是LOCAL-RECALL-42')
        result=await main.chat(main.ChatRequest(message='我之前提供的订单号是什么？',user_id='alice',conv_id=c['id']))
        self.assertIn('LOCAL-RECALL-42',result.response)
        self.assertEqual(result.knowledge_status,'conversation_context')
        self.orchestrator.run.assert_not_called()
