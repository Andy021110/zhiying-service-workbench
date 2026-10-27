import asyncio,unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from agents.agent_orchestrator import AgentOrchestrator,AgentType,AgentResponse,RoutingDecision,Request
from core.intent_recognizer import IntentCategory,UrgencyLevel

class AssistantFailureEdges(unittest.IsolatedAsyncioTestCase):
    def setup_case(self):
        orch=AgentOrchestrator(api_key='controlled-test')
        req=Request(message='重复扣款且无法登录，错误401',user_id='test',conv_id='isolated',intent=IntentCategory.PAYMENT_ISSUE,urgency=UrgencyLevel.LOW)
        return orch,req

    async def test_timeout_preserves_other_branch_and_marks_partial(self):
        orch,req=self.setup_case()
        async def execute(r,at):
            if at==AgentType.TECHNICAL:raise asyncio.TimeoutError()
            return AgentResponse(at,'保留资金核对结果',True)
        orch._execute=execute
        result=await orch.run_parallel(req,RoutingDecision(AgentType.BILLING,[AgentType.TECHNICAL]))
        self.assertEqual(result.execution_status,'degraded');self.assertIn('保留资金核对结果',result.response)
        self.assertEqual(result.agent_types,[AgentType.BILLING]);self.assertEqual(result.agent_outcomes[1]['state'],'failed')

    async def test_all_failed_is_failed_not_completed(self):
        orch,req=self.setup_case();orch._execute=AsyncMock(return_value=AgentResponse(AgentType.GENERAL,'失败',False))
        result=await orch.run_parallel(req,RoutingDecision(AgentType.BILLING,[AgentType.TECHNICAL]))
        self.assertEqual(result.execution_status,'failed');self.assertEqual(result.agent_types,[])

    async def test_specialist_failure_fallback_remains_degraded(self):
        orch,req=self.setup_case()
        def agent(at,success):return SimpleNamespace(agent_type=at,stats=SimpleNamespace(routing_score=lambda:1),handle=AsyncMock(return_value=AgentResponse(at,'通用参考' if success else '失败',success)))
        orch._pool={AgentType.BILLING:[agent(AgentType.BILLING,False)],AgentType.GENERAL:[agent(AgentType.GENERAL,True)]}
        result=await orch.run(req)
        self.assertEqual(result.execution_status,'degraded');self.assertIn('降级参考',result.response)
        self.assertEqual(result.agent_outcomes[0]['state'],'fallback')

    async def test_customer_input_does_not_import_staff_hypotheses(self):
        from core.assistant_quality import problem_domains
        self.assertEqual(problem_domains('只问登录失败，不涉及退款、支付和扣款。'),(True,False))

    async def test_no_match_state_update_is_not_a_generic_policy_fallback(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from core.workbench import WorkbenchStore
        from api import main
        with tempfile.TemporaryDirectory() as temp:
            store=WorkbenchStore(Path(temp)/'db');conv=store.conversation('test')
            store.append(conv['id'],'user','无法登录，且重复扣款。')
            fake=SimpleNamespace(recognize_intent=AsyncMock(return_value=SimpleNamespace(intent=IntentCategory.OTHER,intent_group='other',urgency=UrgencyLevel.LOW,entities={},confidence=.8,source_scores={})),run=AsyncMock())
            with patch.object(main,'_store',store),patch.object(main,'_orchestrator',fake),patch.object(main,'_chat_locks',{}),patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'no_match'))):
                result=await main.chat(main.ChatRequest(user_id='test',conv_id=conv['id'],message='登录已经恢复，但两笔交易仍需核实，尚未提供流水。'))
                self.assertIn('已经恢复',result.response);self.assertIn('资金问题仍待核实',result.response)
                self.assertNotIn('签收',result.response);fake.run.assert_not_awaited()
                result=await main.chat(main.ChatRequest(user_id='test',conv_id=conv['id'],message='两笔交易分别对应不同订单，不是重复扣款。'))
                self.assertIn('不同订单',result.response);self.assertIn('不继续沿用重复扣款',result.response)
                self.assertEqual(store.get('conversation',conv['id'])['status'],'open')

    async def test_correction_does_not_restore_retracted_policy_gap(self):
        from core.assistant_quality import knowledge_gaps,problem_domains
        self.assertEqual(knowledge_gaps('更正：不是重复扣款，是支付失败。不要继续假定已经多扣款。',[]),[])
        self.assertEqual(problem_domains('【模拟，不是真实客户事件】支付后重复扣款，而且无法登录页面401。'),(True,True))

    async def test_scoped_agent_instructions_have_system_priority(self):
        orch,req=self.setup_case();req.domain_scope='technical'
        prompt=orch._pool[AgentType.TECHNICAL][0]._build_system_prompt(req)
        self.assertIn('强制职责边界',prompt);self.assertIn('禁止列出该领域',prompt)

    async def test_general_refund_hit_cannot_answer_only_customs_questions(self):
        from core.assistant_quality import only_uncovered_policy_questions,knowledge_gaps
        sources=[dict(content='购买后7天可以退款，已发货先退货。')]
        question='如果是巴西跨境订单，进口税是否退回、汇率损失谁承担、晚到有三倍赔偿吗？请逐项核对，不要套用测试退款政策。'
        self.assertTrue(only_uncovered_policy_questions(question,knowledge_gaps(question,sources)))
        mixed='已发货订单怎样申请退货退款？如果是巴西跨境订单，进口税也退吗、汇率损失谁承担？请分别说明。'
        self.assertFalse(only_uncovered_policy_questions(mixed,knowledge_gaps(mixed,sources)))

    async def test_question_about_recovery_is_not_a_recovery_statement(self):
        from core.assistant_quality import issue_updates
        self.assertEqual(issue_updates('登录已经恢复了吗？'),{})
        self.assertEqual(issue_updates('登录已经恢复。接下来怎么办？')['technical'],'customer_reports_recovered')

    async def test_document_explicitly_without_policy_is_still_a_gap(self):
        from core.assistant_quality import knowledge_gaps
        self.assertEqual(knowledge_gaps('进口税退吗？',[dict(content='本规则未涉及进口税退还条款。')])[0]['topic'],'进口税')

    async def test_no_match_customer_reply_also_names_each_gap(self):
        import tempfile
        from pathlib import Path
        from core.workbench import WorkbenchStore
        from core.service_reference import prepare_reference
        with tempfile.TemporaryDirectory() as temp:
            store=WorkbenchStore(Path(temp)/'db');conv=store.conversation('test')
            message='进口税退吗、汇率损失谁承担、有三倍赔偿吗？'
            store.append(conv['id'],'user',message)
            result=prepare_reference(store,conv,None,message)
            for topic in ['进口税','汇率损失','三倍赔偿']:self.assertIn(topic,result['suggested_reply'])
