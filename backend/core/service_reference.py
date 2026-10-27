# -*- coding: utf-8 -*-
"""Evidence-based local assistance when no applicable policy can be verified."""
from datetime import datetime

def parsed(value):
 try:return datetime.fromisoformat(value) if value else None
 except (TypeError,ValueError):return None

def chronology(store,conv,order):
 if not order:return None
 review=store.get('review',conv.get('review_id','')) or {};created=review.get('review_creation_date') or review.get('created_at');answered=review.get('review_answer_timestamp')
 entries=[('购买',order.get('purchased_at')),('预计送达',order.get('estimated_at')),('评价记录创建',created),('客户评价作答',answered),('实际送达',order.get('delivered_at'))]
 present=sorted(((label,value) for label,value in entries if parsed(value)),key=lambda row:parsed(row[1]).replace(tzinfo=None))
 lines=['### 历史时间线（源数据原始时间）']+[f'- {label}：{value}' for label,value in present]
 if not answered:lines.append('- 客户评价作答时间：未收录；不能把评价创建时间当作客户填写时间。')
 actual,estimated,at=parsed(order.get('delivered_at')),parsed(order.get('estimated_at')),parsed(answered)
 if actual and estimated:
  days=(actual.date()-estimated.date()).days
  lines.append(f'- 最终按日期比较晚 {days} 个自然日。' if days>0 else f'- 最终按日期比较提前 {-days} 个自然日。' if days<0 else '- 最终按日期比较同日送达。')
 if at and actual:
  if at.replace(tzinfo=None)<actual.replace(tzinfo=None):lines.append('- 客户作答早于记录中的实际送达时间；按订单时间线，当时尚未到记录的送达时点，之后才记录送达。')
  else:lines.append('- 客户作答不早于记录中的实际送达时间；如原文仍称未收到，需要核对签收人与记录差异，不能自动判定客户已实际收货。')
 elif not actual:lines.append('- 实际送达时间未记录，无法据此确认已交付，也不能推算持续逾期至今天。')
 lines.append('以上比较只采用历史字段，不代表实时物流、合同或赔付口径；源数据未提供时区，未按上海时区转换。')
 return '\n'.join(lines)

def cautious_reply(conv):
 issue=conv.get('practice_key') or (conv.get('intake') or {}).get('issue_type','other')
 wording={
 'missing':('您反馈的商品数量差异','订单商品与实际签收数量'),
 'wrong':('您反馈的收到商品与购买商品不一致','订单商品及实际收到的商品情况'),
 'stock':('您反馈的付款后被告知缺货','订单、付款与库存通知的相关记录'),
 'quality':('您反馈的商品品质问题','具体商品情况及相关记录'),
 'not_received':('您反馈的未收到商品情况','评价当时的物流与签收记录'),
 'late':('您反馈的配送时间问题','预计与实际交付记录'),
 'logistics':('您反馈的配送情况','交付与签收记录'),
 'refund':('您反馈的售后诉求','订单及相关处理记录'),
 }.get(issue,('您反馈的情况','订单及相关材料'))
 return f'已收到{wording[0]}。需要先核对{wording[1]}；如现有信息不足，会进一步确认需要补充的内容。当前仍有事项待核实，具体可用方案和处理时间需核对适用规则后再说明，目前无法确认退款、补发条件或完成时间。'

def service_update_reference(store,conv,message):
 from core.assistant_quality import issue_updates,knowledge_gaps,gap_notice
 from core.conversation_context import build_memory
 messages=store.messages(conv['id']);staff=bool(messages and messages[-1]['role']=='operation' and messages[-1].get('action')!='redraft')
 updates=issue_updates(message)
 if not updates:return None
 if not staff:
  memory=build_memory(store,conv['id']);updates={k:v['state'] for k,v in memory.get('current_issues',{}).items()}
 heading='客服假设练习（不是客户事实，未核实，不能据此登记客户结果）' if staff else '客户最新自述（尚未核实，不等于客户确认解决）'
 wording={
 'customer_reports_recovered':'登录：最新描述为已经恢复。登录排查可暂缓；不再把之前的故障表述为仍在发生，仍需观察是否复现。',
 'customer_reports_problem':'技术问题：最新描述仍有登录失败或应用异常，具体原因与是否恢复需进一步核对。',
 'different_orders':'交易归属：最新描述为两笔交易分别对应不同订单，不继续沿用重复扣款的判断；还需核对订单与交易流水，不能据此自动结案。',
 'payment_failed':'当前资金问题已更正为支付失败，不继续假定已经多扣款。下一步核对支付结果、失败提示和订单关联记录。',
 'customer_reports_pending':'资金问题仍待核实：交易显示成功不等于已确认重复扣款，需要核对两笔交易的订单归属及流水。尚未提供的流水仍需补充。'}
 lines=['### 当前处理要点 · '+heading]+['- '+wording[v] for v in updates.values()]
 gaps=knowledge_gaps(message,[])
 if updates.get('technical')=='customer_reports_problem':
  from core.assistant_quality import extract_error_codes
  codes=extract_error_codes(message)
  lines.append('### 技术问题可先补充的信息\n'+('- 原话提到的错误码：'+'、'.join(codes)+'；含义仍需适用资料核对。\n' if codes else '')+'- 发生时间、操作步骤，以及是否每次都能复现。\n- 应用与系统版本、设备或浏览器、完整错误提示（遮盖账号等信息）。\n- 是单个账号还是多人遇到，近期是否更新应用或更换设备、网络。\n- 不提供密码、验证码或完整密钥；当前没有适用技术规则，不推断原因，也不建议重置、清理或修改账号。')
 if gaps:lines.append(gap_notice(gaps))
 lines.append('以上仅整理当前描述，未执行查询、退款、通知或确认结案；政策与处理时限仍需另行核对适用依据。')
 refs=[m['id'] for m in messages[-8:] if m['role']=='user']
 return dict(content='\n\n'.join(lines),suggested_reply='\n\n'.join(lines),references=refs,data_sources=[])


def prepare_reference(store,conv,order,message,fact=None):
 from core.assistant_quality import knowledge_gaps,gap_notice
 update=service_update_reference(store,conv,message)
 if update:return update
 gaps=knowledge_gaps(message,[])
 users=[m for m in store.messages(conv['id']) if m['role']=='user' and m.get('kind')!='staff_action']
 refs=[m['id'] for m in users[-4:]];parts=['### 记录已提供的内容']
 for m in users[-3:]:parts.append('客户原文（自述，尚未核验）：\n> '+m['content'].replace('\n','\n> ')[:700])
 if conv.get('practice_guide'):parts.append('人工中文导读（非逐字原话、非核验结论）：'+conv['practice_guide'])
 if order:
  statuses={'delivered':'已送达','processing':'处理中','canceled':'已取消','shipped':'已发货'}
  parts.append(f"历史订单最终状态：{statuses.get(order.get('status'),order.get('status','未记录'))}；商品与运费合计：{order.get('total')} {order.get('currency','BRL')}。")
  if order.get('items'):parts.append(f"订单共有 {len(order['items'])} 行商品记录、{len({i['product_id'] for i in order['items']})} 个商品标识；这不等于已核实的签收数量。")
 if fact:parts.append(fact['response'])
 timeline=chronology(store,conv,order)
 if timeline:parts.append(timeline)
 materials=[m for m in store.list('material') if m['conv_id']==conv['id']]
 if materials:
  names={'missing':'待收集','received':'已收到待核验','verified':'已核验','waived':'已豁免','withdrawn':'已撤回'}
  parts.append('### 当前材料记录\n'+'\n'.join('- '+m['name']+'：'+names.get(m['status'],m['status']) for m in materials))
 key=conv.get('practice_key') or (conv.get('intake') or {}).get('issue_type')
 questions={
 'missing':['对照订单与客户自述的应收、实收数量，差额仍需凭证核对。','先检查现有材料，再确认是否需要数量、包裹或签收记录，避免重复索要。'],
 'wrong':['核对购买商品标识、实际收到的商品描述和已有照片。','确认当前可核实的信息，原文截断部分不补写。'],
 'stock':['核对付款、订单最终状态与库存通知记录；订单“处理中”不能证明今天仍在处理。','确认客户当前希望继续等货、了解替代方案或提出其他诉求；原文未提出的退款要求不能代填。'],
 'quality':['明确客户描述的是主观品质感受、功能异常还是有证据的损坏。','先检查已有商品说明与材料，再确认还需补充什么。'],
 }.get(key,['核对客户原文与历史订单时间，区分当时描述和最终记录。','把尚未确认的签收、处理意愿与所需材料逐项列清，避免把历史记录当作当前状态。'])
 if gaps:
  parts.append(gap_notice(gaps))
 else:
  parts.append('### 待核实与下一步\n'+'\n'.join('- '+q for q in questions))
 parts.append('### 政策与执行边界\n本次未核对到适用政策，无法确认退款、补发条件、金额或处理时限。以上为记录整理和建议核实步骤，没有执行订单操作。')
 return dict(content='\n\n'.join(parts),suggested_reply=(gap_notice(gaps)+'\n\n'+cautious_reply(conv)) if gaps else cautious_reply(conv),references=refs,data_sources=[dict(kind='order',id=order['id'],label='历史订单原记录',url='/orders/'+order['id'])] if order else [])


def responsibility_reference(store,conv):
 from core.operations import read,records
 from core.closure_plans import followup_state
 with store.connect() as db:
  db.execute('BEGIN');conv=read(db,'conversation',conv['id'])
  tickets=[t for t in records(db,'ticket') if t['conv_id']==conv['id']]
  materials=[m for m in records(db,'material') if m['conv_id']==conv['id'] and m['status'] in {'missing','received'}]
  follow=followup_state(conv);links=[];ticket_lines=[]
  for t in tickets:
   h=t.get('handoff') or {};line=t['id']+'：'+t['owner']+'；状态 '+{'open':'待处理','pending':'待跟进','in_progress':'处理中','resolved':'已解决'}.get(t['status'],t['status'])
   if h.get('state')=='pending':line+='；等待 '+h['candidate']+' 接受，当前仍由 '+t['owner']+' 负责'
   ticket_lines.append(line);links.append(dict(kind='ticket',id=t['id'],conv_id=conv['id'],label='核对工单责任'))
  material_lines=[m['name']+'：'+m['owner']+'；'+('待收集' if m['status']=='missing' else '已收到，待核验') for m in materials]
  links.extend(dict(kind='material',id=m['id'],conv_id=conv['id'],label='核对材料责任') for m in materials)
  customer=(follow['owner']+'；'+follow['next_action']) if follow else ('客户已确认解决，无待回访' if (conv.get('customer_result') or {}).get('status')=='confirmed' else '已记录无需回访的原因' if (conv.get('closure_plan') or {}).get('kind')=='no_followup' else '尚未登记客户结果或回访安排，需责任人核对')
  links.append(dict(kind='customer',id=conv['id'],conv_id=conv['id'],label='核对客户结果与回访'))
  body='1. 工单责任：'+('；'.join(ticket_lines) or '尚无关联工单，事项当前负责人 '+str(conv.get('owner') or conv['user_id']))+'。\n\n2. 材料责任：'+('；'.join(material_lines) or '没有待收集或待核验材料')+'。\n\n3. 客户回访责任：'+customer+'。'
  return body,links
