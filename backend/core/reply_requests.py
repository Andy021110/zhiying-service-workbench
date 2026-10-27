"""Durable local reply requests. One input and one successful result per client request."""
import hashlib
import json
import uuid
from core.workbench import now
from core.operations import read,write


def key(conv_id,request_id):
    return hashlib.sha256((conv_id+'\0'+request_id).encode()).hexdigest()


class ReplyRequests:
    def __init__(self,store):self.store=store

    def get(self,conv_id,request_id):return self.store.get('reply_request',key(conv_id,request_id))

    def list(self,conv_id,actor):
        return [r for r in self.store.list('reply_request') if r['conv_id']==conv_id and r['user_id']==actor][:30]

    def begin(self,conv,actor,request_id,text,input_kind='customer_input',action=None):
        id=key(conv['id'],request_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');record=read(db,'reply_request',id)
            created=record is None
            if record:
                if (record['user_id'],record['message'],record['input_kind'],record.get('action'))!=(actor,text,input_kind,action):
                    raise ValueError('请求编号已用于其他内容，请核对原请求')
                if record['state']=='succeeded':return record,False
                if record['state']=='dismissed':raise ValueError('此请求已停止重试，可从客户原话重新准备回复')
            else:
                source=dict(id=str(uuid.uuid4()),role='user' if input_kind=='customer_input' else 'operation',content=text,
                    created_at=now(),kind=input_kind,author=actor,action=action,reply_request_id=request_id)
                db.execute('INSERT INTO messages(conv_id,data) VALUES(?,?)',(conv['id'],json.dumps(source,ensure_ascii=False)))
                current=read(db,'conversation',conv['id']);current.update(updated_at=now())
                if input_kind=='customer_input':
                    current['preview']=text[:100]
                    if current['title'] in {'新服务事项','新建机器人测试'}:current['title']=text[:32]
                write(db,'conversation',current)
                record=dict(id=id,request_id=request_id,conv_id=conv['id'],user_id=actor,workspace_id=conv.get('workspace_id'),
                    message=text,input_kind=input_kind,action=action,source_message_id=source['id'],created_at=now(),attempts=0)
            record.update(state='running',attempts=record['attempts']+1,updated_at=now(),error=None)
            return write(db,'reply_request',record),created

    def finish(self,conv_id,request_id,payload):
        """Commit result message and receipt together; retry cannot produce a second draft."""
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');record=read(db,'reply_request',key(conv_id,request_id))
            if record['state']=='succeeded':return record['result']
            msg=dict(id=str(uuid.uuid4()),role='assistant',content=payload['response'],created_at=now(),
                kind='assistant_reference' if payload.get('output_type')=='reference' else 'reply_draft',review_state='reference' if payload.get('output_type')=='reference' else 'draft',revision=1,reply_request_id=request_id,
                **{k:v for k,v in payload.items() if k not in {'response','conv_id','request_id'}})
            db.execute('INSERT INTO messages(conv_id,data) VALUES(?,?)',(conv_id,json.dumps(msg,ensure_ascii=False)))
            conv=read(db,'conversation',conv_id);conv.update(preview=msg['content'][:100],updated_at=now());write(db,'conversation',conv)
            record.update(state='succeeded',result=payload,result_message_id=msg['id'],error=None,updated_at=now())
            write(db,'reply_request',record)
            return payload

    def fail(self,conv_id,request_id):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');record=read(db,'reply_request',key(conv_id,request_id))
            if record and record['state']!='succeeded':
                record.update(state='failed',error='回复尚未完成；原输入已保存，可重试同一次生成或手写回复',updated_at=now())
                write(db,'reply_request',record)

    def dismiss(self,conv_id,request_id,actor):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');record=read(db,'reply_request',key(conv_id,request_id))
            if not record or record['user_id']!=actor:raise KeyError('生成请求不存在')
            if record['state']!='failed':raise ValueError('生成状态已变化，请先恢复状态再决定')
            record.update(state='dismissed',updated_at=now());return write(db,'reply_request',record)

    def manual(self,conv,actor,request_id,content,source_reference_id=None):
        id=key(conv['id'],request_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');prior=read(db,'manual_reply',id)
            if prior:
                if prior['user_id']!=actor or prior['content']!=content or prior.get('source_reference_id')!=source_reference_id:raise ValueError('保存编号已用于其他回复')
                row=db.execute('SELECT data FROM messages WHERE conv_id=? ORDER BY seq',(conv['id'],)).fetchall()
                return next(json.loads(r[0]) for r in row if json.loads(r[0])['id']==prior['message_id'])
            current=read(db,'conversation',conv['id'])
            if source_reference_id:
                from core.assistant_outputs import is_reference
                messages=[json.loads(r[0]) for r in db.execute('SELECT data FROM messages WHERE conv_id=?',(conv['id'],))]
                reference=next((m for m in messages if m['id']==source_reference_id),None)
                if not reference or not is_reference(reference,messages):raise ValueError('参考记录不在当前会话，请重新核对')
            msg=dict(id=str(uuid.uuid4()),role='assistant',content=content,created_at=now(),kind='reply_draft',review_state='draft',
                revision=1,author=actor,manual=True,knowledge_mode=current.get('knowledge_mode','test'),knowledge_status='manual',
                sources=[],data_sources=[],context_reference_ids=[],manual_request_id=request_id)
            if source_reference_id:msg['source_reference_id']=source_reference_id
            db.execute('INSERT INTO messages(conv_id,data) VALUES(?,?)',(conv['id'],json.dumps(msg,ensure_ascii=False)))
            current.update(preview='人工草稿：'+content[:80],updated_at=now());write(db,'conversation',current)
            write(db,'manual_reply',dict(id=id,user_id=actor,content=content,message_id=msg['id'],conv_id=conv['id'],source_reference_id=source_reference_id))
            return msg
