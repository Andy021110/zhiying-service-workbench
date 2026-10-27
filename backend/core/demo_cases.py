# -*- coding: utf-8 -*-
"""Per-viewer, persistent synthetic examples. No business documents or vector writes."""
import hashlib,json,uuid,zlib,struct
from datetime import datetime,timedelta,timezone
from core.operations import Operations,read,records,write,access
from core.workbench import now
from core.demo_projects import ensure_project

TEMPLATES=[
 dict(id='late',title='物流晚到：核对之后继续追问',goal='核对订单时效、准备答复，并处理结案后的新问题。',background='林沐收到商品后发现比预计日期晚，希望确认晚了几天以及后续如何处理。',progress='已核对并记录结果，可以追加新的客户问题。',next_step='继续追问原因、处理办法，或核对之前提供的诉求。',tasks=['T02','T03','T05','T10','T11'],prompts=['你还记得我的诉求是什么吗？','这笔订单比预计晚了几天？','那接下来可以怎么处理？'],milestones=['受理与关联订单','核对预计/实际时间','采用回复并记录结果','追加问题继续对话']),
 dict(id='missing',title='缺件投诉：接班后补齐材料',goal='接着已有材料清单和交接历史继续核对缺件问题。',background='许晴的商品缺少一条连接线，上一班客服已核对外包装照片，并交接给你继续追补配件数量说明。',progress='已接受交接；一项材料已核验，一项仍待补齐。',next_step='查看现有凭证、追问剩余材料，或继续登记客户反馈。',tasks=['T02','T08','F07','F09','F03','F05'],prompts=['我补拍好了，还需要核对什么？','之前已经收到哪些材料？','那接下来谁负责继续联系我？'],milestones=['记录商品与诉求','收到并核验部分材料','接班同事明确接受','继续追补与核对']),
 dict(id='knowledge',title='规则补齐：回到原事项继续处理',goal='理解知识缺口如何关联生效版本，再接着原客户问题回复。',background='周禾曾收到不一致的材料要求。缺口已整理，演示规则v2已关联并完成回查，现在需要继续解释下一步。',progress='知识缺口已补齐，相关事项已回查，仍保留客户跟进。',next_step='核对演示规则和回查结论，再继续说明材料要求与跟进安排。',tasks=['T15','T16','F14','T05','T06'],prompts=['那我现在具体需要补什么？','你还记得我之前遇到的情况吗？','规则更新后，我这个问题接下来怎么推进？'],milestones=['登记规则缺口','整理并确认演示规则v2','回查明确关联事项','继续原客户对话'])]


def demo_order(store,conv):
    if conv.get('is_demo'):
        order=store.get('demo_order',conv.get('order_id',''))
        return order if order and order.get('workspace_id')==conv.get('workspace_id') else None
    return store.get('order',conv.get('order_id',''))


def source_document(store,source,conv):
    if source.get('kind')=='demo_policy':
        if not conv.get('is_demo') or conv.get('knowledge_mode')!='test':return None
        doc=store.get('demo_document',source.get('document_id',''))
        if not doc or doc.get('workspace_id')!=conv.get('workspace_id') or doc['id'] not in conv.get('demo_policy_ids',[]):return None
        return doc
    if conv.get('is_demo'):return None
    return store.get('document',source.get('document_id',''))


def demo_knowledge(store,conv):
    if not conv.get('is_demo'):return None
    sources=[];texts=['[仅限当前演示案例的合成规则，不是真实业务政策]']
    for id in conv.get('demo_policy_ids',[]):
        doc=store.get('demo_document',id)
        if not doc or doc.get('deleted') or doc.get('workspace_id')!=conv.get('workspace_id'):continue
        sources.append(dict(kind='demo_policy',document_id=id,version=doc['version'],title=doc['title'],content=doc['content'],source='隔离的合成演示规则',chunk=0,citation=len(sources)+1))
        texts.append(f"[{len(sources)}] {doc['title']} v{doc['version']}\n{doc['content']}")
    materials=[m for m in store.list('material') if m['conv_id']==conv['id']]
    texts.append('[当前演示记录，状态是本机练习数据]\n'+json.dumps(dict(responsible_contact='当前负责客服' if conv.get('owner') not in {None,'','待分派'} else '待明确责任人',intake=conv.get('intake'),materials=[dict(name=m['name'],status=m['status'],required=m['required']) for m in materials]),ensure_ascii=False))
    texts.append('延续本会话已有客户原话与已采用回复，已知资料不必重新索要。正文引用时使用规则标题和版本，内部文档编号只保留在来源元数据中。新增材料是否齐备以清单与人工核验为准。回答中的处理规则需标注“仅演示规则”；不声称真实发送、退款、补发或通知已经完成。')
    return '\n\n'.join(texts),sources,'matched' if sources else 'no_match'


def evidence_png():
    # Deliberately schematic fixture, never presented as a customer photograph.
    width,height=280,140;rows=[]
    glyphs={'D':['11110','10001','10001','10001','10001','10001','11110'],'E':['11111','10000','10000','11110','10000','10000','11111'],'M':['10001','11011','10101','10101','10001','10001','10001'],'O':['01110','10001','10001','10001','10001','10001','01110']}
    for y in range(height):
        row=bytearray()
        for x in range(width):
            color=(235,240,251)
            if 15<x<265 and 20<y<120:color=(66,86,168)
            col=(x-46)//8;line=(y-43)//8
            if 0<=col<24 and 0<=line<7:
                letter='DEMO'[min(col//6,3)];gx=col%6
                if gx<5 and glyphs[letter][line][gx]=='1':color=(255,255,255)
            row.extend(color)
        rows.append(b'\0'+row)
    def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')


class DemoCases:
    def __init__(self,store):self.store=store;self.ops=Operations(store)
    def workspace_id(self,actor):return 'demo-space-'+hashlib.sha256(actor.encode()).hexdigest()[:20]
    def ensure(self,actor):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');id=self.workspace_id(actor);ws=read(db,'workspace',id)
            if not ws:
                ws=dict(id=id,name='体验示例 · 我的练习空间',is_demo=True,demo_owner=actor,created_at=now(),scope='合成演示数据；独立于正式业务统计',members=[dict(id=actor,role='supervisor'),dict(id='示例·上一班客服',role='agent')]);write(db,'workspace',ws)
            if ws.get('demo_owner')!=actor:raise ValueError('此示例空间不属于当前体验者')
            for template in TEMPLATES:
                session_id=id+':'+template['id'];session=read(db,'demo_session',session_id)
                if not session:
                    conv=self.seed(db,ws,actor,template,1);write(db,'demo_session',dict(id=session_id,workspace_id=id,template_id=template['id'],generation=1,conv_id=conv['id']))
            ensure_project(db,ws,actor)
        return self.catalog(actor)
    def catalog(self,actor):
        id=self.workspace_id(actor);ws=self.store.get('workspace',id)
        if not ws:return dict(workspace_id=None,cases=[],scope='尚未建立演示空间')
        if ws.get('demo_owner')!=actor:raise KeyError('演示空间不可访问')
        result=[]
        for t in TEMPLATES:
            session=self.store.get('demo_session',id+':'+t['id'])
            if not session:continue
            conv=self.ops.owned('conversation',session['conv_id'],actor,id)
            history=[dict(id=c['id'],title=c['title'],generation=c['demo_generation'],updated_at=c['updated_at']) for c in self.store.list('conversation') if c.get('workspace_id')==id and c.get('demo_template')==t['id'] and c['id']!=conv['id']]
            result.append(dict(t,conv_id=conv['id'],generation=session['generation'],status=conv['status'],updated_at=conv['updated_at'],message_count=len(self.store.messages(conv['id'])),history=history))
        return dict(workspace_id=id,cases=result,scope='仅合成演示数据；当前空间累计练习记录不计入其他业务空间')
    def reset(self,actor,template_id,expected):
        id=self.workspace_id(actor);self.ops.require_space(actor,id)
        template=next((t for t in TEMPLATES if t['id']==template_id),None)
        if not template:raise KeyError('示例不存在')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');session=read(db,'demo_session',id+':'+template_id);ws=read(db,'workspace',id)
            if not session or ws.get('demo_owner')!=actor:raise KeyError('示例不存在')
            # A repeated/reset response retry returns the already-created round.
            if session['generation']==expected:
                conv=self.seed(db,ws,actor,template,expected+1);session.update(generation=expected+1,conv_id=conv['id']);write(db,'demo_session',session)
            elif session['generation']<expected:raise ValueError('体验版本不匹配，请刷新')
            ensure_project(db,ws,actor)
        return self.catalog(actor)
    def policy(self,id,actor,workspace_id):
        return self.ops.owned('demo_document',id,actor,workspace_id)
    def guide(self,conv_id,actor,workspace_id):
        conv=self.ops.owned('conversation',conv_id,actor,workspace_id)
        if not conv.get('is_demo'):raise KeyError('当前不是演示案例')
        t=next((t for t in TEMPLATES if t['id']==conv.get('demo_template')),None)
        return dict(template=t,policies=[self.policy(id,actor,workspace_id) for id in conv.get('demo_policy_ids',[])],generation=conv.get('demo_generation'),seed_note='已有对话为预置的合成演示记录；你的后续输入和模型新回复会继续保存在同一会话中。')
    def seed(self,db,ws,actor,t,generation):
        start=datetime.now(timezone.utc)-timedelta(minutes=55)
        def at(minutes):return (start+timedelta(minutes=minutes)).isoformat()
        future=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        id=str(uuid.uuid4());oid='demo-order-'+uuid.uuid4().hex[:12];policy_id='demo-rule-'+id
        order_no='DEMO-'+{'late':'LATE','missing':'PART','knowledge':'RULE'}[t['id']]+'-'+id[:6].upper()
        name={'late':'林沐','missing':'许晴','knowledge':'周禾'}[t['id']]
        initial_status='resolved' if t['id']=='late' else 'pending'
        conv=dict(id=id,user_id=actor,workspace_id=ws['id'],title=t['title']+f' · 第{generation}轮',source='合成演示案例；非真实客户',is_demo=True,
            demo_template=t['id'],demo_generation=generation,demo_policy_ids=[policy_id],knowledge_mode='test',order_id=oid,owner=actor,status=initial_status,
            created_at=at(0),updated_at=at(50),intake=dict(issue_type='logistics' if t['id']=='late' else 'missing',quantity=1,product_id='DEMO-KIT',desired_outcome='核对晚到天数与处理办法' if t['id']=='late' else '核对缺件、材料要求与下一步',evidence_note='仅使用演示凭证和合成记录'))
        scope=dict(user_id=actor,workspace_id=ws['id'],is_demo=True)
        day=datetime.now(timezone.utc).date()
        order=dict(id=oid,display_id=order_no,customer_id='demo-'+name,status='delivered',purchased_at=str(day-timedelta(days=10))+' 10:00:00',estimated_at=str(day-timedelta(days=4))+' 00:00:00',delivered_at=str(day-timedelta(days=1))+' 14:00:00',city='演示城市',state='DEMO',currency='CNY',total=199,items=[dict(product_id='DEMO-KIT',price=199,freight=0)],source='合成演示订单；非实时业务数据',**scope)
        write(db,'demo_order',order)
        rule={'late':'仅演示规则：先核对预计和实际送达日期，按自然日比较。晚到天数本身不能推断赔付资格；需另行人工核对原因和处理意见，不承诺真实退款。',
              'missing':'仅演示规则：缺件核对需要外包装与商品照片、配件数量说明。收到不等于已核验；材料齐备并人工核对后才能准备处理意见。未连接真实补发或退款平台。',
              'knowledge':'仅演示规则v2：统一核对外包装与商品照片、配件数量说明。已有照片不重复索要；缺少的数量说明继续追补，当前事项责任人安排回访。核验完成只代表本地处理意见，不等于真实补发或退款已执行。'}[t['id']]
        version=2 if t['id']=='knowledge' else 1
        policy=dict(id=policy_id,title='演示规则 · '+t['title'].split('：')[0],content=rule,scope='demo',version=version,published_version=version,deleted=False,
            source='合成演示规则；仅此案例可用，不进入业务检索',review_history=[dict(at=at(30 if t['id']=='knowledge' else 4),actor='示例·知识维护人员',action='演示内容确认',version=version,note='预置流程记录，不是正式业务审核')],**scope)
        if t['id']=='knowledge':policy['review_history'][:0]=[dict(at=at(8),actor='示例·知识维护人员',action='整理演示草稿',version=1,note='预置流程：记录不一致的材料要求'),dict(at=at(22),actor='示例·知识维护人员',action='统一演示要求',version=2,note='预置流程：已有照片不重复收集，继续追补数量说明')]
        write(db,'demo_document',policy)
        src=dict(kind='demo_policy',document_id=policy_id,version=version,title=policy['title'],content=rule,source=policy['source'],citation=1,chunk=0)
        source_customer=f'我叫{name}，订单号{order_no}。我的诉求是'+conv['intake']['desired_outcome']+'。'
        dialogues={
          'late':[(source_customer+'商品昨天收到，但比预计时间晚。','user'),('演示时效核对：预计日期与实际日期相差3个自然日。先说明订单事实，不据此承诺补偿。','assistant'),('我已收到商品，只是想确认是不是晚了3天。','user'),('根据演示订单字段，确实晚3个自然日；已保留核对依据，未执行退款或外部通知。','assistant'),('好的，谢谢，请先记下这个结果。','user'),('已记录本地核对结果。你仍可继续提出新问题，系统会保留前面的订单和对话背景。','assistant')],
          'missing':[(source_customer+'包装里少了一条连接线。','user'),('我先登记涉及配件和诉求。仅演示规则要求核对包装照片及数量说明，现阶段不会宣称已补发。','assistant'),('外箱没有破损，包装与商品照片我已经提供了。','user'),('已有演示包装照片已登记并人工核验；配件数量说明仍待补齐。上一班已交接，当前由接班客服继续跟进。','assistant'),('我可以补拍内包装，需要拍哪些位置？','user'),('可以继续补充内包装和配件摆放情况，并说明实际收到的连接线数量。已有照片不用重新提交；补充后仍需人工核验。','assistant')],
          'knowledge':[(source_customer+'之前两位客服让我提供的材料不一样。','user'),('材料要求存在缺口，已登记原问题并保留跟进，不把不确定的要求当成正式规则。','assistant'),('我已经提供包装照片，不希望再重复提交。','user'),('演示规则v2已统一材料要求，并完成相关事项回查。已有照片无需重复提供，仍需补齐配件数量说明，由当前客服继续跟进。','assistant'),('那请保留之前的照片和我的问题，我接着确认下一步。','user'),('已保留之前的对话、演示凭证说明、规则版本和回查结论。后续可以直接基于这些记录继续询问。','assistant')]}
        message_minutes={'late':[0,5,10,20,43,45],'missing':[0,5,10,34,38,40],'knowledge':[0,5,10,40,42,45]}[t['id']]
        for i,(content,role) in enumerate(dialogues[t['id']]):
            msg=dict(id=str(uuid.uuid4()),role=role,content=content,created_at=at(message_minutes[i]),kind='customer_input' if role=='user' else 'reply_draft',demo_seed=True,source='合成演示客户原话' if role=='user' else '预置演示回复；非模型现场生成')
            if role=='assistant':msg.update(review_state='adopted',revision=1,knowledge_mode='test',sources=[src],adopted_by='示例·当班客服',adopted_at=at(message_minutes[i]+1),delivery_status='local_only',knowledge_status='demo_seed')
            if t['id']=='knowledge' and i==1:msg.update(sources=[],knowledge_status='no_match')
            db.execute('INSERT INTO messages(conv_id,data) VALUES(?,?)',(id,json.dumps(msg,ensure_ascii=False)))
        conv['preview']=dialogues[t['id']][-1][0][:100]
        result=dict(status='confirmed' if initial_status=='resolved' else 'pending',occurred_at=at(46),note='演示预置：已核对晚到天数' if initial_status=='resolved' else '演示预置：继续补齐材料并确认处理意见',source='demo_seed',recorded_by='示例·当班客服',recorded_at=at(47),owner='' if initial_status=='resolved' else actor,next_action='' if initial_status=='resolved' else '核对配件数量说明并联系演示客户',due_at=None if initial_status=='resolved' else future)
        conv.update(customer_result=result,customer_result_history=[result],result_revision=1)
        if initial_status=='resolved':conv.update(resolved_at=at(48),resolution='演示预置：已记录订单时效核对结果')
        conv['case_history']=[dict(at=at(0),actor='示例·当班客服',action='演示预置：受理客户原话并关联合成订单'),dict(at=at(44),actor='示例·当班客服',action='演示预置：核对订单时效并记录确认结果' if t['id']=='late' else '演示预置：保留材料与规则依据，继续安排跟进')]
        write(db,'conversation',conv)
        ticket=Operations.ticket_record(conv,'演示事项：'+t['background']);ticket.update(is_demo=True,status=initial_status,owner=actor,created_at=at(3),updated_at=at(48),next_action='记录新的客户问题' if initial_status=='resolved' else '继续核对客户材料和诉求',due_at=None if initial_status=='resolved' else future)
        initial_owner='示例·上一班客服' if t['id']=='missing' else actor
        ticket['history']=[dict(at=at(3),actor=initial_owner,owner=initial_owner,status='open',action='演示预置：创建本地事项'),dict(at=at(15),actor=initial_owner,owner=initial_owner,status='pending',action='演示预置：核对事实，保留下一步跟进')]
        if initial_status=='resolved':ticket['history'].append(dict(at=at(48),actor=actor,owner=actor,status='resolved',action='演示预置：客户确认时效核对结果，内部事项结案'))
        if initial_status=='resolved':ticket.update(resolved_at=at(48),resolution=conv['resolution'])
        if t['id']=='missing':
            ticket['handoff']=dict(state='accepted',candidate=actor,from_owner='示例·上一班客服',requested_by='示例·上一班客服',requested_at=at(29),reason='材料尚未齐备，交给接班客服继续',decided_by=actor,decided_at=at(32),decision_note='演示预置：核对历史和下一步后接受')
            ticket['history'].extend([dict(at=at(29),actor='示例·上一班客服',owner='示例·上一班客服',status='pending',action='演示预置：发起交接，接受前原责任人持续负责'),dict(at=at(32),actor=actor,owner=actor,status='pending',action='演示预置：已核对并接受交接')])
        write(db,'ticket',ticket)
        if t['id'] in {'missing','knowledge'}:
            first=None
            for j,(label,state) in enumerate([('外包装与商品照片','verified'),('配件数量说明','missing')]):
                m=dict(id='mat-'+uuid.uuid4().hex,conv_id=id,name=label,status=state,required=True,owner=actor,due_at=future,created_at=at(6),updated_at=at(26),revision=3 if state=='verified' else 1,history=[dict(at=at(6),actor='示例·上一班客服',note='演示预置：登记材料项',status='missing')],**scope)
                if state=='verified':m['history']+=[dict(at=at(17),actor='示例·上一班客服',note='演示预置：收到占位凭证',status='received'),dict(at=at(26),actor='示例·上一班客服',note='演示预置：占位凭证已核验，不代表真实照片',status='verified')];first=m
                write(db,'material',m)
            content=evidence_png();a=dict(id='att-'+uuid.uuid4().hex,conv_id=id,material_id=first['id'],filename='演示占位凭证-DEMO.png',mime='image/png',size=len(content),sha256=hashlib.sha256(content).hexdigest(),uploaded_by='示例·上一班客服',created_at=at(17),source='demo_seed',source_note='程序生成的DEMO占位凭证，不是真实客户照片',request_id='demo-seed',archived=False,revision=1,history=[],**scope)
            write(db,'attachment',a);db.execute('INSERT INTO attachment_bytes VALUES(?,?)',(a['id'],content))
        if t['id']=='knowledge':
            g=dict(id='gap-'+uuid.uuid4().hex,conv_id=id,source_conv_ids=[id],question='演示：缺件材料要求不一致',original_question='演示：缺件材料要求不一致',owner=actor,status='resolved',document_id=policy_id,created_at=at(8),updated_at=at(33),revision=3,history=[dict(at=at(8),actor=actor,note='演示预置：登记规则缺口',status='open'),dict(at=at(20),actor='示例·知识维护人员',note='演示预置：整理材料要求',status='pending'),dict(at=at(33),actor=actor,note='演示预置：关联隔离的演示规则v2',status='resolved',document_id=policy_id)],**scope)
            write(db,'knowledge_gap',g)
            r=dict(id='recheck-'+hashlib.sha256(f'{policy_id}:{version}:{id}'.encode()).hexdigest()[:32],conv_id=id,document_id=policy_id,document_version=version,document_title=policy['title'],references=['gap:'+g['id']],owner=actor,status='reviewed',note='演示预置：已有照片不重复收集，继续追补数量说明',revision=2,created_at=at(33),updated_at=at(38),reviewed_by=actor,reviewed_at=at(38),history=[dict(at=at(38),actor=actor,note='演示预置：回查完成，继续原事项',status='reviewed',document_version=version)],**scope)
            write(db,'knowledge_recheck',r)
        return conv
