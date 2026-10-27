import asyncio,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from core.workbench import WorkbenchStore
from core.execution_calls import ExecutionCalls
from core.operations import Operations
class ExecutionCallTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=WorkbenchStore(Path(self.tmp.name)/'db');self.ws=Operations(self.store).workspace('alice','示例');self.conv=self.store.conversation('alice');self.conv.update(is_demo=True,workspace_id=self.ws['id']);self.store.put('conversation',self.conv);self.req=SimpleNamespace(user_id='alice',conv_id=self.conv['id'],message='不能进入公开监控的客户原话')
  self.service=ExecutionCalls(self.store,'session1');self.execute=AsyncMock(return_value=SimpleNamespace(agent_types=['general']))
 async def test_real_callback_is_awaited_and_completed_record_persists(self):
  result=await self.service.run(self.req,'回复准备',self.execute);self.execute.assert_awaited_once_with(self.req);s=self.service.summary('alice');self.assertEqual(s['totals']['total'],1);self.assertEqual(s['totals']['completed'],1);self.assertEqual(s['totals']['examples'],1);self.assertGreaterEqual(s['recent'][0]['elapsed_ms'],0);self.assertTrue(s['recent'][0]['can_open']);self.assertEqual(ExecutionCalls(WorkbenchStore(self.store.path),'new').summary()['totals']['total'],1)
 async def test_exception_record_is_not_counted_as_completed(self):
  self.execute.side_effect=RuntimeError('secret upstream detail')
  with self.assertRaises(RuntimeError):await self.service.run(self.req,'客户回复译稿',self.execute)
  s=self.service.summary();self.assertEqual(s['totals']['failed'],1);self.assertEqual(s['totals']['completed'],0);self.assertNotIn('secret',str(s))
 async def test_cancelled_call_is_interrupted(self):
  self.execute.side_effect=asyncio.CancelledError()
  with self.assertRaises(asyncio.CancelledError):await self.service.run(self.req,'回复准备',self.execute)
  self.assertEqual(self.service.summary()['recent'][0]['state'],'interrupted')
 async def test_public_monitor_omits_user_prompt_and_private_record_ids(self):
  await self.service.run(self.req,'回复准备',self.execute);s=self.service.summary('outsider');self.assertNotIn('conv_id',s['recent'][0]);self.assertNotIn('workspace_id',s['recent'][0]);self.assertNotIn('user_id',s['recent'][0]);self.assertNotIn(self.req.message,str(s));self.assertNotIn('message',self.store.list('execution_call')[0])
 async def test_previous_process_running_record_is_unknown_after_restart(self):
  async def unfinished(request):self.assertEqual(ExecutionCalls(self.store,'other').summary()['recent'][0]['state'],'unknown');return SimpleNamespace(agent_types=[])
  await self.service.run(self.req,'回复准备',unfinished);self.assertEqual(self.service.summary()['recent'][0]['state'],'completed')
 async def test_history_is_recent_first_and_bounded(self):
  for _ in range(23):await self.service.run(self.req,'回复准备',self.execute)
  s=self.service.summary();self.assertEqual(s['totals']['total'],23);self.assertEqual(len(s['recent']),20);self.assertGreaterEqual(s['recent'][0]['started_at'],s['recent'][-1]['started_at'])
 async def test_missing_history_is_empty_without_invented_call(self):
  self.assertEqual(self.service.summary()['totals']['total'],0);self.assertIsNone(self.service.summary()['totals']['avg_elapsed_ms']);self.assertEqual(self.service.summary()['recent'],[])
