"""Translate a saved reply without replacing its source or inventing policies."""
import hashlib,json,uuid
from core.assistant_outputs import is_reference
from core.operations import Operations,read,write
from core.workbench import now
LANGUAGES={'pt-BR':'巴西葡萄牙语','en':'英语','zh-CN':'简体中文','es':'西班牙语'}
def digest(text):return hashlib.sha256(text.encode()).hexdigest()
def source(store,conv_id,message_id):
    messages=store.messages(conv_id);m=next((m for m in messages if m['id']==message_id),None)
    if not m or m['role']!='assistant' or m.get('legacy') or is_reference(m,messages):raise ValueError('请选择当前会话内可核对的客户回复草稿')
    return m
def validate_lineage(store,conv_id,msg):
    messages={m['id']:m for m in store.messages(conv_id)};seen=set()
    while msg.get('translation_source_id'):
        if msg['id'] in seen:raise ValueError('翻译来源关系异常，请重新选择原稿')
        seen.add(msg['id']);original=messages.get(msg['translation_source_id'])
        if not original or digest(original['content'])!=msg['translation_source_hash']:raise ValueError('翻译原稿已修改，请重新翻译后再采用')
        msg=original

async def build(store,conv,actor,m,language,translate):
    if language not in LANGUAGES:raise ValueError('请选择翻译目标语言')
    validate_lineage(store,conv['id'],m)
    body=await translate(m['content'],LANGUAGES[language])
    latest=source(store,conv['id'],m['id'])
    if digest(latest['content'])!=digest(m['content']):raise ValueError('翻译期间原稿已更新，请核对最新原稿后重新翻译')
    return dict(content=body,translation_source_id=m['id'],translation_source_content=m['content'],translation_source_hash=digest(m['content']),translation_source_revision=m.get('revision',1),target_language=language,output_type='reply',knowledge_status='draft_translation',knowledge_mode=m.get('knowledge_mode',conv.get('knowledge_mode','test')),sources=m.get('sources',[]),data_sources=m.get('data_sources',[]))
async def create(store,conv_id,actor,workspace_id,message_id,language,expected_revision,request_id,translate):
    conv=Operations(store).owned('conversation',conv_id,actor,workspace_id)
    key=digest(conv_id+'\0'+actor+'\0'+request_id);signature=[message_id,language,expected_revision]
    receipt=store.get('draft_translation',key)
    if receipt:
        if receipt['signature']!=signature:raise ValueError('翻译请求编号已用于其他内容')
        return next(m for m in store.messages(conv_id) if m['id']==receipt['message_id'])
    m=source(store,conv_id,message_id)
    if m.get('revision',1)!=expected_revision:raise ValueError('原稿已更新，请刷新核对后再翻译')
    fields=await build(store,conv,actor,m,language,translate)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        messages=[json.loads(r[0]) for r in db.execute('SELECT data FROM messages WHERE conv_id=?',(conv_id,))]
        current=next((x for x in messages if x['id']==message_id),None)
        if not current or digest(current['content'])!=fields['translation_source_hash']:raise ValueError('原稿已更新，请重新翻译')
        msg=dict(id=str(uuid.uuid4()),role='assistant',created_at=now(),kind='reply_draft',review_state='draft',revision=1,author=actor,**fields)
        db.execute('INSERT INTO messages(conv_id,data) VALUES(?,?)',(conv_id,json.dumps(msg,ensure_ascii=False)))
        write(db,'draft_translation',dict(id=key,signature=signature,message_id=msg['id'],conv_id=conv_id,user_id=actor))
        return msg
