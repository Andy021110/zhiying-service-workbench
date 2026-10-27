"""Describe actual reply processing, separate from request completion or intent recognition."""

def reply_trace(payload):
    status=payload.get('knowledge_status','')
    outcomes=payload.get('agent_outcomes') or []
    if outcomes:
        return dict(execution_path='agent',agent_execution_status=payload.get('execution_status','unknown'),processing_reason='已执行所列回复Agent；完成表示执行返回，不代表客户问题已经解决。')
    if payload.get('execution_path')=='clarification':
        return dict(execution_path='clarification',agent_execution_status='not_run',processing_reason='需求尚不明确，直接追问澄清，未执行回复Agent。')
    if status in {'no_match','unavailable'}:
        return dict(execution_path='knowledge_guard',agent_execution_status='not_run',processing_reason='没有适用的可核对知识，直接整理已知事实、待补信息和规则缺口；未执行回复Agent。' if status=='no_match' else '知识检索暂不可用，已返回待核对信息；未执行回复Agent。')
    if status in {'order_fact','record_reference'}:
        return dict(execution_path='record_query',agent_execution_status='not_run',processing_reason='直接读取本地记录并计算或整理事实，未执行回复Agent。')
    if status=='conversation_context':
        return dict(execution_path='context_recall',agent_execution_status='not_run',processing_reason='直接核对已有客户原话，未执行回复Agent。')
    if status in {'source_translation','draft_translation'}:
        return dict(execution_path='translation',agent_execution_status='unknown',processing_reason='译稿处理，模型执行或缓存情况需另核对翻译调用记录；不能从本条推断Agent已执行。')
    return dict(execution_path='unknown',agent_execution_status='unknown',processing_reason='此条未保存完整回复Agent执行明细，不能仅凭默认类型或请求完成状态认定已调用。')
