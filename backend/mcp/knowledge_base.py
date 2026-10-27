"""
RAG 知识库 —— 基于 ChromaDB 的真实检索实现。

功能：
  1. 文档导入：将文本切片后存入 ChromaDB（自动生成 Embedding）
  2. 语义检索：根据 query 从知识库中检索最相关的文档片段
  3. 与 MCP 工具框架集成：作为 knowledge_search 工具的真实 handler

ChromaDB 在这里的角色：
  - memory/ 中用于存储对话记忆（情景记忆 + 用户画像）
  - 这里用于存储知识库文档（RAG 检索）
  两者是不同的 collection，互不干扰。
"""
import asyncio
import hashlib
import logging
import uuid
import threading
from functools import wraps
from core.workbench import WorkbenchStore, now
from core.knowledge_policy import infer_scope, eligible_version
from typing import Any, Dict, List, Optional

import chromadb
from core.embedding_provider import configured_embeddings

logger = logging.getLogger(__name__)


def synchronized(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self._document_lock:
            return method(self, *args, **kwargs)
    return run


class KnowledgeBase:
    """
    基于 ChromaDB 的 RAG 知识库。

    ChromaDB 内置了 Embedding 模型（all-MiniLM-L6-v2），
    调用 add() 时自动生成向量，query() 时自动做语义匹配。
    不需要额外调用 Anthropic Embeddings API。
    """

    COLLECTION_NAME = "knowledge_base"

    def __init__(
        self,
        chroma_host: str = "localhost",
        chroma_port: int = 8000,
        chroma_path: str = "./data/chroma",
    ):
        # 优先连接独立 ChromaDB 服务（服务端内置 embedding 模型，客户端无需下载）
        self._use_server = False
        try:
            # HttpClient 默认也会初始化 ChromaDB telemetry；显式关闭避免 posthog 兼容性错误日志。
            self._client = chromadb.HttpClient(
                host=chroma_host,
                port=chroma_port,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            self._client.heartbeat()
            self._use_server = True
            logger.info(f"知识库 ChromaDB 已连接: {chroma_host}:{chroma_port}")
        except Exception:
            logger.info(f"知识库 ChromaDB 服务不可用，使用本地模式: {chroma_path}")
            self._client = chromadb.PersistentClient(
                path=chroma_path,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )

        # 使用服务端时不传 embedding_function，让服务端处理
        # 本地模式时也不传，使用 ChromaDB 默认的（会触发模型下载）
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "知应 RAG 知识库"},
            **configured_embeddings(),
        )

        self._document_lock = threading.RLock()
        self.store = WorkbenchStore()
        self._migrate_documents()
        self._migrate_governance()

        # 如果知识库为空，导入默认文档
        if self._collection.count() == 0 and not self.store.list('document'):
            self._load_default_docs()

    # ── 文档管理 ──────────────────────────────────────────────────────────────

    def _migrate_documents(self):
        """Register existing chunks without re-embedding or changing their content."""
        raw = self._collection.get(include=['documents', 'metadatas'])
        groups = {}
        for id, content, meta in zip(raw['ids'], raw['documents'], raw['metadatas']):
            if meta.get('document_id'):
                continue
            groups.setdefault(meta.get('title', '未命名文档'), []).append((id, content, meta))
        for title, rows in groups.items():
            doc_id = 'legacy-' + hashlib.md5(title.encode()).hexdigest()[:16]
            if self.store.get('document', doc_id):
                continue
            rows.sort(key=lambda row: row[2].get('chunk_index', 0))
            doc = dict(id=doc_id, title=title, content='\n'.join(row[1] for row in rows),
                       version=1, updated_at=now(), created_at=now(), deleted=False,
                       source='原有示例知识（未核实企业政策）', status='ready', chunk_ids=[r[0] for r in rows])
            self.store.put('document', doc)
            self.store.put('document_version', dict(doc, id=f'{doc_id}:1', document_id=doc_id))
            self._collection.update(ids=[r[0] for r in rows], metadatas=[dict(r[2], document_id=doc_id, version=1, source=doc['source']) for r in rows])

    def _migrate_governance(self):
        # Existing examples remain testable; nothing is silently approved for business use.
        for doc in self.store.list('document'):
            if 'review_status' in doc:
                continue
            scope=infer_scope(doc)
            doc.update(scope=scope,review_status='draft',published_version=None,review_history=[])
            self.store.put('document',doc)
            for version in self.store.list('document_version'):
                if version['document_id']==doc['id']:
                    version.update(scope=scope,review_status='draft',published_version=None,review_history=[])
                    self.store.put('document_version',version)

    @synchronized
    def save_document(self, title, content, doc_id=None, source='手工导入（需业务审核）', expected_version=None, scope=None):
        title, content = title.strip(), content.strip()
        if not title or not content:
            raise ValueError('文档标题和正文不能为空')
        old = self.store.get('document', doc_id) if doc_id else None
        if doc_id and not old:
            raise KeyError(doc_id)
        if old and (expected_version != old['version'] or old.get('deleted')):
            raise ValueError('文档已变化或已归档，请重新加载后编辑')
        doc_id = doc_id or str(uuid.uuid4())
        version = old['version'] + 1 if old else 1
        scope=scope or (old or {}).get('scope') or infer_scope(dict(title=title,source=source))
        if scope not in {'test','business'}:
            raise ValueError('文档范围无效')
        chunks = self._chunk_text(content, 500)
        ids = [f'{doc_id}:v{version}:{i}' for i in range(len(chunks))]
        self._collection.upsert(ids=ids, documents=chunks, metadatas=[dict(title=title,
            document_id=doc_id, version=version, source=source, chunk_index=i, total_chunks=len(chunks)) for i in range(len(chunks))])
        published=(old or {}).get('published_version')
        if old and scope != old.get('scope',infer_scope(old)):
            published=None
        doc = dict(id=doc_id, title=title, content=content, version=version, source=source,scope=scope,
                   review_status='draft',published_version=published,review_history=(old or {}).get('review_history',[]),
                   deleted=False, status='ready', created_at=(old or {}).get('created_at', now()), updated_at=now(), chunk_ids=ids)
        self.store.put('document_version', dict(doc, id=f'{doc_id}:{version}', document_id=doc_id))
        self.store.put('document', doc)
        if old and old.get('chunk_ids') and old['version'] != published:
            self._collection.delete(ids=old['chunk_ids'])
        # A scope change withdraws the old business publication as well.
        if old and old.get('published_version') and not published and old['published_version']!=old['version']:
            prior=self.store.get('document_version',f"{doc_id}:{old['published_version']}")
            if prior and prior.get('chunk_ids'):
                self._collection.delete(ids=prior['chunk_ids'])
        return doc

    @synchronized
    def review_document(self, doc_id, action, version, actor, note):
        doc=self.store.get('document',doc_id)
        if not doc:
            raise KeyError(doc_id)
        if doc.get('deleted') or doc['version']!=version:
            raise ValueError('文档已变化或已归档，请重新加载')
        transitions={'submit':('draft','pending'),'approve':('pending','approved'),'reject':('pending','draft')}
        previous,target=transitions[action]
        if doc.get('review_status','draft')!=previous:
            raise ValueError('审核状态已变化，当前操作不可用')
        old_published=doc.get('published_version')
        doc['review_status']=target
        if action=='approve':
            doc['published_version']=version
            doc.update(reviewed_by=actor,reviewed_at=now())
        doc.setdefault('review_history',[]).append(dict(at=now(),actor=actor,note=note,action=action,
                                                     version=version,scope=doc['scope'],status=target))
        doc['updated_at']=now()
        self.store.put('document_version',dict(doc,id=f'{doc_id}:{version}',document_id=doc_id))
        self.store.put('document',doc)
        if action=='approve' and old_published and old_published!=version:
            prior=self.store.get('document_version',f'{doc_id}:{old_published}')
            if prior and prior.get('chunk_ids'):
                self._collection.delete(ids=prior['chunk_ids'])
        return doc

    @synchronized
    def archive_document(self, doc_id):
        doc = self.store.get('document', doc_id)
        if not doc:
            raise KeyError(doc_id)
        doc.update(deleted=True, status='archived', updated_at=now())
        self.store.put('document', doc)
        ids=list(doc.get('chunk_ids',[]))
        if doc.get('published_version') and doc['published_version']!=doc['version']:
            prior=self.store.get('document_version',f"{doc_id}:{doc['published_version']}")
            ids+=(prior or {}).get('chunk_ids',[])
        if ids:
            self._collection.delete(ids=list(set(ids)))
        return doc

    @synchronized
    def restore_document(self, doc_id):
        doc = self.store.get('document', doc_id)
        if not doc:
            raise KeyError(doc_id)
        if not doc.get('deleted'):
            raise ValueError('文档未归档，无需恢复')
        # Restoration is a new draft. Historical business approval is not automatically revived.
        old=dict(doc)
        doc.update(deleted=False,published_version=None)
        self.store.put('document',doc)
        try:
            return self.save_document(doc['title'],doc['content'],doc_id,doc['source'],doc['version'],doc.get('scope'))
        except Exception:
            self.store.put('document',old)
            raise

    def add_documents(self, documents):
        count = 0
        for item in documents:
            doc = self.save_document(item.get('title', ''), item.get('content', ''), source=item.get('source', '手工导入（需业务审核）'),scope=item.get('scope'))
            count += len(doc['chunk_ids'])
        return count

    async def add_documents_async(self, documents: List[Dict[str, str]]) -> int:
        """异步导入文档；ChromaDB 客户端为同步实现，因此放入线程池执行。"""
        return await asyncio.to_thread(self.add_documents, documents)

    def search(self, query: str, top_k: int = 5, mode: str = 'test') -> List[Dict[str, Any]]:
        eligible=[]
        for document in self.store.list('document'):
            version=eligible_version(document,mode)
            if version:
                eligible.append((document,version))
        if not eligible or not self._collection.count():
            return []
        filters=[{'$and':[{'document_id':doc['id']},{'version':version}]} for doc,version in eligible]
        total=0
        for doc,version in eligible:
            snapshot=doc if doc['version']==version else self.store.get('document_version',f"{doc['id']}:{version}")
            total+=len((snapshot or {}).get('chunk_ids',[]))
        results=self._collection.query(query_texts=[query],n_results=min(max(top_k*3,10),max(1,total)),
            where=filters[0] if len(filters)==1 else {'$or':filters})
        items=[]
        if results['documents'] and results['documents'][0]:
            for content,meta,dist in zip(results['documents'][0],results['metadatas'][0],results['distances'][0]):
                document=self.store.get('document',meta.get('document_id',''))
                if not document or eligible_version(document,mode)!=meta.get('version'):
                    continue
                version=meta['version']
                items.append(dict(title=meta.get('title',''),content=content,score=round(1.0-dist,4),
                    chunk=meta.get('chunk_index',0),document_id=document['id'],version=version,source=meta.get('source',document['source']),
                    scope=document.get('scope','test'),review_status='approved' if mode=='business' else document.get('review_status','draft'),
                    url=f"/knowledge/documents/{document['id']}?version={version}"))
        return items[:top_k]

    async def search_async(self, query: str, top_k: int = 5, mode: str = 'test') -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self.search,query,top_k,mode)

    @property
    def doc_count(self) -> int:
        return self._collection.count()

    async def doc_count_async(self) -> int:
        """异步获取文档片段数量。"""
        return await asyncio.to_thread(self._collection.count)

    # ── MCP 工具 handler ─────────────────────────────────────────────────────

    async def search_handler(self, params: Dict[str, Any], context: Any) -> List[Dict]:
        """
        作为 MCP 工具的 handler 注册。

        MCPToolManager.register(Tool(
            name="knowledge_search",
            handler=kb.search_handler,
            ...
        ))
        """
        query = params.get("query", "")
        top_k = params.get("top_k", 5)
        return await self.search_async(query,top_k=top_k,mode=params.get("knowledge_mode", "test"))

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    def _chunk_text(self, text: str, chunk_size: int = 500) -> List[str]:
        chunks, remaining = [], text.strip()
        while remaining:
            if len(remaining) <= chunk_size:
                chunks.append(remaining)
                break
            cut = max(remaining.rfind('。', 0, chunk_size), remaining.rfind('\n', 0, chunk_size)) + 1
            if cut < chunk_size // 2:
                cut = chunk_size
            chunk = remaining[:cut].strip()
            if chunk:
                chunks.append(chunk)
            remaining = remaining[cut:].strip()
        return chunks

    def _load_default_docs(self) -> None:
        """导入默认知识库文档（客服场景常见问题）。"""
        default_docs = [
            {
                "title": "退款政策",
                "content": (
                    "退款政策说明。"
                    "用户在购买后 7 天内可以申请无理由退款。"
                    "退款申请提交后，系统会在 1-3 个工作日内审核。"
                    "审核通过后，款项将在 5-7 个工作日内退回原支付账户。"
                    "如果商品已发货，需要先完成退货流程才能退款。"
                    "退货运费由用户承担，除非是商品质量问题。"
                    "超过 7 天但未超过 30 天的订单，需要提供商品质量问题的证据才能退款。"
                ),
            },
            {
                "title": "订单查询",
                "content": (
                    "订单查询指南。"
                    "用户可以通过订单号查询订单状态。"
                    "订单状态包括：待支付、已支付、已发货、运输中、已签收、已完成。"
                    "如果订单显示已发货但超过 7 天未收到，可以联系客服申请查件。"
                    "物流信息通常在发货后 24 小时内更新。"
                    "如果订单显示异常，请提供订单号联系客服处理。"
                ),
            },
            {
                "title": "账户安全",
                "content": (
                    "账户安全说明。"
                    "建议用户定期修改密码，密码长度至少 8 位，包含字母和数字。"
                    "如果忘记密码，可以通过绑定的手机号或邮箱重置。"
                    "发现账户异常登录时，系统会自动锁定账户并发送通知。"
                    "用户可以在安全设置中开启两步验证，提高账户安全性。"
                    "不要将密码分享给他人，客服人员不会索要用户密码。"
                ),
            },
            {
                "title": "技术故障排查",
                "content": (
                    "常见技术问题排查。"
                    "应用崩溃：请尝试清除缓存后重启应用，如果问题持续请更新到最新版本。"
                    "登录失败 401 错误：表示认证失败，请检查用户名密码是否正确，或尝试重置密码。"
                    "页面加载慢：检查网络连接，尝试切换 WiFi 或移动数据。"
                    "支付失败：确认银行卡余额充足，检查是否开启了网上支付功能。"
                    "500 服务器错误：这是服务端问题，请稍后重试，如果持续出现请联系技术支持。"
                ),
            },
            {
                "title": "会员与积分",
                "content": (
                    "会员积分规则。"
                    "每消费 1 元累积 1 积分。"
                    "积分可以在下次购物时抵扣，100 积分 = 1 元。"
                    "会员等级分为：普通会员、银卡会员（累计消费 1000 元）、金卡会员（累计消费 5000 元）。"
                    "银卡会员享受 95 折优惠，金卡会员享受 9 折优惠。"
                    "积分有效期为 1 年，过期自动清零。"
                    "生日当月消费可获得双倍积分。"
                ),
            },
            {
                "title": "配送说明",
                "content": (
                    "配送服务说明。"
                    "标准配送：3-5 个工作日送达，免运费（订单满 99 元）。"
                    "加急配送：1-2 个工作日送达，运费 15 元。"
                    "同城配送：当日达或次日达，运费 10 元。"
                    "偏远地区可能需要额外 2-3 天。"
                    "配送时间为每天 9:00-18:00，节假日可能延迟。"
                    "如果需要修改收货地址，请在发货前联系客服。"
                ),
            },
        ]
        for doc in default_docs:
            doc['source']='内置示例知识（未核实企业政策）'
        self.add_documents(default_docs)
        logger.info(f"已导入默认知识库: {len(default_docs)} 篇文档")
