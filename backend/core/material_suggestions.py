# -*- coding: utf-8 -*-
"""Optional staff-selected evidence checklists, never auto-completed or auto-required."""
def suggestions(conv,materials):
 key=conv.get('practice_key') or (conv.get('intake') or {}).get('issue_type','other')
 choices={
 'missing':[('quantity','应收、实收及差异数量说明','先对照已有数量记录；订单行数不等于客户实收数量。',('数量','少件')),('receipt','包裹签收与交付核对记录','先使用现有记录，仍不足时再确认需要补充什么。',('签收','物流'))],
 'wrong':[('item','购买商品与实收商品对照','区分购买商品标识和客户实际收到的商品描述。',('商品对照','错发')),('photo','已有商品或包裹照片','有现成照片先核对，不重复索要。',('照片','图片'))],
 'stock':[('notice','库存通知与订单核对记录','核对通知时间与内容，历史状态不代表当前库存。',('库存','通知')),('payment','付款记录与客户处理意愿','核对已有付款记录，不代客户选择退款。',('付款','支付','意愿'))],
 'quality':[('description','商品问题与使用情况说明','区分主观感受、功能异常与证实的损坏。',('问题说明','使用情况')),('photo','已有商品照片或其他说明','先核对现有材料；并非每种质量问题都必须上传照片。',('照片','图片'))],
 'logistics':[('receipt','交付时间与签收核对记录','先核对订单时间、评价作答时间和已有签收信息。',('签收','物流'))],
 'refund':[('request','客户诉求与相关交易记录','仅记录客户实际表达的诉求，不预先承诺权益。',('诉求','交易'))],
 }
 if key in {'not_received','late'}:key='logistics'
 specs=choices.get(key,[('description','问题情况与已有凭证说明','按实际问题选择需要的材料，避免重复收集。',('说明',))])
 result=[]
 for id,name,reason,aliases in specs:
  existing=next((m for m in materials if m.get('suggestion_key')==id or any(word in m['name'] for word in aliases)),None)
  result.append(dict(key=id,name=name,reason=reason,existing_id=existing['id'] if existing else None,existing_status=existing['status'] if existing else None))
 return result
