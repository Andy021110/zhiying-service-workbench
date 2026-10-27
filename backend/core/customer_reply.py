# -*- coding: utf-8 -*-
"""Customer-facing wording; record IDs stay in structured source metadata."""
import re

def staff_labels(store,conv,actor=None):
    ids={conv.get('owner'),conv.get('user_id'),actor}-{'待分派',None,''}
    ws=store.get('workspace',conv.get('workspace_id','')) or {}
    members={m['id']:m for m in ws.get('members',[])}
    labels={}
    for id in ids:
        name=members.get(id,{}).get('display_name','').strip()
        labels[id]=name if name and name!=id else '当前负责客服'
    return labels

def customer_text(text,sources,labels):
    # Replace only known internal identities, never guessed departments or customer facts.
    for source in sources:
        id=source.get('document_id','')
        if id:text=text.replace(id,source.get('title','所引规则')+' v'+str(source.get('version','')))
    for id,label in sorted(labels.items(),key=lambda item:-len(item[0])):
        text=re.sub(r'(?<![A-Za-z0-9_-])'+re.escape(id)+r'(?![A-Za-z0-9_-])',lambda _:label,text)
    return text

def responsibility_prompt(store,conv):
    owner=conv.get('owner')
    label=staff_labels(store,conv).get(owner,'尚未分派，需人工明确责任人')
    return '[已核实的责任信息] 当前事项责任人称呼：'+label+'。用户标识不代表部门、岗位或业务环节，禁止从标识推测角色。只根据此责任信息回答谁负责。跟进期限是内部待办时间，不能当作客户承诺的处理完成时限。面向客户直接说明已知事实和下一步；来源使用规则标题、版本或[1]编号，内部文档编号、用户标识不得进入回复正文。'
