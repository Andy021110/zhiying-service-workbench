"""Local factual answers are separate from policy retrieval and translation."""
import re
from datetime import datetime

POLICY=re.compile(r'(?:赔付|赔偿|退款|退货|保修|权益).{0,12}(?:多少|标准|条件|规则|流程|怎么|如何|多久|比例|申请|可以|能否|能不能|吗|？|\?)|(?:能否|能不能|可以).{0,8}(?:赔付|赔偿|退款|退货)')

def wants_policy(text):return bool(POLICY.search(text) or re.search(r'补发|换货|退换|维修|赔付|赔偿|补偿|退款|退货|保修',text))

def pure_order_question(text):
    # A factual keyword must not swallow a complaint or a mixed service question.
    return not wants_policy(text) and not re.search(r'缺件|缺少|缺了|少了|少发|漏发|漏件|缺货|丢件|错发|发错|不对|不全|破损|损坏|坏了|没收到|未收到|没有收到|售后|投诉|不满|说法|异议|不认可|怎么办|帮我处理|给我处理|处理一下|怎么处理|如何处理|接下来|下一步|谁负责|联系我|联系谁|处理结果|处理办法|解决',text)

def is_translation(text):return any(w in text.lower() for w in ('翻译','translate','译成中文','概括客户诉求','总结客户诉求'))

def order_fact(text,order):
    if not order:return None
    label=('合成演示订单 ' if order.get('is_demo') else '本地Olist历史订单 ')+order.get('display_id',order['id'])
    currency=order.get('currency','BRL')
    result=None
    if any(w in text for w in ('晚到','晚了','比预计','迟到','延迟','逾期')):
        estimated,actual=order.get('estimated_at',''),order.get('delivered_at','')
        if estimated and actual:
            days=(datetime.fromisoformat(actual).date()-datetime.fromisoformat(estimated).date()).days
            difference=f'按日期比较晚 {days} 个自然日' if days>0 else f'按日期比较提前 {-days} 个自然日' if days<0 else '按日期比较同日送达'
            result=f'预计送达日期为 {estimated[:10]}，实际送达日期为 {actual[:10]}，{difference}。此处只比较历史日期，不推断赔付或合同/SLA口径。'
        else:result='历史记录缺少预计或实际送达日期，无法计算晚到天数；未记录实际送达不等于已经送达。'
    elif any(w in text for w in ('订单状态','物流状态','送达日期','购买日期','订单金额','运费','商品明细','商品清单','商品信息','买了什么')):
        status={'delivered':'已送达','canceled':'已取消','shipped':'已发货','processing':'处理中'}.get(order['status'],order['status'])
        result=f"历史状态：{status}；购买日期：{order.get('purchased_at') or '未记录'}；预计送达：{order.get('estimated_at') or '未记录'}；实际送达：{order.get('delivered_at') or '未记录'}。商品与运费合计：{order.get('total')} {currency}。"
        if any(w in text for w in ('商品','运费','买了什么')):
            result+='\n'+'\n'.join(f"匿名商品 {i['product_id']}：商品 {i['price']:.2f} {currency}，运费 {i['freight']:.2f} {currency}。" for i in order.get('items',[]))
    if not result:return None
    return dict(response=label+'\n'+result+'\n这是历史快照，未执行任何订单操作。',data_sources=[dict(kind='order',label='历史订单原记录',id=order['id'],url='/orders/'+order['id'])])
