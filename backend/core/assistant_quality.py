"""Small, traceable guards for domain routing and uncovered policy questions."""
import re


def active_problem_text(message):
    # Negated examples and prohibitions are not additional customer problems.
    text=re.sub(r'(?:不涉及|没有涉及|不要声称|不得声称|不要继续假定)[^，。；;\n]*', '', message or '')
    text=re.sub(r'(?:不再|没有再|不会再|不)(?:崩溃|报错|闪退)(?:了)?', '', text)
    return re.sub(r'不是(?:重复扣款|多扣|退款问题|登录故障)(?:问题|原因)?', '', text)


def extract_error_codes(message):
    text=message or '';codes=[]
    for match in re.finditer(r'(?<![A-Za-z0-9])([45]\d{2})(?![A-Za-z0-9])',text):
        before=text[max(0,match.start()-10):match.start()];after=text[match.end():match.end()+8]
        if re.match(r'\s*(?:元|块|美元|人民币|rmb|cny|usd)',after,re.I):continue
        if re.search(r'(?:订单号?|电话|金额|数量)[：:\s]*$',before):continue
        codes.append(match.group(1))
    codes.extend(m.group(0).upper() for m in re.finditer(r'(?i)(?<![a-z0-9])E(?:RR(?:OR)?)?[-_]?\d{3,6}(?![a-z0-9])',text))
    return list(dict.fromkeys(codes))


def problem_domains(message):
    text=active_problem_text(message).lower()
    technical=bool(re.search(r'崩溃|报错|无法登录|登录失败|闪退|error|crash',text) or extract_error_codes(text))
    billing=bool(re.search(r'退款|退货|扣款|发票|账单|支付|订阅|refund|invoice|多扣',text))
    return technical,billing


POLICY_TOPICS=[
    ('进口税',r'进口税|关税',r'进口税|关税','补充订单适用地区、税款凭证及适用的税费退还规则'),
    ('汇率损失',r'汇率|汇兑',r'汇率|汇兑','补充支付币种、结算记录及汇兑损失承担条款'),
    ('三倍赔偿',r'三倍赔偿|三倍补偿|赔三倍',r'三倍赔偿|三倍补偿|赔三倍','补充适用合同或赔偿规则及触发条件'),
    ('重复扣款处理',r'重复扣款|两次扣款|多扣',r'重复扣款|两次扣款|多扣','补充交易流水及重复扣款核对、退回的适用规则'),
]


def knowledge_gaps(message,sources):
    # A matching refund paragraph does not establish customs/FX/double-charge policy.
    gaps=[]
    for label,query_pattern,evidence_pattern,next_step in POLICY_TOPICS:
        if not re.search(query_pattern,active_problem_text(message)):continue
        covered=any(re.search(evidence_pattern,line) and not re.search(r'未规定|未涉及|未涵盖|没有.{0,10}(?:规定|条款|规则)',line) for s in sources for line in s.get('content','').splitlines())
        if not covered:gaps.append(dict(topic=label,status='依据不足',next_step=next_step))
    return gaps


def gap_prompt(gaps):
    if not gaps:return ''
    return '[逐项知识边界：依据不足，禁止推断这些项目的政策或金额]\n'+'\n'.join(f"- {g['topic']}：{g['next_step']}" for g in gaps)


def gap_notice(gaps):
    if not gaps:return ''
    return '### 尚缺依据的具体问题\n'+'\n'.join(f"- **{g['topic']}**：当前检索依据不足，无法确认。下一步：{g['next_step']}。" for g in gaps)


def issue_updates(text):
    # Questions about recovery are not reports that recovery occurred.
    text=re.sub(r'[^。！？?\n]*[？?]','',text)
    updates={}
    if re.search(r'登录(?:已经|已)?恢复|已经(?:可以)?正常(?:进入|登录)|现在能登录|可以正常登录',text):updates['technical']='customer_reports_recovered'
    elif re.search(r'无法登录|登录失败|崩溃|报错|闪退',text):updates['technical']='customer_reports_problem'
    if re.search(r'两笔.{0,12}(?:不同|分别).{0,12}订单|分别对应不同订单',text):updates['payment']='different_orders'
    elif re.search(r'不是.{0,10}(?:重复扣款|多扣).{0,10}(?:是|只是).{0,8}支付失败',text):updates['payment']='payment_failed'
    elif re.search(r'重复扣款|多扣|两笔交易|支付失败',active_problem_text(text)):updates['payment']='customer_reports_pending'
    return updates


def ensure_gap_notice(response,gaps):
    missing=[g for g in gaps if not re.search(re.escape(g['topic'])+r'.{0,180}(?:无法确认|依据不足|未涉及|没有.{0,16}(?:规则|条款))',response,re.S)]
    return response+('\n\n'+gap_notice(missing) if missing else '')


def only_uncovered_policy_questions(message,gaps):
    if not gaps:return False
    # Distinguish a hit about general refunds from evidence about customs/FX.
    # Consider the question portion, not later staff instructions mentioning policies.
    question=re.split(r'请逐项|请分别|请依据|请准备|请说明|不要|不得',message,maxsplit=1)[0]
    if re.search(r'登录|崩溃|故障|报错|排查',question):return False
    known_question=re.search(r'(?:如何|怎么|怎样).{0,18}(?:退款|退货|配送|积分)|退款.{0,8}(?:审核|到账)|退货流程',question)
    special=[g for g in gaps if g['topic'] in {'进口税','汇率损失','三倍赔偿'}]
    return bool(special) and not known_question
