# -*- coding: utf-8 -*-
"""A browseable synthetic project over persisted demo cases, with local plan reviews."""
import hashlib,json
from datetime import datetime,timedelta
from core.operations import Operations,read,records,write
from core.workbench import now

TEMPLATES=('late','missing','knowledge')
LABELS={'late':'物流晚到核对','missing':'缺件追补与回访','knowledge':'材料规则统一'}

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def project_id(workspace_id):return 'demo-project-'+digest(workspace_id)[:20]

def current_cases(db,workspace_id):
    cases=[]
    for key in TEMPLATES:
        session=read(db,'demo_session',workspace_id+':'+key)
        conv=read(db,'conversation',session['conv_id']) if session else None
        if conv and conv.get('is_demo') and conv.get('workspace_id')==workspace_id:cases.append(conv)
    return cases

def valid_case(db,project,conv_id):
    conv=read(db,'conversation',conv_id)
    if not conv or not conv.get('is_demo') or conv.get('workspace_id')!=project['workspace_id'] or conv.get('demo_template') not in TEMPLATES:raise KeyError('来源不属于当前演示项目')
    return conv

def source_detail(db,project,source_id):
    kind,sep,id=source_id.partition(':')
    if not sep:raise KeyError('来源不存在')
    if kind in {'customer','order'}:
        conv=valid_case(db,project,id)
        if kind=='customer':
            messages=[json.loads(r[0]) for r in db.execute('SELECT data FROM messages WHERE conv_id=? ORDER BY seq',(id,))]
            data=next((m for m in messages if m['role']=='user' and m.get('kind')!='staff_action'),None)
            title='客户原始诉求 · '+LABELS[conv['demo_template']]
        else:
            data=read(db,'demo_order',conv.get('order_id',''));title='合成订单 · '+(data or {}).get('display_id','')
    else:
        record_kind={'material':'material','attachment':'attachment','policy':'demo_document','gap':'knowledge_gap','recheck':'knowledge_recheck'}.get(kind)
        if not record_kind:raise KeyError('来源类型不存在')
        data=read(db,record_kind,id)
        if not data or not data.get('is_demo') or data.get('workspace_id')!=project['workspace_id']:raise KeyError('来源不在当前演示空间')
        if kind=='policy':
            conv=next((c for c in records(db,'conversation') if c.get('workspace_id')==project['workspace_id'] and c.get('is_demo') and c.get('demo_template') in TEMPLATES and id in c.get('demo_policy_ids',[])),None)
            if not conv:raise KeyError('规则未关联本项目案例')
            title=data['title']
        else:
            conv=valid_case(db,project,data['conv_id'])
            title={'material':data.get('name'),'attachment':data.get('filename'),'gap':data.get('question'),'recheck':data.get('document_title','规则')+' · 回查结论'}[kind]
    if not data:raise KeyError('原始记录不存在')
    return dict(id=source_id,kind=kind,title=title,conv_id=conv['id'],case_label=LABELS[conv['demo_template']],data=data,is_demo=True)

def source_summary(detail):
    d=detail['data'];kind=detail['kind'];status_names={'missing':'待收集','received':'已收到，待核验','verified':'已核验','waived':'已豁免','withdrawn':'已撤回','resolved':'已补齐','pending':'待回查','reviewed':'已回查','not_applicable':'不适用'}
    text=d.get('content') or d.get('note') or d.get('source_note') or status_names.get(d.get('status'),d.get('status',''))
    if kind=='order':text=f"预计 {(d.get('estimated_at') or '')[:10]} · 实际 {(d.get('delivered_at') or '')[:10]} · {d.get('total')} {d.get('currency','BRL')}"
    if kind=='material':text=status_names.get(d['status'],d['status'])+' · '+('必要材料' if d.get('required') else '补充材料')
    return dict(id=detail['id'],kind=kind,title=detail['title'],conv_id=detail['conv_id'],case_label=detail['case_label'],summary=str(text)[:200],version=d.get('version'),revision=d.get('revision'),updated_at=d.get('updated_at') or d.get('created_at'),digest=digest(d))

def snapshots(db,project,ids):return [source_summary(source_detail(db,project,id)) for id in ids]

def ensure_project(db,ws,actor):
    id=project_id(ws['id']);project=read(db,'demo_project',id)
    if not project:
        project=dict(id=id,user_id=actor,workspace_id=ws['id'],is_demo=True,title='售后服务改进示例项目',goal='把物流晚到、缺件追补和材料规则统一三条事项，推进到有依据的处理意见与客户确认。',owner_label='当前体验者 · 项目负责人',created_at=now(),target_at=(datetime.fromisoformat(now())+timedelta(days=7)).isoformat(),scope='合成演示项目；方案审批仅在本机留痕，不执行真实退款、补发或通知。')
        write(db,'demo_project',project)
    for conv in current_cases(db,ws['id']):
        key=conv['demo_template']
        if key not in {'missing','knowledge'}:continue
        approval_id='demo-approval-'+digest([id,conv['id']])[:24]
        if read(db,'demo_approval',approval_id):continue
        source_ids=['customer:'+conv['id'],'order:'+conv['id']]+['policy:'+x for x in conv.get('demo_policy_ids',[])]
        if key=='missing':source_ids += ['material:'+m['id'] for m in records(db,'material') if m['conv_id']==conv['id']]+['attachment:'+a['id'] for a in records(db,'attachment') if a['conv_id']==conv['id'] and not a.get('archived')]
        else:source_ids += ['gap:'+g['id'] for g in records(db,'knowledge_gap') if g['conv_id']==conv['id']]+['recheck:'+r['id'] for r in records(db,'knowledge_recheck') if r['conv_id']==conv['id']]
        evidence=snapshots(db,project,source_ids);approved=key=='knowledge';stamp=conv.get('updated_at',now())
        plan='核对已有材料；仍缺的数量说明继续追补，已核验的材料不重复索要。由当前负责客服回访并确认处理意愿，未核验前不结案，不提前承诺补发。' if key=='missing' else '统一材料核对口径：已有照片不重复收集，缺少的数量说明继续追补；回查原事项后由客服继续跟进。'
        approval=dict(id=approval_id,project_id=id,user_id=actor,workspace_id=ws['id'],is_demo=True,conv_id=conv['id'],title='缺件追补与回访计划' if key=='missing' else '材料口径与回查结论复核',plan=plan,status='approved' if approved else 'pending',revision=1,submitted_by='示例·当班客服' if key=='missing' else '示例·知识维护人员',approver_label='当前体验者 · 示例主管',created_at=stamp,updated_at=stamp,due_at=(datetime.fromisoformat(now())+timedelta(days=1)).isoformat(),source_ids=source_ids,request_sources=evidence,request_hash=digest(evidence),history=[dict(at=stamp,actor='示例·当班客服',action='submit',note='预置演示申请：请核对计划及其来源',demo_seed=True,plan=plan,sources=evidence)])
        if approved:
            approval['history'].append(dict(at=stamp,actor='示例·主管',action='approve',note='预置演示结论：同意统一核对口径，保留客户跟进。此记录不代表正式业务审核。',demo_seed=True,plan=plan,sources=evidence));approval['decision_sources']=evidence;approval['decision_hash']=digest(evidence)
        write(db,'demo_approval',approval)
    return project

class DemoProjects:
    def __init__(self,store):self.store=store;self.ops=Operations(store)
    def owned(self,actor,workspace_id):
        project=self.ops.owned('demo_project',project_id(workspace_id),actor,workspace_id)
        if not project.get('is_demo'):raise KeyError('当前不是演示项目')
        return project
    def get(self,actor,workspace_id):
        project=self.owned(actor,workspace_id)
        with self.store.connect() as db:
            db.execute('BEGIN');return self.build(db,project)
    def source(self,actor,workspace_id,source_id):
        project=self.owned(actor,workspace_id)
        with self.store.connect() as db:return source_detail(db,project,source_id)
    def build(self,db,project):
        cases=current_cases(db,project['workspace_id']);ids={c['id'] for c in cases};todos=[];events=[];sources=[];case_views=[]
        all_tickets=records(db,'ticket');all_materials=records(db,'material');all_gaps=records(db,'knowledge_gap');all_rechecks=records(db,'knowledge_recheck');all_attachments=records(db,'attachment')
        def event(at,title,kind,conv_id,actor='示例记录',note='',seed=False):
            if at:events.append(dict(at=at,title=title,kind=kind,conv_id=conv_id,actor=actor if actor.startswith('示例') or actor=='系统' else '当前体验者',note=note[:500],demo_seed=seed))
        for c in cases:
            key=c['demo_template'];tickets=[t for t in all_tickets if t['conv_id']==c['id']];materials=[m for m in all_materials if m['conv_id']==c['id']];gaps=[g for g in all_gaps if g['conv_id']==c['id']];rechecks=[r for r in all_rechecks if r['conv_id']==c['id']]
            messages=[json.loads(r[0]) for r in db.execute('SELECT data FROM messages WHERE conv_id=? ORDER BY seq',(c['id'],))]
            confirmed=c['status']=='resolved' and (c.get('customer_result') or {}).get('status')=='confirmed'
            steps=[('受理并关联合成订单',bool(c.get('order_id') and any(m['role']=='user' for m in messages)))]
            if key=='late':steps += [('核对订单时效',bool(read(db,'demo_order',c.get('order_id','')))),('采用有依据的回复',any(m.get('review_state')=='adopted' for m in messages))]
            elif key=='missing':steps += [('接班同事接受交接',any((t.get('handoff') or {}).get('state')=='accepted' for t in tickets)),('必要材料完成核验',bool(materials) and all(m['status'] in {'verified','waived','withdrawn'} for m in materials if m.get('required')))]
            else:
                steps=[('登记原始知识缺口',bool(gaps)),('关联当前演示规则',any(g['status']=='resolved' and g.get('document_id') in c.get('demo_policy_ids',[]) for g in gaps)),('记录相关事项回查结论',bool(rechecks) and all(r['status'] in {'reviewed','not_applicable'} for r in rechecks))]
            steps += [('内部完成且客户确认结果',confirmed)]
            case_views.append(dict(id=c['id'],template_id=key,title=LABELS[key],generation=c.get('demo_generation',1),status=c['status'],customer_status=(c.get('customer_result') or {}).get('status','unrecorded'),completed=sum(done for _,done in steps),total=len(steps),steps=[dict(title=t,done=d) for t,d in steps],updated_at=c['updated_at']))
            for t in tickets:
                if t['status']!='resolved':todos.append(dict(id='ticket:'+t['id'],kind='ticket',conv_id=c['id'],record_id=t['id'],case_label=LABELS[key],title=t.get('next_action') or '继续处理关联工单',owner='当前负责客服',due_at=t.get('due_at'),priority=t.get('priority','normal')))
                for h in t.get('history',[]):event(h.get('at'),h.get('action','工单处理'),'ticket',c['id'],h.get('actor','示例记录'),seed=str(h.get('action','')).startswith('演示预置'))
            r=c.get('customer_result') or {}
            if r.get('status') in {'pending','unreachable','disputed'}:todos.append(dict(id='customer:'+c['id'],kind='customer',conv_id=c['id'],case_label=LABELS[key],title=r.get('next_action') or '确认客户处理结果',owner='当前负责客服',due_at=r.get('due_at'),priority='normal'))
            for m in materials:
                if m['status'] in {'missing','received'}:todos.append(dict(id='material:'+m['id'],kind='material',record_id=m['id'],conv_id=c['id'],case_label=LABELS[key],title=m['name']+' · '+('待收集' if m['status']=='missing' else '待人工核验'),owner='当前负责客服',due_at=m.get('due_at'),priority='normal'))
                for h in m.get('history',[]):event(h.get('at'),'材料：'+m['name'],'material',c['id'],h.get('actor','示例记录'),h.get('note',''),str(h.get('note','')).startswith('演示预置'))
            for r in rechecks:
                if r['status']=='pending':todos.append(dict(id='recheck:'+r['id'],kind='recheck',record_id=r['id'],conv_id=c['id'],case_label=LABELS[key],title='回查规则更新对原事项的影响',owner='当前负责客服',due_at=None,priority='normal'))
            for g in gaps:
                for h in g.get('history',[]):event(h.get('at'),'知识缺口进展','gap',c['id'],h.get('actor','示例记录'),h.get('note',''),str(h.get('note','')).startswith('演示预置'))
            for r in rechecks:
                for h in r.get('history',[]):event(h.get('at'),'记录知识回查结论','recheck',c['id'],h.get('actor','示例记录'),h.get('note',''),str(h.get('note','')).startswith('演示预置'))
            for h in c.get('case_history',[]):event(h.get('at'),h.get('action','事项更新'),'case',c['id'],h.get('actor','示例记录'),seed=str(h.get('action','')).startswith('演示预置'))
            for h in c.get('customer_result_history',[]):event(h.get('recorded_at'),'记录客户结果','customer',c['id'],h.get('recorded_by','示例记录'),h.get('note',''),h.get('source')=='demo_seed')
            source_ids=['customer:'+c['id'],'order:'+c['id']]+['policy:'+p for p in c.get('demo_policy_ids',[])]+['material:'+m['id'] for m in materials]+['attachment:'+a['id'] for a in all_attachments if a['conv_id']==c['id']]+['gap:'+g['id'] for g in gaps]+['recheck:'+r['id'] for r in rechecks]
            for id in source_ids:sources.append(source_summary(source_detail(db,project,id)))
        approvals=[];past=[]
        for a in records(db,'demo_approval'):
            if a.get('project_id')!=project['id']:continue
            current=snapshots(db,project,a['source_ids']);public=dict(a,context_hash=digest(current),current_sources=current,historical=a['conv_id'] not in ids,source_changed=digest(current)!=(a.get('decision_hash') if a['status']=='approved' else a.get('request_hash')))
            if public['historical']:past.append(public);continue
            approvals.append(public)
            if a['status'] in {'pending','returned'}:todos.append(dict(id='approval:'+a['id'],kind='approval',record_id=a['id'],conv_id=a['conv_id'],case_label='项目方案复核',title=a['title']+' · '+('待主管复核' if a['status']=='pending' else '待补充后重提'),owner='当前体验者 · 示例主管',due_at=a.get('due_at'),priority='normal'))
            for h in a['history']:event(h.get('at'),{'submit':'提交方案复核','approve':'方案复核通过','return':'方案退回补充','resubmit':'补充方案并重新提交'}.get(h['action'],'方案处理'),'approval',a['conv_id'],h['actor'],h['note'],h.get('demo_seed',False))
        approvals.sort(key=lambda a:(a['status']=='approved',a['created_at']));todos.sort(key=lambda t:t.get('due_at') or '9999');events.sort(key=lambda e:e['at'],reverse=True)
        completed=sum(c['completed'] for c in case_views);total=sum(c['total'] for c in case_views);status='completed' if completed==total and all(a['status']=='approved' for a in approvals) else 'in_progress'
        return dict(project,status=status,completed=completed,total=total,cases=case_views,todos=todos,approvals=approvals,past_approvals=past,sources=sources,events=events,approval_pending=sum(a['status'] in {'pending','returned'} for a in approvals),approval_approved=sum(a['status']=='approved' for a in approvals))
    def decide(self,actor,workspace_id,id,body):
        project=self.owned(actor,workspace_id)
        if project['user_id']!=actor:raise ValueError('请由此演示项目的体验者以示例主管身份复核')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');a=read(db,'demo_approval',id)
            if not a or a.get('project_id')!=project['id']:raise KeyError('审批记录不属于当前项目')
            if a['conv_id'] not in {c['id'] for c in current_cases(db,workspace_id)}:raise ValueError('此审批属于以前轮次，仅供查看；请在当前轮次继续复核')
            if a['revision']!=body['expected_revision']:raise ValueError('方案已被更新，请刷新核对；未提交说明仍可保留')
            sources=snapshots(db,project,a['source_ids']);hash=digest(sources)
            if hash!=body['expected_context_hash']:raise ValueError('关联材料或规则已更新，请刷新来源后重新核对再审批')
            action=body['action'];plan=body.get('plan') or a['plan']
            if action not in {'approve','return','resubmit'}:raise ValueError('不支持此审批操作')
            if action=='resubmit':
                if a['status']!='returned':raise ValueError('仅已退回的方案可以补充后重新提交')
                a.update(status='pending',plan=plan,request_sources=sources,request_hash=hash)
            else:
                if a['status']!='pending':raise ValueError('仅待复核的方案可以通过或退回')
                a.update(status='approved' if action=='approve' else 'returned',decision_sources=sources,decision_hash=hash)
            a['history'].append(dict(at=now(),actor=actor,action=action,note=body['note'],plan=plan,sources=sources,demo_seed=False));a.update(revision=a['revision']+1,updated_at=now());write(db,'demo_approval',a)
            return a
