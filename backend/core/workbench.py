"""Local workbench records. SQLite is authoritative for conversation context.
No credentials, notifications or writes to the source order platform live here.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class WorkbenchStore:
    def __init__(self, path=None):
        default = Path(os.getenv('CHROMA_PERSIST_DIRECTORY', './data/chroma')).parent / 'workbench.sqlite3'
        self.path = str(path or os.getenv('ECHOMIND_WORKBENCH_DB', str(default)))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(kind,id))')
            db.execute('CREATE TABLE IF NOT EXISTS messages (seq INTEGER PRIMARY KEY AUTOINCREMENT, conv_id TEXT NOT NULL, data TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conv_id,seq)')
            db.execute('CREATE TABLE IF NOT EXISTS attachment_bytes (id TEXT PRIMARY KEY, content BLOB NOT NULL)')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, kind, id):
        with self.connect() as db:
            row = db.execute('SELECT data FROM records WHERE kind=? AND id=?', (kind, id)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, kind, data):
        with self.connect() as db:
            db.execute('INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',
                       (kind, data['id'], json.dumps(data, ensure_ascii=False)))
        return data

    def list(self, kind):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT data FROM records WHERE kind=? ORDER BY rowid DESC', (kind,))]

    def conversation(self, user_id, title='新建机器人测试', order_id='', source='模拟客服输入'):
        record = dict(id=str(uuid.uuid4()), user_id=user_id, title=title, order_id=order_id,
                      source=source, knowledge_mode='test', status='open', owner='待分派', created_at=now(), updated_at=now())
        return self.put('conversation', record)

    def messages(self, conv_id):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT data FROM messages WHERE conv_id=? ORDER BY seq', (conv_id,))]

    def append(self, conv_id, role, content, **metadata):
        msg = dict(id=str(uuid.uuid4()), role=role, content=content, created_at=now())
        msg.update(metadata)
        with self.connect() as db:
            db.execute('INSERT INTO messages(conv_id,data) VALUES(?,?)', (conv_id, json.dumps(msg, ensure_ascii=False)))
            row = db.execute("SELECT data FROM records WHERE kind='conversation' AND id=?", (conv_id,)).fetchone()
            conv = json.loads(row[0]); conv['updated_at'] = now()
            if role in {'user','assistant'}:
                conv['preview'] = content[:100]
            if role == 'user' and conv['title'] in {'新建机器人测试','新服务事项'}:
                conv['title'] = content[:32]
            db.execute("UPDATE records SET data=? WHERE kind='conversation' AND id=?", (json.dumps(conv, ensure_ascii=False), conv_id))
        return msg

    def ticket(self,conv,summary,review_id=''):
        from core.operations import Operations
        return Operations(self).ticket(conv,summary,review_id)

    def update_draft(self,conv_id,message_id,user_id,content,revision,adopt=False,validate=None,workspace_id=None):
        """One transaction validates ownership/revision and records edits or local adoption."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT data FROM records WHERE kind='conversation' AND id=?",(conv_id,)).fetchone()
            conv=json.loads(row[0]) if row else None
            from core.operations import access
            if not access(self,conv,user_id,workspace_id):
                raise KeyError('会话不存在或用户标识不匹配')
            rows=db.execute('SELECT seq,data FROM messages WHERE conv_id=?',(conv_id,)).fetchall()
            found=next(((seq,json.loads(raw)) for seq,raw in rows if json.loads(raw)['id']==message_id),None)
            if not found:
                raise KeyError('回复不存在')
            seq,msg=found
            from core.assistant_outputs import is_reference
            if is_reference(msg,[json.loads(raw) for _,raw in rows]):raise ValueError('客服参考不能作为客户回复采用或修改，请单独准备客户回复草稿')
            if msg['role']!='assistant' or msg.get('legacy'):
                raise ValueError('仅能编辑当前版本生成的回复草稿')
            if msg.get('revision',1)!=revision or msg.get('review_state')=='adopted':
                raise ValueError('回复已变化或已经采用，请重新加载')
            content=content.strip()
            if not content:
                raise ValueError('回复正文不能为空')
            if validate:
                validate(msg,conv)
            msg.setdefault('original_content',msg['content'])
            previous=msg['content']
            msg.update(content=content,revision=revision+1,review_state='adopted' if adopt else 'draft',edited_at=now())
            msg.setdefault('draft_history',[]).append(dict(action='adopt' if adopt else 'edit',actor=user_id,
                at=now(),previous_content=previous,content=content,revision=msg['revision']))
            if adopt:
                msg.update(adopted_at=now(),adopted_by=user_id,delivery_status='local_only')
            db.execute('UPDATE messages SET data=? WHERE seq=?',(json.dumps(msg,ensure_ascii=False),seq))
            conv.update(updated_at=now(),preview=('已采用（未发送）：' if adopt else '回复草稿：')+content[:80])
            db.execute("UPDATE records SET data=? WHERE kind='conversation' AND id=?",(json.dumps(conv,ensure_ascii=False),conv_id))
        return msg
