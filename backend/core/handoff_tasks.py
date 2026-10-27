# -*- coding: utf-8 -*-
"""Snapshot independent responsibilities and transfer only explicitly chosen work."""
import hashlib,json
from core.operations import records,read,write
from core.closure_plans import followup_state
from core.workbench import now

def preview(db,conv_id):
 conv=read(db,'conversation',conv_id);items=[]
 for m in records(db,'material'):
  if m['conv_id']==conv_id and m['status'] in {'missing','received'}:items.append(dict(key='material:'+m['id'],kind='material',id=m['id'],title=m['name'],owner=m['owner'],status=m['status'],revision=m['revision'],due_at=m.get('due_at'),required=m.get('required',False)))
 follow=followup_state(conv)
 if follow:items.append(dict(key='customer:'+conv_id,kind='customer',id=conv_id,title='客户后续跟进',owner=follow['owner'],status=follow['status'],revision=follow.get('revision',0),source=follow['source'],next_action=follow['next_action'],due_at=follow['due_at']))
 items.sort(key=lambda x:x['key']);hash=hashlib.sha256(json.dumps(items,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 return dict(items=items,context_hash=hash)

def make_plan(db,conv_id,choices,expected_hash):
 current=preview(db,conv_id)
 if current['items']:
  if expected_hash!=current['context_hash']:raise ValueError('材料或客户跟进已有变化，请刷新交接清单后核对')
  chosen={x['key']:x['decision'] for x in choices or []}
  if len(chosen)!=len(choices or []) or set(chosen)!={x['key'] for x in current['items']} or any(d not in {'transfer','retain'} for d in chosen.values()):raise ValueError('请逐项确认材料和客户跟进随工单移交，或由原人继续负责')
 else:
  if choices:raise ValueError('交接清单已经变化，请刷新后核对')
  chosen={}
 return dict(task_context_hash=current['context_hash'],tasks=[dict(x,decision=chosen[x['key']]) for x in current['items']])

def apply_plan(db,conv,handoff,actor):
 current=preview(db,conv['id']);expected=handoff.get('task_context_hash')
 if current['items'] and not expected:raise ValueError('此交接尚未确认独立待办，请退回后由原责任人重新核对交接清单')
 if expected and expected!=current['context_hash']:raise ValueError('交接发起后材料或客户跟进已变化，请退回重新核对，避免覆盖新安排')
 applied=[]
 for task in handoff.get('tasks',[]):
  target=actor if task['decision']=='transfer' else task['owner'];applied.append(dict(task,to_owner=target))
  if task['decision']!='transfer' or target==task['owner']:continue
  if task['kind']=='material':
   m=read(db,'material',task['id']);m['owner']=target;m['revision']+=1;m['updated_at']=now();m.setdefault('history',[]).append(dict(at=now(),actor=actor,note='接受交接，按已确认清单移交材料责任',previous_owner=task['owner'],status=m['status']));write(db,'material',m)
  elif task['source']=='closure_plan':
   plan=conv['closure_plan'];plan['owner']=target;plan['revision']+=1;conv.setdefault('closure_plan_history',[]).append(dict(plan,action='接受交接移交后续责任',changed_at=now(),changed_by=actor,previous_owner=task['owner']))
  elif task['source']=='customer_result':
   conv['customer_result']['owner']=target;conv['result_revision']=conv.get('result_revision',0)+1
   conv.setdefault('customer_followup_history',[]).append(dict(at=now(),actor=actor,action='接受交接移交回访责任',previous_owner=task['owner'],owner=target))
 handoff['applied_tasks']=applied
