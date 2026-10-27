"""Transactional local service operations. Explicit opt-in team spaces; personal history stays private."""
import json
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from core.workbench import now

SHANGHAI=ZoneInfo('Asia/Shanghai')

def read(db,kind,id):
    row=db.execute('SELECT data FROM records WHERE kind=? AND id=?',(kind,id)).fetchone()
    return json.loads(row[0]) if row else None

def records(db,kind):
    return [json.loads(r[0]) for r in db.execute('SELECT data FROM records WHERE kind=?',(kind,))]

def write(db,kind,data):
    db.execute('INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',(kind,data['id'],json.dumps(data,ensure_ascii=False)))
    return data

def access(store,record,actor,workspace_id=None):
    if not record:return False
    space=record.get('workspace_id')
    if space:
        ws=store.get('workspace',space)
        return space==workspace_id and bool(ws and any(m['id']==actor for m in ws['members']))
    return not workspace_id and record.get('user_id')==actor

def scope_key(actor,workspace_id=None):
    return 'team:'+workspace_id if workspace_id else 'personal:'+actor

class Operations:
    def __init__(self,store):self.store=store

    def require_space(self,actor,workspace_id=None):
        if workspace_id:
            ws=self.store.get('workspace',workspace_id)
            if not ws or not any(m['id']==actor for m in ws['members']):raise KeyError('工作空间不存在或不是成员')
            return ws

    def visible(self,kind,actor,workspace_id=None):
        self.require_space(actor,workspace_id)
        return [r for r in self.store.list(kind) if access(self.store,r,actor,workspace_id)]

    def owned(self,kind,id,actor,workspace_id=None):
        record=self.store.get(kind,id)
        if not access(self.store,record,actor,workspace_id):raise KeyError('记录不存在或不在当前工作空间')
        return record

    def workspace(self,actor,name):
        return self.store.put('workspace',dict(id='ws-'+uuid.uuid4().hex[:12],name=name,created_at=now(),
            members=[dict(id=actor,role='supervisor')],scope='本机协作空间；身份切换不是企业登录认证'))

    def member(self,actor,workspace_id,member_id,role):
        self.require_space(actor,workspace_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');ws=read(db,'workspace',workspace_id)
            if ws.get('is_demo'):raise ValueError('示例练习空间成员固定，请在普通协作空间维护真实成员')
            if not any(m['id']==actor and m['role']=='supervisor' for m in ws['members']):raise ValueError('只有本地空间主管可维护成员')
            prior=next((m for m in ws['members'] if m['id']==member_id),None)
            if prior and prior['role']=='supervisor' and role!='supervisor' and sum(m['role']=='supervisor' for m in ws['members'])==1:raise ValueError('至少保留一位主管')
            ws['members']=[m for m in ws['members'] if m['id']!=member_id]+[dict(id=member_id,role=role)]
            return write(db,'workspace',ws)

    def check_owner(self,actor,workspace_id,owner):
        ws=self.require_space(actor,workspace_id)
        if ws and owner!='待分派' and not any(m['id']==owner for m in ws['members']):raise ValueError('负责人必须是当前空间成员')

    def ticket(self,conv,summary,review_id=''):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=next((t for t in records(db,'ticket') if t['conv_id']==conv['id']),None)
            if existing:return existing
            record=self.ticket_record(conv,summary,review_id)
            write(db,'ticket',record)
            current=read(db,'conversation',conv['id']);current.update(status='pending',updated_at=now());write(db,'conversation',current)
            return record

    @staticmethod
    def ticket_record(conv,summary,review_id=''):
        return dict(id='EM-'+uuid.uuid4().hex[:8].upper(),conv_id=conv['id'],user_id=conv['user_id'],workspace_id=conv.get('workspace_id'),
            is_demo=bool(conv.get('is_demo')),title=conv['title'],order_id=conv.get('order_id',''),review_id=review_id,owner=conv.get('owner','待分派'),status='open',
            priority='normal',wait_reason='',next_action='',due_at=None,resolution='',revision=1,summary=summary[:3000],
            created_at=now(),updated_at=now(),scope='本地演示工单；未通知外部平台、未执行退款',
            history=[dict(at=now(),action='创建本地工单',owner=conv.get('owner','待分派'),actor=conv['user_id'])])

    def feedback_case(self,actor,review_id,workspace_id=None):
        ws=self.require_space(actor,workspace_id)
        if ws and ws.get('is_demo'):raise ValueError('演示空间仅保留合成案例，请退出演示后受理历史反馈')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');review=read(db,'review',review_id)
            if not review:raise KeyError('评价不存在')
            existing=next((c for c in records(db,'conversation') if c.get('review_id')==review_id and scope_key(c['user_id'],c.get('workspace_id'))==scope_key(actor,workspace_id)),None)
            if existing:
                ticket=next((t for t in records(db,'ticket') if t['conv_id']==existing['id']),None)
                return dict(conversation=existing,ticket=ticket,already_exists=True)
            order_id=review['order_id']
            conv=dict(id=str(uuid.uuid4()),user_id=actor,workspace_id=workspace_id,review_id=review_id,
                title=f"{review['score']}星客户反馈 · 订单 {order_id[-6:]}",source='Olist真实历史评价',knowledge_mode='business',
                order_id=order_id,status='pending',owner='待分派',created_at=now(),updated_at=now(),preview=review['content'][:100],
                intake=dict(issue_type='complaint',desired_outcome='',quantity=None,evidence_note=''))
            write(db,'conversation',conv)
            msg=dict(id=str(uuid.uuid4()),role='user',content=review['content'],created_at=now(),source='真实葡萄牙语评价原文',
                source_created_at=review.get('created_at'),kind='customer_input')
            db.execute('INSERT INTO messages(conv_id,data) VALUES(?,?)',(conv['id'],json.dumps(msg,ensure_ascii=False)))
            ticket=self.ticket_record(conv,f"真实历史评价（非政策）：{review['content']}\n评分：{review['score']}/5。核对订单后记录本地处理意见。",review_id)
            write(db,'ticket',ticket)
            return dict(conversation=conv,ticket=ticket,already_exists=False)

    def patch_conversation(self,id,actor,patch,workspace_id=None):
        current=self.owned('conversation',id,actor,workspace_id)
        if current.get('is_demo') and patch.get('knowledge_mode','test')!='test':raise ValueError('演示案例仅使用当前案例的隔离演示规则')
        if 'owner' in patch:self.check_owner(actor,workspace_id,patch['owner'])
        if patch.get('order_id'):
            linked=self.store.get('demo_order' if current.get('is_demo') else 'order',patch['order_id'])
            if not linked or (current.get('is_demo') and linked.get('workspace_id')!=workspace_id):raise KeyError('订单不在当前范围')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');conv=read(db,'conversation',id);tickets=[t for t in records(db,'ticket') if t['conv_id']==id]
            if workspace_id and 'owner' in patch and patch['owner']!=conv.get('owner'):
                raise ValueError('共享事项请从工单发起交接，由接班同事确认后切换责任人')
            plan=patch.pop('closure_plan',None)
            status=patch.get('status')
            if status=='resolved':
                from core.service_followup import close_guard
                close_guard(db,conv,patch.get('closure_exception',''),plan,actor)
                if any(t['status']!='resolved' for t in tickets):raise ValueError('有关联工单尚未完成，请先处理工单再结案')
                if not patch.get('resolution','').strip():raise ValueError('结案需要填写解决结果')
                conv['resolved_at']=now()
            elif status and conv['status']=='resolved':
                if tickets:raise ValueError('请通过关联工单的“重新打开”继续处理')
                from core.closure_plans import reopen_followup
                reopen_followup(conv,actor,'手动重新打开事项')
                conv.pop('resolved_at',None);conv['resolution']=''
            if 'intake' in patch:patch['intake']={**conv.get('intake',{}),**patch['intake']}
            conv.setdefault('case_history',[]).append(dict(at=now(),actor=actor,action='更新事项',fields=list(patch)))
            conv.update(patch,updated_at=now());write(db,'conversation',conv)
            for ticket in tickets:
                if 'owner' in patch:ticket['owner']=patch['owner']
                if 'order_id' in patch:ticket['order_id']=patch['order_id']
                if 'owner' in patch or 'order_id' in patch:
                    ticket.update(updated_at=now(),revision=ticket.get('revision',1)+1)
                    ticket['history'].append(dict(at=now(),actor=actor,owner=ticket['owner'],action='从事项同步负责人或订单'))
                    write(db,'ticket',ticket)
            return conv

    def update_ticket(self,id,actor,patch,workspace_id=None,reopen=False):
        self.owned('ticket',id,actor,workspace_id)
        self.check_owner(actor,workspace_id,patch.get('owner','待分派'))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');ticket=read(db,'ticket',id)
            expected=patch.pop('expected_revision',None)
            if expected is not None and ticket.get('revision',1)!=expected:raise ValueError('工单已被其他成员更新，请重新加载')
            plan=patch.pop('closure_plan',None);choices=patch.pop('handoff_tasks',None);context_hash=patch.pop('handoff_context_hash',None)
            merged={**ticket,**patch};due=merged.get('due_at')
            if due and (not merged.get('next_action','').strip() or merged.get('owner')=='待分派'):raise ValueError('安排回访需要负责人和下一步行动')
            if workspace_id and 'owner' in patch and patch['owner']!=ticket['owner']:
                target=patch['owner'];space=read(db,'workspace',workspace_id)
                supervisor=any(m['id']==actor and m['role']=='supervisor' for m in space['members'])
                if ticket['owner'] not in {actor,'待分派'} and not supervisor:raise ValueError('只有当前责任人或本地主管可重新分派工单')
                if target not in {actor,'待分派'}:
                    if patch.get('status')=='resolved':raise ValueError('发起交接后需等待对方接受，不能同时结案')
                    prior=ticket.get('handoff') or {}
                    from core.handoff_tasks import make_plan
                    package=make_plan(db,ticket['conv_id'],choices,context_hash)
                    patch['handoff']=dict(state='pending',candidate=target,from_owner=ticket['owner'] if ticket['owner']!='待分派' else actor,
                        requested_by=actor,requested_at=now(),reason=patch.get('note',''),**package)
                    patch['owner']=patch['handoff']['from_owner']
                else:
                    prior=ticket.get('handoff') or {}
                    if target==actor and prior.get('state')=='pending' and prior.get('candidate')==actor:raise ValueError('请使用接受交接操作，逐项确认独立待办责任')
                    patch['handoff']=dict(prior,state='accepted' if target==actor else 'cancelled',candidate=target,decided_by=actor,decided_at=now())
            handoff=patch.get('handoff',ticket.get('handoff')) or {}
            if patch.get('status')=='resolved' and handoff.get('state')=='pending':raise ValueError('交接尚未接受，请先完成交接或退回处理后再结案')
            if handoff.get('state')=='pending' and handoff.get('candidate')==actor and patch.get('status')=='in_progress':raise ValueError('请先接受交接，再开始处理')
            old=ticket['status'];new=patch.get('status',old)
            if reopen:
                if old!='resolved':raise ValueError('只有已解决工单可以重新打开')
                new='pending';patch['status']=new;patch['resolution']='';patch['reopened_count']=ticket.get('reopened_count',0)+1
                ticket.pop('resolved_at',None)
            elif old=='resolved':raise ValueError('已解决工单需要先重新打开')
            note=patch.pop('note').strip()
            if new=='resolved':
                from core.service_followup import close_guard
                close_guard(db,read(db,'conversation',ticket['conv_id']),patch.get('closure_exception',''),plan,actor)
                patch.update(resolution=patch.get('resolution') or note,resolved_at=now())
            ticket['history'].append(dict(at=now(),action=('重新打开：' if reopen else '')+note,actor=actor,
                owner=patch.get('owner',ticket['owner']),previous_status=old,status=new,due_at=due,handoff=patch.get('handoff',ticket.get('handoff'))))
            ticket.update(patch,updated_at=now(),revision=ticket.get('revision',1)+1);write(db,'ticket',ticket)
            conv=read(db,'conversation',ticket['conv_id'])
            if conv:
                if reopen and (conv['status']=='resolved' or (conv.get('customer_result') or {}).get('status')=='confirmed'):
                    from core.closure_plans import reopen_followup
                    reopen_followup(conv,actor,note)
                others=[t for t in records(db,'ticket') if t['conv_id']==conv['id']]
                done=all(t['status']=='resolved' for t in others)
                conv.update(owner=ticket['owner'],status='resolved' if done else 'pending',updated_at=now())
                if done:conv.update(resolution=ticket.get('resolution',''),resolved_at=now())
                else:
                    conv.pop('resolved_at',None);conv['resolution']=''
                    if (conv.get('closure_plan') or {}).get('kind')=='no_followup':conv['closure_plan']['active']=False
                write(db,'conversation',conv)
            return ticket

    def handoff(self,id,actor,action,note,expected_revision,workspace_id=None):
        self.owned('ticket',id,actor,workspace_id)
        if not workspace_id:raise ValueError('交接确认需要共享空间')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');ticket=read(db,'ticket',id);handoff=ticket.get('handoff') or {}
            if ticket.get('revision',1)!=expected_revision:raise ValueError('工单已更新，请刷新后核对交接')
            if ticket['status']=='resolved' or handoff.get('state')!='pending':raise ValueError('当前没有等待确认的交接')
            if handoff.get('candidate')!=actor:raise ValueError('只有被分派的接班同事可以接受或退回交接')
            if action not in {'accept','return'}:raise ValueError('交接动作不支持')
            if not note.strip():raise ValueError('请填写交接核对说明或退回原因')
            handoff.update(state='accepted' if action=='accept' else 'returned',decided_by=actor,decided_at=now(),decision_note=note.strip())
            conv=read(db,'conversation',ticket['conv_id'])
            if action=='accept':
                from core.handoff_tasks import apply_plan
                apply_plan(db,conv,handoff,actor);ticket['owner']=actor
            write(db,'conversation',conv)
            ticket.update(handoff=handoff,status='in_progress' if action=='accept' else 'pending',revision=ticket.get('revision',1)+1,updated_at=now())
            ticket['history'].append(dict(at=now(),actor=actor,owner=ticket['owner'],status=ticket['status'],
                action=('接受交接：' if action=='accept' else '退回交接：')+note.strip(),handoff=dict(handoff)))
            write(db,'ticket',ticket)
            conv=read(db,'conversation',ticket['conv_id'])
            conv.update(owner=ticket['owner'],status='pending',updated_at=now());write(db,'conversation',conv)
            return ticket

    def queue(self,actor,workspace_id=None):
        current=datetime.now(timezone.utc);today=current.astimezone(SHANGHAI).date()
        items=[]
        for ticket in self.visible('ticket',actor,workspace_id):
            due=datetime.fromisoformat(ticket['due_at'].replace('Z','+00:00')) if ticket.get('due_at') else None
            handoff=ticket.get('handoff') or {}
            item=dict(ticket,awaiting_me=ticket['status']!='resolved' and handoff.get('state')=='pending' and handoff.get('candidate')==actor,
                handoff_pending=ticket['status']!='resolved' and handoff.get('state')=='pending',handoff_returned=ticket['status']!='resolved' and handoff.get('state')=='returned',overdue=bool(due and due<current and ticket['status']!='resolved'),
                due_today=bool(due and due.astimezone(SHANGHAI).date()==today and ticket['status']!='resolved'),assigned_to_me=ticket['owner']==actor)
            items.append(item)
        items.sort(key=lambda t:(t['status']=='resolved',not t['overdue'],{'urgent':0,'high':1,'normal':2,'low':3}.get(t.get('priority','normal'),2),t.get('due_at') or '9999',t['created_at']))
        return dict(items=items,as_of=current.isoformat(),timezone='Asia/Shanghai',notification_scope='本地到期待办；未发送外部通知')

    def revise(self,conv_id,message_id,actor,workspace_id=None):
        conv=self.owned('conversation',conv_id,actor,workspace_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            messages=[json.loads(r[0]) for r in db.execute('SELECT data FROM messages WHERE conv_id=? ORDER BY seq',(conv_id,))]
            parent=next((m for m in messages if m['id']==message_id),None)
            from core.assistant_outputs import is_reference
            if parent and is_reference(parent,messages):raise ValueError('客服参考不能创建客户回复修订版，请单独准备草稿')
            if not parent or parent['role']!='assistant' or parent.get('review_state')!='adopted':raise ValueError('请选择已经采用的回复创建修订版')
            msg={k:v for k,v in parent.items() if k not in {'id','created_at','adopted_at','adopted_by','original_content','draft_history','delivery_status','edited_at','demo_seed'}}
            msg.update(id=str(uuid.uuid4()),created_at=now(),review_state='draft',revision=1,parent_message_id=message_id,revision_author=actor)
            db.execute('INSERT INTO messages(conv_id,data) VALUES(?,?)',(conv_id,json.dumps(msg,ensure_ascii=False)))
            conv.update(updated_at=now(),preview='修订草稿：'+msg['content'][:80]);write(db,'conversation',conv)
            return msg

    def report(self,actor,workspace_id=None):
        queue=self.queue(actor,workspace_id)['items'];convs=self.visible('conversation',actor,workspace_id);gaps=self.visible('knowledge_gap',actor,workspace_id)
        return dict(as_of=now(),timezone='Asia/Shanghai',scope='演示空间累计练习记录；不是实际业务指标' if workspace_id and (self.store.get('workspace',workspace_id) or {}).get('is_demo') else '当前个人/协作空间累计记录；本地解决不等于客户确认',
            open_cases=sum(c['status']!='resolved' for c in convs),resolved_cases=sum(c['status']=='resolved' for c in convs),
            awaiting_acceptance=sum(t['handoff_pending'] for t in queue),returned_handoffs=sum(t['handoff_returned'] for t in queue),
            overdue=sum(t['overdue'] for t in queue),due_today=sum(t['due_today'] for t in queue),unassigned=sum(t['owner']=='待分派' and t['status']!='resolved' for t in queue),
            reopened=sum(t.get('reopened_count',0) for t in queue),knowledge_gaps=sum(g['status'] in {'open','pending'} for g in gaps),
            members=[dict(id=member,open=sum(t['owner']==member and t['status']!='resolved' for t in queue),overdue=sum(t['owner']==member and t['overdue'] for t in queue)) for member in sorted(set(t['owner'] for t in queue))],
            definitions={'resolved_cases':'有结案结果且关联工单均已完成的本地事项；不把采用回复计为解决','overdue':'未解决且跟进截止时间早于当前时间的工单','due_today':'上海日期为今天的未完成回访/跟进','reopened':'已解决工单通过重开入口再次进入处理的累计次数','handoff':'分派与接受分开记录；等待接受/退回期间，原责任人继续承担跟进责任'})
