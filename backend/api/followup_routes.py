from typing import Annotated, Literal
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints, AwareDatetime
from urllib.parse import quote
from core.service_followup import Followups, MAX_FILE

Text=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=200)]
Note=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=2000)]
class Scope(BaseModel):
    user_id:Text
    workspace_id:Text|None=None
from api.plan_inputs import ClosurePlanInput
class ClosurePlanBody(Scope):
    plan:ClosurePlanInput
class CustomerResultInput(Scope):
    status:Literal['pending','confirmed','disputed','unreachable']
    occurred_at:AwareDatetime
    note:Note
    owner:Text='待分派'
    next_action:Annotated[str,StringConstraints(max_length=1000)]=''
    due_at:AwareDatetime|None=None
    expected_revision:int=Field(ge=0)
class MaterialInput(Scope):
    name:Text
    required:bool=True
    owner:Text
    due_at:AwareDatetime
    status:Literal['missing','received','verified','waived','withdrawn']='missing'
    note:Annotated[str,StringConstraints(max_length=2000)]=''
    expected_revision:int|None=Field(default=None,ge=1)
class SuggestedMaterialsInput(Scope):
    keys:list[Text]=Field(min_length=1,max_length=6)
    owner:Text
    due_at:AwareDatetime
    required:bool=False
class ArchiveInput(Scope):
    note:Note
    expected_revision:int=Field(ge=1)
class RecheckInput(ArchiveInput):
    status:Literal['pending','reviewed','not_applicable']
class GapMergeInput(ArchiveInput):
    target_id:Text
    target_revision:int=Field(ge=1)


def create_followup_router(store):
    router=APIRouter();service=Followups(store)
    def run(fn,*args,**kw):
        try:return fn(*args,**kw)
        except KeyError as e:raise HTTPException(404,str(e))
        except ValueError as e:raise HTTPException(409,str(e))
    def payload(body):return body.model_dump(mode='json',exclude={'user_id','workspace_id'})

    @router.get('/conversations/{id}/followup')
    def followup(id:str,user_id:str,workspace_id:str|None=None):return run(service.bundle,id,user_id,workspace_id)

    @router.get('/conversations/{id}/readiness')
    def readiness(id:str,user_id:str,workspace_id:str|None=None,ticket_id:str|None=None):return run(service.readiness,id,user_id,workspace_id,ticket_id)

    @router.get('/knowledge/gaps/{id}/documents')
    def gap_documents(id:str,user_id:str,workspace_id:str|None=None):return run(service.gap_documents,id,user_id,workspace_id)

    @router.put('/conversations/{id}/closure-plan')
    def closure_plan(id:str,body:ClosurePlanBody):return run(service.closure_plan,id,body.user_id,body.plan.model_dump(mode='json'),body.workspace_id)

    @router.put('/conversations/{id}/customer-result')
    def outcome(id:str,body:CustomerResultInput):return run(service.customer_result,id,body.user_id,payload(body),body.workspace_id)

    @router.post('/conversations/{id}/materials')
    def material(id:str,body:MaterialInput):return run(service.material,id,body.user_id,payload(body),body.workspace_id)

    @router.post('/conversations/{id}/material-suggestions')
    def suggested_materials(id:str,body:SuggestedMaterialsInput):return run(service.add_suggestions,id,body.user_id,payload(body),body.workspace_id)

    @router.patch('/conversations/{id}/materials/{material_id}')
    def edit_material(id:str,material_id:str,body:MaterialInput):
        if body.expected_revision is None:raise HTTPException(422,'修改材料必须带当前版本')
        return run(service.material,id,body.user_id,payload(body),body.workspace_id,material_id)

    @router.post('/conversations/{id}/attachments')
    async def upload(id:str,user_id:Annotated[str,Form(min_length=1,max_length=200)],material_id:Annotated[str,Form(min_length=1)],
                     source_note:Annotated[str,Form(min_length=1,max_length=2000)],request_id:Annotated[str,Form(min_length=1,max_length=200)],
                     file:Annotated[UploadFile,File()],workspace_id:Annotated[str|None,Form()]=None):
        run(service.ops.owned,'conversation',id,user_id,workspace_id)
        try:content=await file.read(MAX_FILE+1)
        finally:await file.close()
        if not source_note.strip():raise HTTPException(422,'请说明凭证来源')
        return run(service.upload,id,user_id,material_id,file.filename or '',content,source_note.strip(),request_id,workspace_id)

    @router.get('/conversations/{id}/attachments/{attachment_id}')
    def download(id:str,attachment_id:str,user_id:str,workspace_id:str|None=None):
        a,content=run(service.attachment,attachment_id,user_id,workspace_id)
        if a['conv_id']!=id:raise HTTPException(404,'凭证不属于当前事项')
        return Response(content,media_type=a['mime'],headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(a['filename']),
            'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

    @router.post('/conversations/{id}/attachments/{attachment_id}/archive')
    def archive(id:str,attachment_id:str,body:ArchiveInput):
        a=run(service.ops.owned,'attachment',attachment_id,body.user_id,body.workspace_id)
        if a['conv_id']!=id:raise HTTPException(404,'凭证不属于当前事项')
        return run(service.archive_attachment,attachment_id,body.user_id,body.note,body.expected_revision,body.workspace_id)

    @router.get('/knowledge/rechecks')
    def rechecks(user_id:str,workspace_id:str|None=None):return run(service.rechecks,user_id,workspace_id)

    @router.post('/knowledge/rechecks/refresh')
    def refresh(body:Scope):return run(service.refresh_rechecks,body.user_id,body.workspace_id)

    @router.patch('/knowledge/rechecks/{id}')
    def review(id:str,body:RecheckInput):return run(service.review,id,body.user_id,body.status,body.note,body.expected_revision,body.workspace_id)

    @router.post('/knowledge/gaps/{id}/merge')
    def merge(id:str,body:GapMergeInput):return run(service.merge_gap,id,body.target_id,body.user_id,body.note,body.expected_revision,body.target_revision,body.workspace_id)

    @router.get('/operations/followups')
    def pending(user_id:str,workspace_id:str|None=None):
        convs=run(service.ops.visible,'conversation',user_id,workspace_id)
        from core.closure_plans import followup_state
        return dict(customer_results=[dict(conv_id=c['id'],case_title=c['title'],**r) for c in convs if (r:=followup_state(c))],
            materials=[m for m in run(service.ops.visible,'material',user_id,workspace_id) if m['status'] in {'missing','received'}],
            rechecks=[r for r in run(service.rechecks,user_id,workspace_id) if r['status']=='pending'])
    return router
