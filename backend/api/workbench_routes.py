"""Workbench API for a single-machine demo; user_id scopes records, it is not authentication."""
import asyncio
from typing import Annotated, Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StringConstraints, Field, AwareDatetime
from core.workbench import now
from core.knowledge_policy import source_is_current
from core.conversation_context import build_memory
from core.operations import Operations
from api.operations_routes import create_operations_router
from core.reply_requests import ReplyRequests
from core.demo_cases import source_document
from api.demo_routes import create_demo_router
from core.historical_todos import HistoricalTodos
from core.assistant_outputs import public_messages

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
class ActorInput(BaseModel):
    user_id: Text
    workspace_id: str | None = None
class NewConversation(ActorInput):
    title: Text = '新建机器人测试'
    order_id: str = ''
    knowledge_mode: Literal['test','business'] = 'test'
class IntakeInput(BaseModel):
    issue_type: Literal['complaint','logistics','missing','refund','account','other']='other'
    product_id: str = ''
    quantity: int | None = Field(default=None,ge=1,le=999)
    desired_outcome: Annotated[str,StringConstraints(max_length=1000)] = ''
    evidence_note: Annotated[str,StringConstraints(max_length=2000)] = ''
from api.plan_inputs import ClosurePlanInput,HandoffTaskInput
class ConversationPatch(ActorInput):
    closure_plan:ClosurePlanInput|None=None
    status: Literal['open', 'pending', 'resolved'] | None = None
    owner: Text | None = None
    order_id: str | None = None
    knowledge_mode: Literal['test','business'] | None = None
    resolution: Annotated[str,StringConstraints(strip_whitespace=True,max_length=2000)] | None = None
    intake: IntakeInput | None = None
    closure_exception: Annotated[str,StringConstraints(max_length=2000)] = ''
class TicketInput(ActorInput):
    conv_id: Text
    summary: str = ''
class TicketPatch(ActorInput):
    closure_plan:ClosurePlanInput|None=None
    handoff_tasks:list[HandoffTaskInput]|None=Field(default=None,max_length=100)
    handoff_context_hash:str|None=Field(default=None,max_length=64)
    owner: Text
    status: Literal['open', 'in_progress', 'pending', 'resolved']
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    priority: Literal['urgent','high','normal','low'] = 'normal'
    due_at: AwareDatetime | None = None
    wait_reason: Annotated[str,StringConstraints(max_length=200)] = ''
    next_action: Annotated[str,StringConstraints(max_length=1000)] = ''
    resolution: Annotated[str,StringConstraints(strip_whitespace=True,max_length=2000)] = ''
    expected_revision: int | None = Field(default=None,ge=1)
    closure_exception: Annotated[str,StringConstraints(max_length=2000)] = ''
class DocumentEdit(BaseModel):
    title: Text
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000000)]
    version: int = Field(ge=1)
    scope: Literal['test','business'] | None = None
class FeedbackInput(ActorInput):
    pass
class NoteInput(ActorInput):
    content: Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=4000)]
class DraftInput(ActorInput):
    content: Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=16000)]
    revision: int = Field(ge=1)
    adopt: bool = False
class ReviewInput(BaseModel):
    actor: Text
    action: Literal['submit','approve','reject']
    version: int = Field(ge=1)
    note: Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=2000)]


def create_router(store, kb_getter, invalidate):
    router = APIRouter()
    router.include_router(create_operations_router(store))
    router.include_router(create_demo_router(store))
    ops=Operations(store)

    def owned(kind,id,user,workspace_id=None):
        try:return ops.owned(kind,id,user,workspace_id)
        except KeyError as error:raise HTTPException(404,str(error))

    def operate(fn,*args,**kwargs):
        try:return fn(*args,**kwargs)
        except KeyError as error:raise HTTPException(404,str(error))
        except ValueError as error:raise HTTPException(409,str(error))

    @router.get('/conversations')
    def conversations(user_id: str,workspace_id: str | None = None):
        return sorted(operate(ops.visible,'conversation',user_id,workspace_id), key=lambda c: c['updated_at'], reverse=True)

    @router.post('/conversations')
    def new_conversation(body: NewConversation):
        operate(ops.require_space,body.user_id,body.workspace_id)
        ws=store.get('workspace',body.workspace_id) if body.workspace_id else None
        is_demo=bool(ws and ws.get('is_demo'))
        if body.order_id:
            linked=store.get('demo_order' if is_demo else 'order',body.order_id)
            if not linked or (is_demo and linked.get('workspace_id')!=body.workspace_id):raise HTTPException(404,'订单不在当前范围')
        conv=store.conversation(body.user_id,body.title,body.order_id)
        conv.update(knowledge_mode='test' if is_demo else body.knowledge_mode,workspace_id=body.workspace_id)
        if is_demo:conv.update(is_demo=True,demo_policy_ids=[],source='合成演示练习；非真实客户')
        return store.put('conversation',conv)

    @router.get('/conversations/{id}')
    def conversation(id: str,user_id: str,workspace_id: str | None = None):
        conv=owned('conversation',id,user_id,workspace_id)
        return dict(conv,messages=public_messages(store,conv),memory=build_memory(store,id),reply_requests=ReplyRequests(store).list(id,user_id))

    @router.post('/conversations/{id}/requests/{request_id}/dismiss')
    def dismiss_request(id:str,request_id:str,body:ActorInput):
        owned('conversation',id,body.user_id,body.workspace_id)
        return operate(ReplyRequests(store).dismiss,id,request_id,body.user_id)

    @router.get('/conversations/{id}/requests/{request_id}')
    def reply_request(id:str,request_id:str,user_id:str,workspace_id:str|None=None):
        owned('conversation',id,user_id,workspace_id)
        record=ReplyRequests(store).get(id,request_id)
        if not record or record['user_id']!=user_id:raise HTTPException(404,'此用户的生成请求不存在')
        return record

    @router.patch('/conversations/{id}')
    def patch_conversation(id: str, body: ConversationPatch):
        patch=body.model_dump(mode='json',exclude_none=True,exclude={'user_id','workspace_id'},exclude_unset=True)
        return operate(ops.patch_conversation,id,body.user_id,patch,body.workspace_id)

    @router.post('/conversations/{id}/notes')
    def add_note(id: str, body: NoteInput):
        owned('conversation',id,body.user_id,body.workspace_id)
        return store.append(id,'note',body.content,kind='internal_note',author=body.user_id,visibility='staff_only')

    @router.patch('/conversations/{id}/drafts/{message_id}')
    def update_draft(id: str, message_id: str, body: DraftInput):
        def validate(msg,conv):
            if not body.adopt:
                return
            if msg.get('translation_source_id'):
                from core.draft_translation import validate_lineage
                validate_lineage(store,id,msg)
            if any(s.get('kind')=='order' and s.get('id')!=conv.get('order_id') for s in msg.get('data_sources',[])):
                raise ValueError('关联订单已变化，请核对新订单并重新生成回复')
            mode=conv.get('knowledge_mode','test')
            if msg.get('knowledge_mode','test')!=mode:
                raise ValueError('会话知识模式已变化，请重新生成回复')
            if not all(source_is_current(source_document(store,source,conv),source,mode) for source in msg.get('sources',[])):
                raise ValueError('引用的知识已更新、归档或不再生效，请重新生成后采用')
        try:
            return store.update_draft(id,message_id,body.user_id,body.content,body.revision,body.adopt,validate,body.workspace_id)
        except KeyError as error:
            raise HTTPException(404,str(error))
        except ValueError as error:
            raise HTTPException(409,str(error))

    @router.get('/conversations/{id}/memory')
    def conversation_memory(id: str,user_id: str,workspace_id: str | None = None):
        owned('conversation',id,user_id,workspace_id)
        return build_memory(store,id)

    @router.get('/tickets')
    def tickets(user_id: str,workspace_id: str | None = None):
        return operate(ops.visible,'ticket',user_id,workspace_id)

    @router.post('/tickets')
    def create_ticket(body: TicketInput):
        conv = owned('conversation',body.conv_id,body.user_id,body.workspace_id)
        messages = [m for m in store.messages(conv['id']) if m['role']=='user' or (m['role']=='assistant' and m.get('review_state')=='adopted')]
        summary = body.summary.strip() or '\n'.join(f"{m['role']}: {m['content'][:300]}" for m in messages[-6:]) or '待补充对话摘要'
        ticket = store.ticket(conv, summary)
        return ticket

    @router.get('/tickets/{id}/handoff-preview')
    def handoff_preview(id:str,user_id:str,workspace_id:str|None=None):
        ticket=owned('ticket',id,user_id,workspace_id)
        from core.handoff_tasks import preview
        with store.connect() as db:
            db.execute('BEGIN');return preview(db,ticket['conv_id'])

    @router.patch('/tickets/{id}')
    def update_ticket(id: str, body: TicketPatch):
        patch=body.model_dump(mode='json',exclude={'user_id','workspace_id'},exclude_unset=True)
        return operate(ops.update_ticket,id,body.user_id,patch,body.workspace_id)

    @router.get('/orders')
    def orders(query: str = '',user_id:str='',workspace_id:str|None=None):
        ws=store.get('workspace',workspace_id) if workspace_id else None
        if ws and ws.get('is_demo'):
            return [o for o in operate(ops.visible,'demo_order',user_id,workspace_id) if query.lower() in str(o).lower()][:100]
        return [o for o in store.list('order') if query.lower() in str(o).lower()][:100]

    @router.get('/orders/{id}')
    def order(id: str,user_id:str='',workspace_id:str|None=None):
        if store.get('demo_order',id):return owned('demo_order',id,user_id,workspace_id)
        result = store.get('order', id)
        if not result:
            raise HTTPException(404, '本地只读样本未收录该订单；未查询实时平台')
        return result

    @router.get('/feedback')
    def feedback():
        return dict(source=store.get('dataset', 'olist'), reviews=store.list('review'))

    @router.post('/historical-todos/ensure')
    def historical_todos(body: ActorInput):
        return operate(HistoricalTodos(store).ensure,body.user_id)

    @router.post('/feedback/{id}/case')
    def feedback_case(id: str, body: FeedbackInput):
        return operate(ops.feedback_case,body.user_id,id,body.workspace_id)

    @router.get('/knowledge/imports')
    def imports():
        return store.list('import')[:50]

    @router.get('/knowledge/documents')
    def documents(include_deleted: bool = False):
        return [dict(d, content_preview=d['content'][:120], content=None, chunks=len(d.get('chunk_ids', [])))
                for d in store.list('document') if include_deleted or not d.get('deleted')]

    @router.get('/knowledge/documents/{id}')
    def document(id: str, version: int | None = None):
        doc = store.get('document_version', f'{id}:{version}') if version else store.get('document', id)
        if not doc:
            raise HTTPException(404, '文档或版本不存在')
        current = store.get('document', id)
        versions = [dict(version=d['version'], updated_at=d['updated_at']) for d in store.list('document_version') if d['document_id'] == id]
        return dict(doc,current_version=current['version'],archived=current.get('deleted',False),versions=versions,current_review_status=current.get('review_status','draft'),current_published_version=current.get('published_version'),review_history=current.get('review_history',[]))

    @router.put('/knowledge/documents/{id}')
    async def edit_document(id: str, body: DocumentEdit):
        old = store.get('document', id)
        if not old:
            raise HTTPException(404, '文档不存在')
        try:
            result = await asyncio.to_thread(kb_getter().save_document, body.title,body.content,id,old['source'],body.version,body.scope)
            invalidate()
            return result
        except ValueError as error:
            raise HTTPException(409, str(error))

    @router.post('/knowledge/documents/{id}/review')
    async def review_document(id: str, body: ReviewInput):
        try:
            result=await asyncio.to_thread(kb_getter().review_document,id,body.action,body.version,body.actor,body.note)
            if body.action=='approve':
                from core.service_followup import Followups
                Followups(store).sync_document(id)
            invalidate()
            return result
        except KeyError:
            raise HTTPException(404,'文档不存在')
        except ValueError as error:
            raise HTTPException(409,str(error))

    @router.delete('/knowledge/documents/{id}')
    async def delete_document(id: str):
        try:
            result = await asyncio.to_thread(kb_getter().archive_document, id)
            invalidate(); return result
        except KeyError:
            raise HTTPException(404, '文档不存在')
        except ValueError as error:
            raise HTTPException(409,str(error))

    @router.post('/knowledge/documents/{id}/restore')
    async def restore_document(id: str):
        try:
            result = await asyncio.to_thread(kb_getter().restore_document, id)
            invalidate(); return result
        except KeyError:
            raise HTTPException(404, '文档不存在')
        except ValueError as error:
            raise HTTPException(409,str(error))

    return router
