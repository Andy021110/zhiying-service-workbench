"""Shared visibility policy; test retrieval never grants business approval."""

def infer_scope(document):
    text = ' '.join(str(document.get(k, '')) for k in ('id','title','source'))
    return 'test' if document.get('id','').startswith('legacy-') or any(w in text for w in ('示例','测试','验收','模拟')) else 'business'


def eligible_version(document, mode='test'):
    if not document or document.get('deleted'):
        return None
    if mode == 'business':
        if document.get('scope', infer_scope(document)) != 'business':
            return None
        return document.get('published_version') or None
    return document['version']


def source_is_current(document, source, mode='test'):
    return bool(document and eligible_version(document,mode) == source.get('version'))
