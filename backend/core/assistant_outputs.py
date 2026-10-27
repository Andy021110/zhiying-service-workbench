# -*- coding: utf-8 -*-
"""Separate staff references from customer drafts, including legacy utility results."""
def is_reference(message,messages=()):
 seen=set()
 while message and message.get('id') not in seen:
  seen.add(message.get('id'))
  if message.get('output_type')=='reference' or message.get('kind')=='assistant_reference' or message.get('knowledge_status')=='source_translation':return True
  if message.get('output_type')=='reply':return False
  request_id=message.get('reply_request_id')
  if request_id:
   source=next((m for m in messages if m.get('reply_request_id')==request_id and m.get('kind')=='staff_action'),None)
  else:
   index=next((i for i,m in enumerate(messages) if m['id']==message.get('id')),None)
   source=messages[index-1] if index else None
  if source and source.get('kind')=='staff_action' and source.get('action')!='redraft':return True
  message=next((m for m in messages if m['id']==message.get('parent_message_id')),None)
 return False

def public_messages(store,conv):
 messages=store.messages(conv['id']);review=store.get('review',conv.get('review_id','')) or {}
 for m in messages:
  if m['role']=='assistant' and is_reference(m,messages):m.update(output_type='reference')
  if m.get('source')=='真实葡萄牙语评价原文':
   m.update(source_review_created_at=review.get('review_creation_date') or m.get('source_created_at'),source_answered_at=review.get('review_answer_timestamp'))
 return messages
