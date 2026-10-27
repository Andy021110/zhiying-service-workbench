# -*- coding: utf-8 -*-
"""Local practice tasks grounded in the already imported, immutable Olist sample."""
import hashlib,json,uuid
from datetime import datetime,timedelta
from core.operations import Operations,read,records,write
from core.workbench import now

# Human-written reading guides, separate from the original Portuguese customer text.
EXAMPLES=[
 dict(key='not_received',review_id='030aff7a50557f1994580ee873c11834',title='评价时未收到货 · 核对交付时间线',issue='logistics',guide='客户在评价中表示当时尚未收到商品。',next_action='对照评价日期、预计和实际送达时间，区分评价时的未收货与历史订单最终状态，再记录待确认的问题。'),
 dict(key='late',review_id='030ea5d715585d5854b21ee757a9b58b',title='配送晚到 · 核对客户所述与订单记录',issue='logistics',guide='客户表示配送超过期限一天，并提到此前购物的配送更早。',next_action='核对预计和实际送达日期，记录与客户所述是否一致；回复前查证适用规则，不自行承诺补偿。'),
 dict(key='missing',review_id='03129dea7c12fa5878b2e629ccdf2ce6',title='购买14件只收到9件 · 核对少件情况',issue='missing',guide='客户表示购买14件、仅收到9件，评价时问题仍未解决。数量来自评价，尚未人工核验。',next_action='先核对订单商品明细与客户所述数量；记录仍需哪些数量或签收凭证，再形成处理意见。'),
 dict(key='wrong',review_id='0303804af92daa119d4dfa93e017fb7c',title='玩具车变成牙刷 · 错发商品核对',issue='other',guide='客户表示给孩子购买红色玩具卡车，却收到牙刷，并希望尽快处理。原始评价末尾有截断。',next_action='对照订单商品标识与客户原话，登记错发核对所需材料；保留原文截断状态，不补写缺失内容。'),
 dict(key='stock',review_id='02d7d280dafb4b78a49f368b9f7c4454',title='付款后被告知缺货 · 梳理处理诉求',issue='complaint',guide='客户表示网站出售的商品没有库存，付款数日后才被告知。原文没有明确提出退款要求。',next_action='核对历史订单状态与商品记录，整理库存问题和待确认诉求；不把未表达的退款意愿写成客户原话。'),
 dict(key='quality',review_id='02f29e4ac238024f80ed96cc0f30e772',title='商品太薄、不满意 · 明确质量反馈',issue='complaint',guide='客户认为商品太薄，并对同等价格下的品质不满意；原文未说明商品损坏。',next_action='区分质量主观评价与已证实的损坏，记录需进一步确认的情况，再核对适用售后规则。'),
]

class HistoricalTodos:
 def __init__(self,store):self.store=store;self.ops=Operations(store)
 @staticmethod
 def workspace_id(actor):return 'olist-practice-'+hashlib.sha256(actor.encode()).hexdigest()[:20]
 def ensure(self,actor):
  ws_id=self.workspace_id(actor)
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');dataset=read(db,'dataset','olist');reviews={r['review_id']:r for r in records(db,'review')};ws=read(db,'workspace',ws_id)
   available=[(spec,reviews[spec['review_id']]) for spec in EXAMPLES if spec['review_id'] in reviews and read(db,'order',reviews[spec['review_id']]['order_id'])]
   if not available:return dict(workspace_id=None,items=[],source=dataset,scope='本机尚未导入这些历史评价与订单，请先导入Olist样本。')
   if not ws:
    ws=dict(id=ws_id,name='Olist 历史数据练习',created_at=now(),members=[dict(id=actor,role='supervisor')],is_historical_practice=True,practice_owner=actor,source_dataset='olist',scope='匿名历史评价及只读订单；练习工单在本机保存，不代表当前真实客户投诉。');write(db,'workspace',ws)
   if ws.get('practice_owner')!=actor:raise KeyError('历史练习空间不属于当前体验者')
   items=[]
   for spec,review in available:
    session_id=ws_id+':'+spec['key'];session=read(db,'historical_practice',session_id)
    if not session:
     stamp=now();conv=dict(id=str(uuid.uuid4()),user_id=actor,workspace_id=ws_id,review_id=review['id'],title=spec['title'],source='Olist真实历史评价',knowledge_mode='business',order_id=review['order_id'],status='pending',owner=actor,created_at=stamp,updated_at=stamp,preview=review['content'][:100],is_historical_practice=True,practice_guide=spec['guide'],practice_key=spec['key'],intake=dict(issue_type=spec['issue'],desired_outcome='',quantity=None,evidence_note=''),case_history=[dict(at=stamp,actor=actor,action='根据Olist历史评价建立本地练习事项')])
     write(db,'conversation',conv)
     msg=dict(id=str(uuid.uuid4()),role='user',content=review['content'],created_at=stamp,source='真实葡萄牙语评价原文',source_created_at=review.get('created_at'),kind='customer_input')
     db.execute('INSERT INTO messages(conv_id,data) VALUES(?,?)',(conv['id'],json.dumps(msg,ensure_ascii=False)))
     ticket=self.ops.ticket_record(conv,'真实历史评价（非政策）：'+review['content']+'\n中文导读（人工整理，非客户逐字原话）：'+spec['guide'],review['id'])
     ticket.update(is_historical_practice=True,next_action=spec['next_action'],due_at=(datetime.fromisoformat(stamp)+timedelta(hours=4)).isoformat())
     ticket['history'].append(dict(at=stamp,actor=actor,owner=actor,action='预置本地练习行动；期限从建立时起算，不是历史客户承诺'))
     write(db,'ticket',ticket);session=dict(id=session_id,user_id=actor,workspace_id=ws_id,conv_id=conv['id'],ticket_id=ticket['id'],created_at=stamp);write(db,'historical_practice',session)
    conv=read(db,'conversation',session['conv_id']);ticket=read(db,'ticket',session['ticket_id']);order=read(db,'order',review['order_id'])
    if not conv or not ticket:continue
    items.append(dict(key=spec['key'],conv_id=conv['id'],ticket_id=ticket['id'],title=conv['title'],guide=spec['guide'],next_action=ticket.get('next_action'),status=ticket['status'],owner=ticket['owner'],due_at=ticket.get('due_at'),review=review,order=order))
   return dict(workspace_id=ws_id,items=items,source=dataset,scope=ws['scope'])
