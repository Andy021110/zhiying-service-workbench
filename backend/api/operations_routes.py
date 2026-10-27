from typing import Annotated,Literal,Optional
from datetime import datetime
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,StringConstraints,Field
from core.operations import Operations,access
from core.workbench import now
from core.task_map import catalog
from core.reply_requests import ReplyRequests

Text=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=200)]
Note=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=2000)]
class Actor(BaseModel):
    user_id:Text
    workspace_id:Optional[Text]=None
class ManualInput(Actor):
    content:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=16000)]
    request_id:Text
    source_reference_id:Optional[Text]=None
class HandoffInput(Actor):
    action:Literal['accept','return']
    note:Note
    expected_revision:int=Field(ge=1)
class SpaceInput(Actor):name:Text
class MemberInput(Actor):
    member_id:Text
    role:Literal['agent','supervisor','knowledge']='agent'
class ReopenInput(Actor):note:Note
class GapInput(Actor):
    conv_id:Text
    question:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=4000)]
    owner:Text='待分派'
class GapEdit(Actor):
    owner:Text
    status:Literal['open','pending','resolved','withdrawn']
    note:Note
    document_id:Optional[str]=None
    question:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=4000)]|None=None
    expected_revision:int=Field(ge=1)


def create_operations_router(store):
    router=APIRouter();ops=Operations(store)
    from api.followup_routes import create_followup_router
    from core.service_followup import Followups
    service=Followups(store)
    router.include_router(create_followup_router(store))
    def run(fn,*args,**kwargs):
        try:return fn(*args,**kwargs)
        except KeyError as e:raise HTTPException(404,str(e))
        except ValueError as e:raise HTTPException(409,str(e))

    @router.get('/task-map')
    def task_map():return catalog()

    @router.get('/workspaces')
    def workspaces(user_id:str):return [w for w in store.list('workspace') if any(m['id']==user_id for m in w['members'])]

    @router.post('/workspaces')
    def create_space(body:SpaceInput):return ops.workspace(body.user_id,body.name)

    @router.post('/workspaces/{id}/members')
    def members(id:str,body:MemberInput):return run(ops.member,body.user_id,id,body.member_id,body.role)

    @router.get('/operations/queue')
    def queue(user_id:str,workspace_id:Optional[str]=None):return run(ops.queue,user_id,workspace_id)

    @router.get('/operations/report')
    def report(user_id:str,workspace_id:Optional[str]=None):return run(ops.report,user_id,workspace_id)

    @router.post('/tickets/{id}/reopen')
    def reopen(id:str,body:ReopenInput):
        ticket=run(ops.owned,'ticket',id,body.user_id,body.workspace_id)
        return run(ops.update_ticket,id,body.user_id,dict(owner=ticket['owner'],note=body.note,status='pending'),body.workspace_id,True)

    @router.post('/tickets/{id}/handoff')
    def handoff(id:str,body:HandoffInput):return run(ops.handoff,id,body.user_id,body.action,body.note,body.expected_revision,body.workspace_id)

    @router.post('/conversations/{id}/drafts/manual')
    def manual(id:str,body:ManualInput):
        conv=run(ops.owned,'conversation',id,body.user_id,body.workspace_id)
        return run(ReplyRequests(store).manual,conv,body.user_id,body.request_id,body.content,body.source_reference_id)

    @router.post('/conversations/{id}/drafts/{message_id}/revise')
    def revise(id:str,message_id:str,body:Actor):return run(ops.revise,id,message_id,body.user_id,body.workspace_id)

    @router.get('/knowledge/gaps')
    def gaps(user_id:str,workspace_id:Optional[str]=None):return run(ops.visible,'knowledge_gap',user_id,workspace_id)

    @router.post('/knowledge/gaps')
    def create_gap(body:GapInput):
        return run(service.create_gap,body.user_id,body.conv_id,body.question,body.owner,body.workspace_id)

    @router.patch('/knowledge/gaps/{id}')
    def update_gap(id:str,body:GapEdit):
        return run(service.edit_gap,id,body.user_id,body.model_dump(exclude={'user_id','workspace_id'}),body.workspace_id)

    return router
