from typing import Literal
from pydantic import BaseModel,Field,AwareDatetime
class ClosurePlanInput(BaseModel):
    kind:Literal['confirmed','followup','no_followup']
    note:str=Field(default='',max_length=2000)
    owner:str=Field(default='',max_length=200)
    next_action:str=Field(default='',max_length=1000)
    due_at:AwareDatetime|None=None
    expected_result_revision:int=Field(ge=0)
    expected_plan_revision:int=Field(ge=0)
class HandoffTaskInput(BaseModel):
    key:str=Field(min_length=1,max_length=300)
    decision:Literal['transfer','retain']
