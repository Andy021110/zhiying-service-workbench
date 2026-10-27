# -*- coding: utf-8 -*-
"""Explicit closure arrangements are plans, never invented customer feedback."""
from datetime import datetime, timedelta, timezone
from core.operations import read,write
from core.workbench import now


def has_current_confirmation(conv):
 result=conv.get('customer_result') or {}
 return result.get('status')=='confirmed' and not conv.get('customer_confirmation_required',False) and result.get('service_round',0)==conv.get('service_round',0)

def reopen_followup(conv,actor,reason):
 """Start a new handling round, retaining feedback history and unfinished work."""
 at=now();previous=conv.get('customer_result') or {}
 conv.update(service_round=conv.get('service_round',0)+1,reopened_at=at,customer_confirmation_required=True,result_revision=conv.get('result_revision',0)+1)
 if not previous or previous.get('status')=='confirmed':
  history=conv.setdefault('customer_result_history',[])
  if previous and previous not in history:history.append(previous.copy())
  result=dict(status='pending',occurred_at=at,note='事项已重新打开，上一轮结果保留在历史中；本轮需重新确认。',source='case_reopen',recorded_by=actor,recorded_at=at,service_round=conv['service_round'],owner=conv.get('owner') if conv.get('owner') not in {None,'','待分派'} else actor,next_action='核对重开原因并重新确认本轮客户结果',due_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
  history.append(result.copy());conv['customer_result']=result
 plan=conv.get('closure_plan') or {}
 if plan.get('kind') in {'confirmed','no_followup'} and plan.get('active',True):
  conv['closure_plan']=dict(plan,active=False,revision=plan.get('revision',0)+1,invalidated_at=at)
 conv.setdefault('case_history',[]).append(dict(at=at,actor=actor,action='重开后需重新确认客户结果',reason=reason,service_round=conv['service_round']))

def followup_state(conv):
 result=conv.get('customer_result') or {};plan=conv.get('closure_plan') or {}
 active=plan and plan.get('active',True) and plan.get('at','')>=(result.get('recorded_at') or '')
 if active:
  if plan['kind'] in {'confirmed','no_followup'}:return None
  return dict(status='pending',owner=plan['owner'],next_action=plan['next_action'],due_at=plan['due_at'],note=plan['note'],source='closure_plan',revision=plan['revision'])
 if result.get('status') in {'pending','disputed','unreachable'}:return dict(result,source='customer_result',revision=conv.get('result_revision',0))
 if result.get('status')=='confirmed':return None
 if conv['status']=='resolved':return dict(status='unrecorded',owner=conv.get('owner') if conv.get('owner') not in {None,'','待分派'} else conv['user_id'],next_action='核对历史结案是否仍需回访，补录后续安排',due_at=None,source='closure_review',revision=conv.get('result_revision',0))
 return None

def save_plan(db,conv,actor,plan):
 kind=plan.get('kind');result=conv.get('customer_result') or {}
 if plan.get('expected_result_revision')!=conv.get('result_revision',0) or plan.get('expected_plan_revision')!=(conv.get('closure_plan') or {}).get('revision',0):raise ValueError('客户结果或结案安排已更新，请刷新核对；未提交内容仍保留')
 if kind not in {'confirmed','followup','no_followup'}:raise ValueError('请选择客户确认、仍需跟进或无需回访')
 if kind=='confirmed' and not has_current_confirmation(conv):raise ValueError('本轮客户确认尚未登记；事项重开后不能复用上一轮确认，请先核对并登记本轮客户结果')
 note=plan.get('note','').strip()
 if kind!='confirmed' and not note:raise ValueError('请说明内部结案的后续安排或无需回访的原因')
 if kind=='followup':
  owner=plan.get('owner');due=plan.get('due_at')
  ws=read(db,'workspace',conv.get('workspace_id')) if conv.get('workspace_id') else None
  if not owner or owner=='待分派' or (ws and owner not in {m['id'] for m in ws['members']}) or (not ws and owner!=actor):raise ValueError('后续跟进需要当前工作范围内的负责人')
  if not plan.get('next_action','').strip() or not due:raise ValueError('仍需跟进的事项必须填写下一步和期限')
  try:
   if datetime.fromisoformat(due.replace('Z','+00:00')).tzinfo is None:raise ValueError()
  except (ValueError,TypeError):raise ValueError('请填写带时区的有效跟进期限')
 saved=dict(kind=kind,note=note,owner=plan.get('owner') if kind=='followup' else '',next_action=plan.get('next_action','').strip() if kind=='followup' else '',due_at=plan.get('due_at') if kind=='followup' else None,actor=actor,at=now(),active=True,revision=(conv.get('closure_plan') or {}).get('revision',0)+1)
 conv.setdefault('closure_plan_history',[]).append(saved.copy());conv['closure_plan']=saved;write(db,'conversation',conv)
 return saved
