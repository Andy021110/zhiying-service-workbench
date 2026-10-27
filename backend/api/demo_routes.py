# -*- coding: utf-8 -*-
from typing import Annotated
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field,StringConstraints
from core.demo_cases import DemoCases
from core.demo_projects import DemoProjects
Text=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=200)]
class DemoActor(BaseModel):user_id:Text
class NewRound(DemoActor):expected_generation:int=Field(ge=1)
class Decision(DemoActor):
    workspace_id:Text
    action:Annotated[str,StringConstraints(pattern='^(approve|return|resubmit)$')]
    note:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=2000)]
    plan:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=4000)]|None=None
    expected_revision:int=Field(ge=1)
    expected_context_hash:Annotated[str,StringConstraints(pattern='^[a-f0-9]{64}$')]
def create_demo_router(store):
    router=APIRouter();demos=DemoCases(store);projects=DemoProjects(store)
    def run(fn,*args):
        try:return fn(*args)
        except KeyError as e:raise HTTPException(404,str(e))
        except ValueError as e:raise HTTPException(409,str(e))
    @router.get('/demos')
    def catalog(user_id:Text):return run(demos.catalog,user_id)
    @router.post('/demos/ensure')
    def ensure(body:DemoActor):return run(demos.ensure,body.user_id)
    @router.post('/demos/{template_id}/new-round')
    def new_round(template_id:str,body:NewRound):return run(demos.reset,body.user_id,template_id,body.expected_generation)
    @router.get('/demos/project')
    def project(user_id:Text,workspace_id:str):return run(projects.get,user_id,workspace_id)
    @router.get('/demos/project/source')
    def project_source(user_id:Text,workspace_id:str,source_id:str):return run(projects.source,user_id,workspace_id,source_id)
    @router.post('/demos/project/approvals/{id}/decision')
    def decide(id:str,body:Decision):return run(projects.decide,body.user_id,body.workspace_id,id,body.model_dump(exclude={'user_id','workspace_id'}))
    @router.get('/demos/documents')
    def policies(user_id:Text,workspace_id:str):return run(demos.ops.visible,'demo_document',user_id,workspace_id)
    @router.get('/demos/conversations/{id}')
    def guide(id:str,user_id:Text,workspace_id:str):return run(demos.guide,id,user_id,workspace_id)
    @router.get('/demos/documents/{id}')
    def policy(id:str,user_id:Text,workspace_id:str):return run(demos.policy,id,user_id,workspace_id)
    return router
