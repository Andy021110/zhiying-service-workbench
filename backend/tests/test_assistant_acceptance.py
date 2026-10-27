"""13 acceptance groups; provider calls are replaced with controlled responses.
Real answer quality is checked separately against the frozen source documents.
"""
import unittest, tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from api import main
REAL_RETRIEVE=main._retrieve_knowledge
from agents.agent_orchestrator import AgentOrchestrator, AgentType, AgentResponse, Request, RoutingDecision
from core.intent_recognizer import IntentRecognizer, IntentCategory, UrgencyLevel
from core.workbench import WorkbenchStore
from core.conversation_context import build_memory


class AssistantAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=WorkbenchStore(Path(self.tmp.name)/'test.sqlite');self.conv=self.store.conversation('acceptance')
        self.rec=IntentRecognizer(api_key='test-only-not-a-secret')
        self.orch=AgentOrchestrator(api_key='test-only-not-a-secret')
        self.result=SimpleNamespace(response='受控测试输出',intent=IntentCategory.OTHER,agent_type=AgentType.GENERAL,agent_types=[AgentType.GENERAL],primary_agent=AgentType.GENERAL,supporting_agents=[],routing_reason='fixture',routing_confidence=.9,escalated=False,latency_ms=1)
        intent=SimpleNamespace(intent=IntentCategory.OTHER,intent_group='other',urgency=UrgencyLevel.LOW,entities={},confidence=.8,source_scores={})
        self.fake=SimpleNamespace(recognize_intent=AsyncMock(return_value=intent),run=AsyncMock(return_value=self.result))
        for p in [patch.object(main,'_store',self.store),patch.object(main,'_orchestrator',self.fake),patch.object(main,'_chat_locks',{}),patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'not_searched')))]:
            p.start();self.addCleanup(p.stop)

    def req(self,text,intent=IntentCategory.PAYMENT_ISSUE):
        return Request(message=text,user_id='acceptance',conv_id=self.conv['id'],intent=intent,intent_confidence=.9,urgency=UrgencyLevel.LOW,entities=self.rec._extract_entities(text))

    async def chat(self,text,kind='staff_action'):
        return await main.chat(main.ChatRequest(message=text,user_id='acceptance',conv_id=self.conv['id'],input_kind=kind,action='custom' if kind=='staff_action' else None))

    async def test_A01_composite_domains_are_both_routed(self):
        text='主要是支付后重复扣款；另有无法登录、页面401和应用崩溃。'
        self.assertEqual(set(self.orch._route_decision(self.req(text)).agent_types),{AgentType.BILLING,AgentType.TECHNICAL})

    async def test_A02_staff_followup_keeps_hypothesis_separate(self):
        await self.chat('假设客户登录失败且重复扣款，练习编号CASE-ALPHA。')
        self.store.append(self.conv['id'],'note','PRIVATE-NOTE-NEVER-PROMPT')
        await self.chat('继续刚才练习，假设现在登录恢复但资金待核实。')
        context=self.fake.run.call_args.args[0].context
        self.assertIn('CASE-ALPHA',context);self.assertIn('假设',context)
        self.assertIn('不是客户事实',context);self.assertNotIn('PRIVATE-NOTE-NEVER-PROMPT',context)
        self.assertEqual(build_memory(self.store,self.conv['id'])['customer_message_count'],0)

    async def test_A03_refund_source_version_is_traceable(self):
        source=dict(document_id='refund-test',title='测试退款规则',version=2,content='已发货需先退货。申请审核与资金到账是不同环节。',citation=1)
        with patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=(source['content'],[source],'matched'))):
            result=await self.chat('已发货订单如何退货退款，请区分审核和到账。')
        self.assertEqual(result.sources[0]['version'],2);self.assertEqual(result.knowledge_mode,'test')
        self.assertIn(source['content'],self.fake.run.call_args.args[0].context)

    async def test_A04_no_match_lists_specific_policy_gaps(self):
        with patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=('',[],'no_match'))):
            result=await self.chat('巴西跨境订单进口税会退吗、汇率损失谁承担、晚到有三倍赔偿吗？')
        self.fake.run.assert_not_awaited()
        for topic in ['进口税','汇率损失','三倍赔偿']:self.assertIn(topic,result.response)
        self.assertNotIn('签收',result.response)

    async def test_A05_collaboration_scopes_domains_and_combines_once(self):
        captured=[]
        async def execute(req,at):
            captured.append((at,req));return AgentResponse(at,'资金核对段' if at==AgentType.BILLING else '技术排查段',True)
        self.orch._execute=execute
        result=await self.orch.run_parallel(self.req('重复扣款且无法登录'),RoutingDecision(AgentType.BILLING,[AgentType.TECHNICAL]))
        self.assertEqual(len(captured),2)
        for at,req in captured:self.assertIn('仅负责',req.context)
        self.assertNotIn('[billing - 主处理]',result.response)
        self.assertEqual(result.response.count('资金核对段'),1);self.assertEqual(result.response.count('技术排查段'),1)
        self.assertIn('联合处理方案',result.response)

    async def test_A06_error_code_variants_and_false_positives(self):
        for text in ['页面401','401错误','HTTP 401','错误码：401','报错E401','error e401']:
            with self.subTest(text=text):self.assertTrue(self.rec._extract_entities(text)['error_code'])
        for text in ['订单1401','订单号ORDER401XYZ','金额401元','电话13800000401']:
            with self.subTest(text=text):self.assertFalse(self.rec._extract_entities(text)['error_code'])

    async def test_A07_single_domain_and_negative_mentions(self):
        for text,intent,expected in [('无法登录，报错401',IntentCategory.TECHNICAL_LOGIN,AgentType.TECHNICAL),('支付后重复扣款',IntentCategory.PAYMENT_ISSUE,AgentType.BILLING),('只处理登录失败，不涉及退款、扣款和支付。',IntentCategory.TECHNICAL_LOGIN,AgentType.TECHNICAL)]:
            self.assertEqual(self.orch._route_decision(self.req(text,intent)).agent_types,[expected])

    async def test_recovered_technical_issue_does_not_trigger_unnecessary_agent_on_redraft(self):
        text='现在登录已经恢复，应用也不崩溃了；重复扣款仍需核实，两笔交易都显示成功。'
        for old_intent in [IntentCategory.PAYMENT_ISSUE,IntentCategory.TECHNICAL_CRASH]:
            self.assertEqual(self.orch._route_decision(self.req(text,old_intent)).agent_types,[AgentType.BILLING])
    async def test_recovered_login_with_new_active_crash_still_routes_both(self):
        text='登录已经恢复，但应用现在再次崩溃，另外重复扣款仍需核实。'
        self.assertEqual(set(self.orch._route_decision(self.req(text)).agent_types),{AgentType.BILLING,AgentType.TECHNICAL})

    async def test_A08_customer_correction_overrides_current_issue(self):
        self.store.append(self.conv['id'],'user','同一订单重复扣款。')
        latest=self.store.append(self.conv['id'],'user','更正：不是重复扣款，是支付失败。')
        memory=build_memory(self.store,self.conv['id'])
        self.assertEqual(memory['current_issues']['payment']['state'],'payment_failed')
        self.assertEqual(memory['current_issues']['payment']['message_id'],latest['id'])
        self.assertEqual(len(memory['excerpts']),2)

    async def test_A09_three_turn_state_is_not_a_verified_resolution(self):
        for text in ['无法登录，且重复扣款。','现在登录已经恢复，但两笔交易都显示成功，尚未提供流水。','两笔交易分别对应不同订单，不是重复扣款。']:
            self.store.append(self.conv['id'],'user',text)
        memory=build_memory(self.store,self.conv['id'])
        self.assertEqual(memory['current_issues']['technical']['state'],'customer_reports_recovered')
        self.assertEqual(memory['current_issues']['payment']['state'],'different_orders')
        self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'open')
        self.assertNotIn('customer_result',self.store.get('conversation',self.conv['id']))

    async def test_A10_staff_hypothesis_does_not_mutate_customer_facts(self):
        self.store.append(self.conv['id'],'user','退款仍在核对。')
        await self.chat('假设客户已经收到退款，请讨论该假设后续怎么处理。')
        memory=build_memory(self.store,self.conv['id'])
        self.assertEqual(memory['customer_message_count'],1)
        self.assertNotIn('已经收到',str(memory));self.assertNotIn('customer_result',self.store.get('conversation',self.conv['id']));self.assertEqual(self.store.get('conversation',self.conv['id'])['status'],'open')

    async def test_A11_partial_sources_separate_known_and_unknown(self):
        source=dict(document_id='refund',title='退款规则',version=1,content='已发货先退货，审核后按原渠道退回。',citation=1)
        with patch.object(main,'_retrieve_knowledge',AsyncMock(return_value=(source['content'],[source],'matched'))):
            result=await self.chat('已发货怎么退款，进口税也退吗，汇率损失谁承担？')
        self.assertTrue(result.knowledge_used)
        self.assertIn('进口税',result.response);self.assertIn('汇率损失',result.response)
        self.assertIn('依据不足',self.fake.run.call_args.args[0].context)

    async def test_A12_archived_and_old_sources_are_rejected(self):
        for id,version,deleted in [('old',2,False),('archived',1,True),('current',3,False)]:
            self.store.put('document',dict(id=id,version=version,deleted=deleted,scope='business',published_version=version))
        candidates=[dict(document_id=id,version=version,score=.9,title=id,content='规则',source='受控测试资料',chunk=0) for id,version in [('old',1),('archived',1),('current',3)]]
        manager=SimpleNamespace(search_with_rewrite=AsyncMock(return_value=SimpleNamespace(success=True,data=candidates)))
        with patch.object(main,'_tool_manager',manager):
            _,sources,status=await REAL_RETRIEVE('退款规则',mode='business')
        self.assertEqual([s['document_id'] for s in sources],['current']);self.assertEqual(status,'matched')

    async def test_A13_failed_branch_is_visible_in_result_and_journal(self):
        async def execute(req,at):return AgentResponse(at,'资金核对成功' if at==AgentType.BILLING else '未完成',at==AgentType.BILLING)
        self.orch._execute=execute
        result=await self.orch.run_parallel(self.req('扣款且登录报错'),RoutingDecision(AgentType.BILLING,[AgentType.TECHNICAL]))
        self.assertEqual(getattr(result,'execution_status','completed'),'degraded')
        self.assertIn('未完成',result.response);self.assertIn('资金核对成功',result.response)
        from core.execution_calls import ExecutionCalls
        calls=ExecutionCalls(self.store,'isolated');await calls.run(self.req('测试'),'回复准备',AsyncMock(return_value=result))
        summary=calls.summary();self.assertEqual(summary['recent'][0]['state'],'degraded')
        self.assertEqual(summary['totals']['completed'],0)
