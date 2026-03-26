"""
知识库管理器：负责知识库的创建、删除、文档管理和索引构建。
"""

import json
import logging
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from config.config import RAG_CONFIG
from server.rag.v1.embedding.embedding_model import EmbeddingModel
from server.rag.v1.tool.load_file import ReadFiles
from server.rag.v1.vectorstore.vectorstore import VectorStore

logger = logging.getLogger(__name__)


class KnowledgeBaseManager:
    def __init__(self, base_path: str = None):
        self.base_path = Path(base_path or RAG_CONFIG["knowledge_base_path"])
        self.base_path.mkdir(parents=True, exist_ok=True)
        # 每个知识库一把锁，防止并发索引冲突
        self._locks: dict[str, threading.Lock] = {}
        # 索引构建状态追踪
        self._indexing_status: dict[str, dict] = {}

    def _kb_path(self, kb_id: str) -> Path:
        return self.base_path / kb_id

    def _meta_path(self, kb_id: str) -> Path:
        return self._kb_path(kb_id) / "meta.json"

    def _docs_path(self, kb_id: str) -> Path:
        return self._kb_path(kb_id) / "documents"

    def _storage_path(self, kb_id: str) -> Path:
        return self._kb_path(kb_id) / "storage"

    def _get_lock(self, kb_id: str) -> threading.Lock:
        if kb_id not in self._locks:
            self._locks[kb_id] = threading.Lock()
        return self._locks[kb_id]

    def _read_meta(self, kb_id: str) -> dict | None:
        meta_file = self._meta_path(kb_id)
        if not meta_file.exists():
            return None
        with open(meta_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_meta(self, kb_id: str, meta: dict):
        with open(self._meta_path(kb_id), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    # ======================== CRUD ========================

    def create(self, name: str, description: str = "") -> str:
        kb_id = f"kb_{uuid.uuid4().hex[:12]}"
        kb_path = self._kb_path(kb_id)
        kb_path.mkdir(parents=True)
        self._docs_path(kb_id).mkdir()
        self._storage_path(kb_id).mkdir()

        meta = {
            "kb_id": kb_id,
            "name": name,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "doc_count": 0,
            "indexed": False,
            "index_time": None,
        }
        self._write_meta(kb_id, meta)
        logger.info(f"知识库已创建: {name} ({kb_id})")
        return kb_id

    def list_all(self) -> list[dict]:
        results = []
        if not self.base_path.exists():
            return results
        for item in sorted(self.base_path.iterdir()):
            if item.is_dir() and (item / "meta.json").exists():
                meta = self._read_meta(item.name)
                if meta:
                    results.append(meta)
        return results

    def get(self, kb_id: str) -> dict | None:
        meta = self._read_meta(kb_id)
        if meta is None:
            return None
        meta["documents"] = self.list_documents(kb_id)
        return meta

    def update(self, kb_id: str, name: str = None, description: str = None) -> bool:
        meta = self._read_meta(kb_id)
        if meta is None:
            return False
        if name is not None:
            meta["name"] = name
        if description is not None:
            meta["description"] = description
        meta["updated_at"] = datetime.now().isoformat()
        self._write_meta(kb_id, meta)
        return True

    def delete(self, kb_id: str) -> bool:
        kb_path = self._kb_path(kb_id)
        if not kb_path.exists():
            return False
        shutil.rmtree(kb_path)
        self._locks.pop(kb_id, None)
        self._indexing_status.pop(kb_id, None)
        logger.info(f"知识库已删除: {kb_id}")
        return True

    # ======================== 文档管理 ========================

    def add_document(self, kb_id: str, src_path: str, original_name: str = None) -> str | None:
        meta = self._read_meta(kb_id)
        if meta is None:
            return None

        doc_id = uuid.uuid4().hex[:8]
        filename = original_name or os.path.basename(src_path)
        dest_name = f"{doc_id}_{filename}"
        dest_path = self._docs_path(kb_id) / dest_name

        shutil.copy2(src_path, dest_path)

        meta["doc_count"] = self._count_documents(kb_id)
        meta["indexed"] = False  # 新增文档后标记需要重新索引
        meta["updated_at"] = datetime.now().isoformat()
        self._write_meta(kb_id, meta)

        logger.info(f"文档已添加到知识库 {kb_id}: {filename} (doc_id={doc_id})")
        return doc_id

    def remove_document(self, kb_id: str, doc_id: str) -> bool:
        docs_dir = self._docs_path(kb_id)
        if not docs_dir.exists():
            return False

        removed = False
        for f in docs_dir.iterdir():
            if f.name.startswith(doc_id + "_"):
                f.unlink()
                removed = True
                break

        if removed:
            meta = self._read_meta(kb_id)
            if meta:
                meta["doc_count"] = self._count_documents(kb_id)
                meta["indexed"] = False
                meta["updated_at"] = datetime.now().isoformat()
                self._write_meta(kb_id, meta)
            logger.info(f"文档已从知识库 {kb_id} 删除: doc_id={doc_id}")
        return removed

    def list_documents(self, kb_id: str) -> list[dict]:
        docs_dir = self._docs_path(kb_id)
        if not docs_dir.exists():
            return []

        documents = []
        for f in sorted(docs_dir.iterdir()):
            if f.is_file():
                parts = f.name.split("_", 1)
                doc_id = parts[0] if len(parts) > 1 else f.stem
                display_name = parts[1] if len(parts) > 1 else f.name
                stat = f.stat()
                documents.append({
                    "doc_id": doc_id,
                    "filename": display_name,
                    "size": stat.st_size,
                    "uploaded_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        return documents

    def _count_documents(self, kb_id: str) -> int:
        docs_dir = self._docs_path(kb_id)
        if not docs_dir.exists():
            return 0
        return sum(1 for f in docs_dir.iterdir() if f.is_file())

    # ======================== 索引构建 ========================

    def build_index(self, kb_id: str) -> bool:
        """同步构建索引。大文档集请在后台线程调用。"""
        lock = self._get_lock(kb_id)
        if not lock.acquire(blocking=False):
            logger.warning(f"知识库 {kb_id} 正在索引中，跳过重复请求")
            return False

        self._indexing_status[kb_id] = {"status": "indexing", "progress": "读取文档..."}
        try:
            docs_dir = self._docs_path(kb_id)
            storage_dir = self._storage_path(kb_id)

            if not docs_dir.exists() or self._count_documents(kb_id) == 0:
                logger.warning(f"知识库 {kb_id} 无文档，跳过索引")
                self._indexing_status[kb_id] = {"status": "error", "progress": "知识库中没有文档"}
                return False

            # 读取并切分文档（带来源追踪）
            self._indexing_status[kb_id]["progress"] = "切分文档..."
            max_token_len = RAG_CONFIG.get("max_token_len", 600)
            cover_content = RAG_CONFIG.get("cover_content", 150)
            reader = ReadFiles(str(docs_dir))
            docs, sources = reader.get_content_with_source(
                max_token_len=max_token_len,
                cover_content=cover_content,
            )

            if not docs:
                logger.warning(f"知识库 {kb_id} 文档内容为空")
                self._indexing_status[kb_id] = {"status": "error", "progress": "文档内容为空，请检查上传的文件是否包含有效文本"}
                return False

            # 生成向量
            self._indexing_status[kb_id]["progress"] = f"生成向量 (共{len(docs)}个片段)..."
            vector = VectorStore(docs, sources=sources)
            embedding = EmbeddingModel()
            vector.get_vector(EmbeddingModel=embedding)

            # 持久化
            self._indexing_status[kb_id]["progress"] = "保存向量..."
            vector.persist(path=str(storage_dir))

            # 更新 meta
            meta = self._read_meta(kb_id)
            if meta:
                meta["indexed"] = True
                meta["index_time"] = datetime.now().isoformat()
                meta["doc_count"] = self._count_documents(kb_id)
                meta["chunk_count"] = len(docs)
                meta["updated_at"] = datetime.now().isoformat()
                self._write_meta(kb_id, meta)

            self._indexing_status[kb_id] = {
                "status": "done",
                "progress": f"索引构建完成，共 {len(docs)} 个片段",
                "chunk_count": len(docs),
            }
            logger.info(f"知识库 {kb_id} 索引构建完成，共 {len(docs)} 个片段")
            return True

        except Exception as e:
            logger.error(f"知识库 {kb_id} 索引构建失败: {e}", exc_info=True)
            self._indexing_status[kb_id] = {"status": "error", "progress": f"索引失败: {e}"}
            return False
        finally:
            lock.release()

    def build_index_async(self, kb_id: str):
        """在后台线程中异步构建索引。"""
        self._indexing_status[kb_id] = {"status": "indexing", "progress": "准备中..."}
        thread = threading.Thread(target=self.build_index, args=(kb_id,), daemon=True)
        thread.start()

    def get_index_status(self, kb_id: str) -> dict:
        if kb_id in self._indexing_status:
            return self._indexing_status[kb_id]
        meta = self._read_meta(kb_id)
        if meta and meta.get("indexed"):
            return {"status": "done", "progress": "索引已就绪", "index_time": meta.get("index_time")}
        return {"status": "not_indexed", "progress": "尚未构建索引"}

    def is_indexed(self, kb_id: str) -> bool:
        meta = self._read_meta(kb_id)
        return meta is not None and meta.get("indexed", False)
