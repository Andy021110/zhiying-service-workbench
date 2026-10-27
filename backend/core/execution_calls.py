"""Persist assistant execution metadata without retaining prompts in monitoring."""
import asyncio,time,uuid
from core.workbench import now
from core.operations import access

class ExecutionCalls:
    def __init__(self,store,session):self.store=store;self.session=session
    async def run(self,request,purpose,execute):
        conv=self.store.get('conversation',request.conv_id) or {}
        source='synthetic_example' if conv.get('is_demo') else 'historical_practice' if conv.get('practice_key') else 'historical_review' if request.conv_id.startswith('review-translation:') else 'local_workbench'
        record=dict(id='call-'+uuid.uuid4().hex,session=self.session,conv_id=request.conv_id,user_id=request.user_id,workspace_id=conv.get('workspace_id'),purpose=purpose,source=source,example_template=conv.get('demo_template') if conv.get('is_demo') else None,state='running',started_at=now(),finished_at=None,elapsed_ms=None,agent_types=[])
        self.store.put('execution_call',record);start=time.monotonic()
        try:
            result=await execute(request)
        except BaseException as error:
            record.update(state='interrupted' if isinstance(error,asyncio.CancelledError) else 'failed',finished_at=now(),elapsed_ms=round((time.monotonic()-start)*1000,1))
            self.store.put('execution_call',record);raise
        state=getattr(result,'execution_status','completed')
        if state not in {'completed','degraded','failed'}:state='failed'
        record.update(state=state,finished_at=now(),elapsed_ms=round((time.monotonic()-start)*1000,1),agent_types=[getattr(a,'value',str(a)) for a in getattr(result,'agent_types',[])],agent_outcomes=getattr(result,'agent_outcomes',[]),routing_reason=getattr(result,'routing_reason',''))
        self.store.put('execution_call',record);return result
    def summary(self,actor=''):
        records=sorted(self.store.list('execution_call'),key=lambda r:r['started_at'],reverse=True)
        for record in records:
            if record['state']=='running' and record['session']!=self.session:record['state']='unknown'
        finished=[r for r in records if r['state'] in {'completed','degraded','failed','interrupted'}]
        totals=dict(total=len(records),completed=sum(r['state']=='completed' for r in records),failed=sum(r['state']=='failed' for r in records),degraded=sum(r['state']=='degraded' for r in records),pending=sum(r['state'] in {'running','unknown','interrupted'} for r in records),examples=sum(r['source']=='synthetic_example' for r in records),avg_elapsed_ms=round(sum(r['elapsed_ms'] or 0 for r in finished)/len(finished),1) if finished else None)
        recent=[]
        for r in records[:20]:
            public={k:r.get(k) for k in ['id','purpose','source','example_template','state','started_at','finished_at','elapsed_ms','agent_types','agent_outcomes']}
            conv=self.store.get('conversation',r['conv_id'])
            if conv and r['source']=='synthetic_example':public['example_template']=conv.get('demo_template')
            if actor and conv and access(self.store,conv,actor,r.get('workspace_id')):
                public.update(conv_id=conv['id'],workspace_id=conv.get('workspace_id'),case_title=conv.get('title',''),can_open=True)
            recent.append(public)
        return dict(totals=totals,recent=recent,scope='本机已接入记录的助手执行请求；跨服务重启保留。包含合成示例。一次执行可能包含多个底层模型或工具请求，不等于Token或计费请求数。')
