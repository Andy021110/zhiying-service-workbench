"""Cached translations of immutable public historical reviews, separate from replies."""
import hashlib,json
from core.operations import read,write
from core.workbench import now

def fingerprint(review):
    return hashlib.sha256(json.dumps([review['id'],review.get('title',''),review['content'],'zh-CN'],ensure_ascii=False).encode()).hexdigest()

class ReviewTranslations:
    def __init__(self,store):self.store=store
    def review(self,id):
        review=self.store.get('review',id)
        if not review:raise KeyError('本地未收录此历史评价')
        return review
    def get(self,id):
        review=self.review(id);cached=self.store.get('review_translation',fingerprint(review))
        return dict(state='ready',**cached) if cached else dict(state='missing',review_id=id,target_language='zh-CN')
    async def ensure(self,id,actor,translate):
        review=self.review(id);key=fingerprint(review);cached=self.store.get('review_translation',key)
        if cached:return dict(state='ready',**cached)
        text=await translate(review)
        if not isinstance(text,str) or not text.strip() or len(text)>16000:raise RuntimeError('未获得有效译文，请稍后重试')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');current=read(db,'review',id)
            if not current or fingerprint(current)!=key:raise ValueError('评价原文已经变化，请重新读取后再翻译')
            cached=read(db,'review_translation',key)
            if not cached:
                cached=dict(id=key,review_id=id,original_title=review.get('title',''),original_content=review['content'],source_hash=key,source_language='pt-BR',target_language='zh-CN',text=text.strip(),machine_translated=True,created_at=now(),created_by=actor)
                write(db,'review_translation',cached)
            return dict(state='ready',**cached)
