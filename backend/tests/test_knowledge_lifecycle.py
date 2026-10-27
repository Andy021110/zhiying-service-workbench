import tempfile
import threading
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from core.workbench import WorkbenchStore
from mcp.knowledge_base import KnowledgeBase


class FakeCollection:
    def __init__(self):
        self.rows={}; self.fail=False
    def upsert(self,ids,documents,metadatas):
        if self.fail: raise RuntimeError('index unavailable')
        self.rows.update({id:(doc,meta) for id,doc,meta in zip(ids,documents,metadatas)})
    def delete(self,ids):
        for id in ids: self.rows.pop(id,None)
    def count(self): return len(self.rows)
    def query(self,query_texts,n_results,where=None):
        def matches(meta,clause):
            if not clause:return True
            if '$and' in clause:return all(matches(meta,c) for c in clause['$and'])
            if '$or' in clause:return any(matches(meta,c) for c in clause['$or'])
            return all(meta.get(k)==v for k,v in clause.items())
        rows=[row for row in self.rows.values() if matches(row[1],where)][:n_results]
        return dict(documents=[[r[0] for r in rows]],metadatas=[[r[1] for r in rows]],distances=[[.1]*len(rows)])


class KnowledgeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.kb=KnowledgeBase.__new__(KnowledgeBase)
        self.kb.store=WorkbenchStore(Path(self.temp.name)/'db.sqlite');self.kb._collection=FakeCollection();self.kb._document_lock=threading.RLock()
        self.doc=self.kb.save_document('测试政策','保障期为42个月',source='模拟验收')
    def test_edit_removes_old_index_but_retains_citable_version(self):
        self.kb.save_document('测试政策','保障期为84个月',self.doc['id'],'模拟验收',1)
        self.assertEqual(self.kb.search('保障期')[0]['version'],2)
        self.assertEqual(self.kb.store.get('document_version',self.doc['id']+':1')['content'],'保障期为42个月')
        self.assertEqual(len(self.kb._collection.rows),1)
    def test_archive_excludes_and_restore_versions(self):
        self.kb.archive_document(self.doc['id']);self.assertEqual(self.kb.search('保障期'),[])
        restored=self.kb.restore_document(self.doc['id'])
        self.assertEqual(restored['version'],2);self.assertEqual(len(self.kb.search('保障期')),1)
    def test_failed_index_write_keeps_previous_version(self):
        self.kb._collection.fail=True
        with self.assertRaises(RuntimeError):self.kb.save_document('测试政策','新版',self.doc['id'],'模拟验收',1)
        self.assertEqual(self.kb.store.get('document',self.doc['id'])['version'],1)
        self.assertEqual(self.kb.search('保障期')[0]['content'],'保障期为42个月')
    def test_stale_and_concurrent_edits_cannot_overwrite_version(self):
        def edit(value):
            try:
                self.kb.save_document('测试政策',value,self.doc['id'],'模拟验收',1)
                return 'saved'
            except ValueError:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(edit,['新版一','新版二']))
        self.assertEqual(sorted(results),['conflict','saved'])
