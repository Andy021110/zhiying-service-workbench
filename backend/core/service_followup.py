"""Durable local outcomes, evidence, gap governance and explicit knowledge rechecks."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from core.operations import Operations, access, read, records, write
from core.workbench import now

MAX_FILE=5*1024*1024
TERMINAL_GAPS={'withdrawn','merged'}


def revision(record, expected):
    if expected is not None and record.get('revision',1)!=expected:
        raise ValueError('记录已被更新，请刷新后核对；未提交内容仍可保留')


def stamp(record, actor, note, **fields):
    record.setdefault('history',[]).append(dict(at=now(),actor=actor,note=note,**fields))
    record.update(revision=record.get('revision',1)+1,updated_at=now())


def close_guard(db, conv, exception='', plan=None, actor=''):
    missing=[m for m in records(db,'material') if m['conv_id']==conv['id'] and m.get('required') and m['status'] not in {'verified','waived','withdrawn'}]
    if missing:raise ValueError('必要材料尚未核验，请先核验或逐项记录豁免原因：'+'、'.join(m['name'] for m in missing))
    from core.closure_plans import save_plan
    if plan:
        save_plan(db,conv,actor,plan);return
    result=conv.get('customer_result')
    if not result:raise ValueError('客户结果尚未登记，请明确选择仍需跟进或无需回访，并填写安排或原因')
    from core.closure_plans import has_current_confirmation
    if not has_current_confirmation(conv) and not exception.strip():raise ValueError('本轮客户结果尚未确认，请重新核对客户反馈或明确后续安排；原客户跟进仍保留')


class Followups:
    def __init__(self,store):self.store=store;self.ops=Operations(store)

    def scope(self,conv):
        return dict(user_id=conv['user_id'],workspace_id=conv.get('workspace_id'),**({'is_demo':True} if conv.get('is_demo') else {}))

    @staticmethod
    def valid_document(doc,record):
        if not doc or doc.get('deleted') or not doc.get('published_version'):return False
        if doc.get('is_demo'):return bool(record.get('is_demo') and doc.get('scope')=='demo' and doc.get('workspace_id')==record.get('workspace_id'))
        return doc.get('scope')=='business' and not record.get('is_demo')

    def responsible(self,conv,refs,lookup):
        if not conv.get('workspace_id'):return conv['user_id']
        if conv.get('owner') not in {None,'','待分派'}:return conv['owner']
        for ref in sorted(refs):
            if ref.startswith('gap:'):
                gap=lookup('knowledge_gap',ref[4:]) or {}
                if gap.get('owner') not in {None,'','待分派'}:return gap['owner']
        return conv['user_id']

    def bundle(self,conv_id,actor,workspace_id=None):
        conv=self.ops.owned('conversation',conv_id,actor,workspace_id)
        from core.material_suggestions import suggestions
        materials=[m for m in self.ops.visible('material',actor,workspace_id) if m['conv_id']==conv_id]
        from core.closure_plans import followup_state
        return dict(closure_plan=conv.get('closure_plan'),closure_plan_history=conv.get('closure_plan_history',[]),customer_followup=followup_state(conv),customer_result=conv.get('customer_result'),customer_result_history=conv.get('customer_result_history',[]),
            customer_confirmation_required=conv.get('customer_confirmation_required',False),service_round=conv.get('service_round',0),result_revision=conv.get('result_revision',0),materials=materials,material_suggestions=suggestions(conv,materials),
            attachments=[a for a in self.ops.visible('attachment',actor,workspace_id) if a['conv_id']==conv_id],
            rechecks=[r for r in self.rechecks(actor,workspace_id) if r['conv_id']==conv_id])

    def add_suggestions(self,conv_id,actor,body,workspace_id=None):
        from core.material_suggestions import suggestions
        conv=self.ops.owned('conversation',conv_id,actor,workspace_id)
        self.ops.check_owner(actor,workspace_id,body['owner'])
        if body['owner']=='待分派' or (not workspace_id and body['owner']!=actor):raise ValueError('请指定当前工作范围内的材料负责人')
        if not body.get('due_at'):raise ValueError('请填写材料追补期限')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');conv=read(db,'conversation',conv_id);materials=[m for m in records(db,'material') if m['conv_id']==conv_id];specs={s['key']:s for s in suggestions(conv,materials)}
            keys=list(dict.fromkeys(body['keys']))
            if not keys or any(k not in specs for k in keys):raise ValueError('建议材料已变化，请刷新后核对选择')
            result=[]
            for key in keys:
                spec=specs[key]
                if spec['existing_id']:
                    result.append(read(db,'material',spec['existing_id']));continue
                m=dict(id='mat-suggest-'+hashlib.sha256((conv_id+':'+key).encode()).hexdigest()[:24],conv_id=conv_id,**self.scope(conv),suggestion_key=key,name=spec['name'],status='missing',required=body.get('required',False),owner=body['owner'],due_at=body['due_at'],created_at=now(),revision=0,history=[])
                stamp(m,actor,'客服选择场景建议建立材料；尚未收集或核验',status='missing');write(db,'material',m);result.append(m)
            return result

    def readiness(self,conv_id,actor,workspace_id=None,ticket_id=None):
        self.ops.owned('conversation',conv_id,actor,workspace_id)
        with self.store.connect() as db:
            db.execute('BEGIN');conv=read(db,'conversation',conv_id)
            tickets=[t for t in records(db,'ticket') if t['conv_id']==conv_id]
            ticket=next((t for t in tickets if t['id']==ticket_id),None)
            if ticket_id and not ticket:raise KeyError('工单不属于当前事项')
            blocks=[dict(kind='material',id=m['id'],title=m['name']+'：'+('待收集' if m['status']=='missing' else '已收到，待核验'),action='去核验材料') for m in records(db,'material') if m['conv_id']==conv_id and m.get('required') and m['status'] not in {'verified','waived','withdrawn'}]
            if ticket_id:
                if (ticket.get('handoff') or {}).get('state')=='pending':blocks.append(dict(kind='ticket',id=ticket_id,title='交接尚未接受',action='处理工单交接'))
            else:
                blocks += [dict(kind='ticket',id=t['id'],title=t.get('title','关联工单')+'：尚未完成',action='去处理工单') for t in tickets if t['status']!='resolved']
            from core.closure_plans import followup_state
            result=conv.get('customer_result') or {};follow=followup_state(conv);plan=conv.get('closure_plan') or {}
            from core.closure_plans import has_current_confirmation
            needs_exception=not has_current_confirmation(conv)
            notices=[]
            if needs_exception:notices.append(dict(kind='customer',title='客户结果尚未确认；结案时需明确后续跟进或无需回访原因',action='核对客户结果与后续安排'))
            phase=('历史结案需补录后续安排' if follow and follow['source']=='closure_review' else '内部已结案，待客户跟进' if follow else '已明确无需回访' if plan.get('kind')=='no_followup' and plan.get('active',True) else '客户已确认解决') if conv['status']=='resolved' else '补齐并核验必要材料' if any(i['kind']=='material' for i in blocks) else '处理关联工单' if blocks else '明确客户结果与后续安排' if needs_exception else '可准备结案'
            return dict(conv_id=conv_id,ticket_id=ticket_id,phase=phase,blocks=blocks,notices=notices,requires_exception=needs_exception,internally_resolved=conv['status']=='resolved')

    def closure_plan(self,conv_id,actor,body,workspace_id=None):
        self.ops.owned('conversation',conv_id,actor,workspace_id)
        from core.closure_plans import save_plan
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');conv=read(db,'conversation',conv_id)
            if conv['status']!='resolved':raise ValueError('请在结案时记录安排；此入口用于补录已结案事项')
            return save_plan(db,conv,actor,body)

    def customer_result(self,conv_id,actor,body,workspace_id=None):
        self.ops.owned('conversation',conv_id,actor,workspace_id)
        status=body['status']
        if status not in {'pending','confirmed','disputed','unreachable'}:raise ValueError('客户结果不支持')
        if datetime.fromisoformat(body['occurred_at']).timestamp()>datetime.now(timezone.utc).timestamp()+300:raise ValueError('反馈时间不能晚于当前时间')
        if status!='confirmed':
            if body.get('owner','待分派')=='待分派' or not body.get('next_action','').strip() or not body.get('due_at'):raise ValueError('未确认结果需要跟进负责人、下一步和期限')
            self.ops.check_owner(actor,workspace_id,body['owner'])
            if not workspace_id and body['owner']!=actor:raise ValueError('个人事项的后续跟进请由当前用户负责；协作请先进入共享空间')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');conv=read(db,'conversation',conv_id)
            if conv.get('result_revision',0)!=body['expected_revision']:raise ValueError('客户结果已被更新，请刷新后核对')
            result={k:v for k,v in body.items() if k!='expected_revision'}
            if status=='confirmed':result.update(owner='',next_action='',due_at=None)
            result.update(source='manual',recorded_by=actor,recorded_at=now(),service_round=conv.get('service_round',0))
            conv.setdefault('customer_result_history',[]).append(result.copy())
            conv.update(customer_result=result,customer_confirmation_required=False,result_revision=conv.get('result_revision',0)+1,updated_at=now())
            write(db,'conversation',conv);return result

    def material(self,conv_id,actor,body,workspace_id=None,id=None):
        conv=self.ops.owned('conversation',conv_id,actor,workspace_id)
        self.ops.check_owner(actor,workspace_id,body['owner'])
        if not workspace_id and body['owner']!=actor:raise ValueError('个人事项的材料请由当前用户负责；协作请先进入共享空间')
        if body['owner']=='待分派' or not body.get('due_at'):raise ValueError('材料需要负责人和追补期限')
        if body['status'] in {'verified','waived','withdrawn'} and not body.get('note','').strip():raise ValueError('核验、豁免或撤回需要说明原因')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if id:
                m=read(db,'material',id)
                if not m or m['conv_id']!=conv_id:raise KeyError('材料不属于当前事项')
                revision(m,body['expected_revision'])
                if not body.get('note','').strip():raise ValueError('修改材料项需要记录变更说明')
            else:
                m=dict(id='mat-'+uuid.uuid4().hex,conv_id=conv_id,**self.scope(conv),created_at=now(),revision=0,history=[])
            previous={k:m.get(k) for k in ['name','status','required','owner','due_at']}
            m.update({k:v for k,v in body.items() if k not in {'note','expected_revision'}})
            stamp(m,actor,body.get('note','') or '建立材料追补项',previous=previous,status=m['status'])
            return write(db,'material',m)

    @staticmethod
    def file_type(content,filename):
        suffix=filename.lower().rsplit('.',1)[-1]
        types={'png':('image/png',content.startswith(b'\x89PNG\r\n\x1a\n') and len(content)>32),
               'jpg':('image/jpeg',content.startswith(b'\xff\xd8\xff') and content.endswith(b'\xff\xd9')),
               'jpeg':('image/jpeg',content.startswith(b'\xff\xd8\xff') and content.endswith(b'\xff\xd9')),
               'webp':('image/webp',len(content)>16 and content[:4]==b'RIFF' and content[8:12]==b'WEBP'),
               'pdf':('application/pdf',content.startswith(b'%PDF-'))}
        if suffix not in types or not types[suffix][1]:raise ValueError('仅支持内容与扩展名匹配的PNG、JPEG、WebP、PDF凭证')
        if suffix=='pdf':
            from pypdf import PdfReader
            from io import BytesIO
            try:
                pdf=PdfReader(BytesIO(content));valid=not pdf.is_encrypted and 0<len(pdf.pages)<=200
            except Exception:valid=False
            if not valid:raise ValueError('PDF无效、已加密或超过200页')
        return types[suffix][0]

    def upload(self,conv_id,actor,material_id,filename,content,source_note,request_id,workspace_id=None):
        conv=self.ops.owned('conversation',conv_id,actor,workspace_id)
        if not content or len(content)>MAX_FILE:raise ValueError('凭证不能为空且单文件不能超过5MB')
        filename=filename.replace('\\','/').rsplit('/',1)[-1][:200]
        mime=self.file_type(content,filename);digest=hashlib.sha256(content).hexdigest()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');m=read(db,'material',material_id)
            if not m or m['conv_id']!=conv_id:raise KeyError('材料不属于当前事项')
            if m['status']=='withdrawn':raise ValueError('已撤回材料不能上传凭证')
            prior=next((a for a in records(db,'attachment') if a['conv_id']==conv_id and a.get('request_id')==request_id and a['uploaded_by']==actor),None)
            if prior:
                if prior['sha256']!=digest or prior['material_id']!=material_id or prior['source_note']!=source_note or prior['filename']!=filename:raise ValueError('同次上传标识内容不同，请重新选择文件')
                return prior
            if sum(a['conv_id']==conv_id and not a.get('archived') for a in records(db,'attachment'))>=20:raise ValueError('每个事项最多保留20个活动凭证，请先归档不再使用的凭证')
            a=dict(id='att-'+uuid.uuid4().hex,conv_id=conv_id,material_id=material_id,filename=filename,mime=mime,size=len(content),sha256=digest,
                uploaded_by=actor,created_at=now(),source='manual_upload',source_note=source_note,request_id=request_id,archived=False,revision=1,history=[],**self.scope(conv))
            db.execute('INSERT INTO attachment_bytes VALUES(?,?)',(a['id'],content));write(db,'attachment',a)
            # New evidence requires another verification, even if the material was verified before.
            m['status']='received';stamp(m,actor,'上传凭证，需人工核验',attachment_id=a['id'],status='received');write(db,'material',m)
            return a

    def attachment(self,id,actor,workspace_id=None):
        a=self.ops.owned('attachment',id,actor,workspace_id)
        with self.store.connect() as db:row=db.execute('SELECT content FROM attachment_bytes WHERE id=?',(id,)).fetchone()
        if not row:raise KeyError('原文件不存在')
        return a,bytes(row[0])

    def archive_attachment(self,id,actor,note,expected,workspace_id=None):
        self.ops.owned('attachment',id,actor,workspace_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');a=read(db,'attachment',id);revision(a,expected)
            if a.get('archived'):raise ValueError('凭证已经归档，请刷新后核对')
            a['archived']=True;stamp(a,actor,note);write(db,'attachment',a)
            m=read(db,'material',a['material_id'])
            if m and m['status']=='verified':
                m['status']='received';stamp(m,actor,'凭证已归档，材料需重新核验',attachment_id=id);write(db,'material',m)
            return a

    def create_gap(self,actor,conv_id,question,owner,workspace_id=None):
        conv=self.ops.owned('conversation',conv_id,actor,workspace_id);self.ops.check_owner(actor,workspace_id,owner)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=next((g for g in records(db,'knowledge_gap') if g['conv_id']==conv_id and g['question']==question and g['status'] in {'open','pending'}),None)
            if old:return old
            return write(db,'knowledge_gap',dict(id='gap-'+uuid.uuid4().hex,conv_id=conv_id,source_conv_ids=[conv_id],question=question,original_question=question,
                owner=owner,status='open',created_at=now(),updated_at=now(),revision=1,history=[],**self.scope(conv)))

    def gap_documents(self,id,actor,workspace_id=None):
        gap=self.ops.owned('knowledge_gap',id,actor,workspace_id)
        conv=self.ops.owned('conversation',gap['conv_id'],actor,workspace_id)
        return [dict(id=d['id'],title=d['title'],published_version=d['published_version'],is_demo=bool(d.get('is_demo'))) for d in self.store.list('demo_document' if gap.get('is_demo') else 'document') if self.valid_document(d,gap) and (not gap.get('is_demo') or d['id'] in conv.get('demo_policy_ids',[]))]

    def edit_gap(self,id,actor,body,workspace_id=None):
        self.ops.owned('knowledge_gap',id,actor,workspace_id);self.ops.check_owner(actor,workspace_id,body['owner'])
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');g=read(db,'knowledge_gap',id);revision(g,body.get('expected_revision'))
            if g['status']=='merged':raise ValueError('已合并缺口请进入目标记录维护')
            doc=read(db,'demo_document' if g.get('is_demo') else 'document',body.get('document_id') or '')
            if body['status']=='resolved' and not self.valid_document(doc,g):raise ValueError('完成知识缺口需关联当前已生效的业务文档')
            if body['status']=='resolved' and g.get('is_demo') and doc['id'] not in (read(db,'conversation',g['conv_id']) or {}).get('demo_policy_ids',[]):raise ValueError('请关联当前案例的演示规则，其他案例规则不适用')
            before={k:g.get(k) for k in ['question','status','owner','document_id']}
            g.setdefault('original_question',g['question']);g.setdefault('source_conv_ids',[g['conv_id']])
            g.update({k:v for k,v in body.items() if k in {'owner','status','document_id','question'} and (k!='question' or v is not None)})
            if g['status']!='resolved':g['document_id']=None
            stamp(g,actor,body['note'],previous=before,status=g['status'],question=g['question'],document_id=g.get('document_id'))
            write(db,'knowledge_gap',g)
            if g['status']=='resolved':self.sync_document(g['document_id'],db)
            return g

    def merge_gap(self,id,target_id,actor,note,expected,target_expected,workspace_id=None):
        self.ops.owned('knowledge_gap',id,actor,workspace_id);self.ops.owned('knowledge_gap',target_id,actor,workspace_id)
        if id==target_id:raise ValueError('不能合并到自身')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');g=read(db,'knowledge_gap',id);target=read(db,'knowledge_gap',target_id)
            revision(g,expected);revision(target,target_expected)
            if g['status'] in TERMINAL_GAPS or target['status'] in TERMINAL_GAPS:raise ValueError('请选择未撤销、未合并的来源与目标，不能形成循环')
            linked=set(target.get('source_conv_ids',[target['conv_id']]))|set(g.get('source_conv_ids',[g['conv_id']]))
            target['source_conv_ids']=sorted(linked);stamp(target,actor,'合入缺口：'+note,source_gap_id=id)
            g.update(status='merged',merged_into=target_id);stamp(g,actor,'合并至 '+target_id+'：'+note,target_gap_id=target_id)
            write(db,'knowledge_gap',target);write(db,'knowledge_gap',g)
            if target['status']=='resolved' and target.get('document_id'):self.sync_document(target['document_id'],db)
            return g

    def sync_document(self,doc_id,db=None,allowed=None):
        if db is None:
            with self.store.connect() as conn:
                conn.execute('BEGIN IMMEDIATE');return self.sync_document(doc_id,conn,allowed)
        doc=read(db,'document',doc_id) or read(db,'demo_document',doc_id)
        if not doc or doc.get('deleted') or doc.get('scope') not in {'business','demo'} or not doc.get('published_version'):return 0
        version=doc['published_version'];links={}
        published=read(db,'document_version',f'{doc_id}:{version}') or doc
        for g in records(db,'knowledge_gap'):
            if g.get('document_id')==doc_id and g['status']=='resolved':
                for conv_id in g.get('source_conv_ids',[g['conv_id']]):links.setdefault(conv_id,set()).add('gap:'+g['id'])
        for conv_id,raw in db.execute('SELECT conv_id,data FROM messages'):
            m=json.loads(raw)
            if m.get('role')=='assistant' and m.get('knowledge_mode')==('test' if doc.get('is_demo') else 'business') and any(s.get('document_id')==doc_id for s in m.get('sources',[])):
                links.setdefault(conv_id,set()).add('citation:'+m['id'])
        created=0
        for conv_id,refs in links.items():
            if allowed is not None and conv_id not in allowed:continue
            conv=read(db,'conversation',conv_id)
            if not conv or not self.valid_document(doc,conv):continue
            if doc.get('is_demo') and doc_id not in conv.get('demo_policy_ids',[]):continue
            id='recheck-'+hashlib.sha256(f'{doc_id}:{version}:{conv_id}'.encode()).hexdigest()[:32]
            previous=read(db,'knowledge_recheck',id)
            if previous:
                previous['references']=sorted(set(previous['references'])|refs);write(db,'knowledge_recheck',previous);continue
            for old in records(db,'knowledge_recheck'):
                if old['document_id']==doc_id and old['conv_id']==conv_id and old['status']=='pending':
                    old['status']='superseded';stamp(old,'系统','新版本生效，待回查项转至新版本');write(db,'knowledge_recheck',old)
            r=dict(id=id,conv_id=conv_id,document_id=doc_id,document_version=version,document_title=published.get('title',doc_id),references=sorted(refs),
                owner=self.responsible(conv,refs,lambda kind,id:read(db,kind,id)),status='pending',note='',revision=1,history=[],created_at=now(),updated_at=now(),**self.scope(conv))
            write(db,'knowledge_recheck',r);created+=1
        return created

    def refresh_rechecks(self,actor,workspace_id=None):
        self.ops.require_space(actor,workspace_id)
        allowed={c['id'] for c in self.ops.visible('conversation',actor,workspace_id)}
        ws=self.store.get('workspace',workspace_id) if workspace_id else None
        for doc in self.store.list('demo_document' if ws and ws.get('is_demo') else 'document'):
            if not doc.get('is_demo') or doc.get('workspace_id')==workspace_id:self.sync_document(doc['id'],allowed=allowed)
        return self.rechecks(actor,workspace_id)

    def rechecks(self,actor,workspace_id=None):
        result=[]
        for r in self.ops.visible('knowledge_recheck',actor,workspace_id):
            doc=self.store.get('demo_document' if r.get('is_demo') else 'document',r['document_id']);conv=self.store.get('conversation',r['conv_id']) or {}
            current=bool(self.valid_document(doc,r) and doc.get('published_version')==r['document_version'])
            result.append(dict(r,document_current=current,case_title=conv.get('title','原事项'),current_owner=self.responsible(conv,r['references'],self.store.get)))
        return result

    def review(self,id,actor,status,note,expected,workspace_id=None):
        self.ops.owned('knowledge_recheck',id,actor,workspace_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');r=read(db,'knowledge_recheck',id);revision(r,expected)
            doc=read(db,'demo_document' if r.get('is_demo') else 'document',r['document_id'])
            if not self.valid_document(doc,r) or doc.get('published_version')!=r['document_version']:raise ValueError('依据版本已变化或失效，请刷新影响事项清单')
            if r['status']=='superseded':raise ValueError('此项已转至新版本，请刷新')
            r.update(status=status,note=note,reviewed_by=actor,reviewed_at=now());stamp(r,actor,note,status=status,document_version=r['document_version'])
            return write(db,'knowledge_recheck',r)
