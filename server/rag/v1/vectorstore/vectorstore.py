import logging
import os
from typing import List, Dict
import numpy as np
import uuid

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, document: List[str] = None, sources: List[str] = None) -> None:
        """
        初始化向量存储类，存储文档和对应的向量表示，并生成唯一的文档ID。
        :param document: 文档列表，默认为空。
        :param sources: 每个文档片段对应的来源文件名列表，与 document 等长。
        """
        if document is None:
            document = []
        self.document = document
        self.vectors = []
        self.doc_ids = []
        self.vector_ids = []
        self.sources = sources if sources else ["" for _ in document]

        # 为每个文档生成唯一ID
        self.doc_ids = [str(uuid.uuid4()) for _ in self.document]

    def get_vector(self, EmbeddingModel) -> List[Dict[str, List[float]]]:
        """
        使用传入的 Embedding 模型将文档向量化，并生成唯一的向量块ID。
        """
        self.vectors = []
        total = len(self.document)
        for i, doc in enumerate(self.document):
            try:
                vec = EmbeddingModel.get_embedding(doc)
                if not vec:
                    logger.warning(f"文档片段 {i+1}/{total} 生成了空向量，跳过")
                    vec = []
                self.vectors.append(vec)
            except Exception as e:
                logger.error(f"文档片段 {i+1}/{total} 向量化失败: {e}")
                self.vectors.append([])

        self.vector_ids = [str(uuid.uuid4()) for _ in self.vectors]
        return [{"vector_id": vec_id, "vector": vector}
                for vec_id, vector in zip(self.vector_ids, self.vectors)]

    def persist(self, path: str = 'storage'):
        """
        将文档、向量、来源信息持久化到本地目录中。
        """
        if not os.path.exists(path):
            os.makedirs(path)

        # 过滤掉空向量的条目
        valid_indices = [i for i, v in enumerate(self.vectors) if v]
        if not valid_indices:
            logger.warning("没有有效向量可以持久化")
            return

        valid_vectors = [self.vectors[i] for i in valid_indices]
        valid_docs = [self.document[i] for i in valid_indices]
        valid_doc_ids = [self.doc_ids[i] for i in valid_indices]
        valid_vector_ids = [self.vector_ids[i] for i in valid_indices]
        valid_sources = [self.sources[i] if i < len(self.sources) else "" for i in valid_indices]

        np.save(os.path.join(path, 'vectors.npy'), valid_vectors)

        with open(os.path.join(path, 'documents.txt'), 'w', encoding='utf-8') as f:
            for doc, doc_id in zip(valid_docs, valid_doc_ids):
                # 把文档中的换行替换为特殊标记，防止破坏行格式
                safe_doc = doc.replace('\n', '\\n').replace('\t', '\\t')
                f.write(f"{doc_id}\t{safe_doc}\n")

        with open(os.path.join(path, 'vector_ids.txt'), 'w', encoding='utf-8') as f:
            for vector_id in valid_vector_ids:
                f.write(f"{vector_id}\n")

        # 保存来源信息
        with open(os.path.join(path, 'sources.txt'), 'w', encoding='utf-8') as f:
            for doc_id, source in zip(valid_doc_ids, valid_sources):
                f.write(f"{doc_id}\t{source}\n")

        logger.info(f"已持久化 {len(valid_vectors)} 个向量到 {path}")

    def load_vector(self, path: str = 'storage'):
        """
        从本地加载之前保存的数据，包含完善的容错处理。
        """
        vectors_file = os.path.join(path, 'vectors.npy')
        docs_file = os.path.join(path, 'documents.txt')

        if not os.path.exists(vectors_file):
            raise FileNotFoundError(f"向量文件不存在: {vectors_file}")
        if not os.path.exists(docs_file):
            raise FileNotFoundError(f"文档文件不存在: {docs_file}")

        try:
            self.vectors = np.load(vectors_file, allow_pickle=True).tolist()
        except Exception as e:
            raise RuntimeError(f"加载向量文件失败: {e}")

        self.document = []
        self.doc_ids = []
        try:
            with open(docs_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split('\t', 1)
                    if len(parts) < 2:
                        logger.warning(f"文档文件第 {line_num} 行格式异常，跳过")
                        continue
                    doc_id, doc = parts
                    # 还原换行和制表符
                    doc = doc.replace('\\n', '\n').replace('\\t', '\t')
                    self.doc_ids.append(doc_id)
                    self.document.append(doc)
        except Exception as e:
            raise RuntimeError(f"加载文档文件失败: {e}")

        # 加载向量ID
        vector_ids_file = os.path.join(path, 'vector_ids.txt')
        if os.path.exists(vector_ids_file):
            with open(vector_ids_file, 'r', encoding='utf-8') as f:
                self.vector_ids = [line.strip() for line in f if line.strip()]
        else:
            self.vector_ids = [str(uuid.uuid4()) for _ in self.vectors]

        # 加载来源信息
        self.sources = ["" for _ in self.document]
        sources_file = os.path.join(path, 'sources.txt')
        if os.path.exists(sources_file):
            source_map = {}
            with open(sources_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split('\t', 1)
                    if len(parts) == 2:
                        source_map[parts[0]] = parts[1]
            self.sources = [source_map.get(did, "") for did in self.doc_ids]

        # 一致性校验
        min_len = min(len(self.vectors), len(self.document))
        if len(self.vectors) != len(self.document):
            logger.warning(
                f"向量数量({len(self.vectors)})与文档数量({len(self.document)})不一致，"
                f"将截取前 {min_len} 条"
            )
            self.vectors = self.vectors[:min_len]
            self.document = self.document[:min_len]
            self.doc_ids = self.doc_ids[:min_len]
            self.sources = self.sources[:min_len]

        logger.info(f"已加载 {len(self.vectors)} 个向量，来自 {path}")

    def get_similarity(self, vector1: List[float], vector2: List[float]) -> float:
        """计算两个向量的余弦相似度。"""
        if not vector1 or not vector2:
            return 0.0
        dot_product = np.dot(vector1, vector2)
        magnitude = np.linalg.norm(vector1) * np.linalg.norm(vector2)
        if not magnitude:
            return 0.0
        return float(dot_product / magnitude)

    def query(self, query: str, EmbeddingModel, k: int = 1,
              min_similarity: float = 0.0) -> List[Dict[str, str]]:
        """
        根据用户的查询文本，检索最相关的文档片段。
        :param query: 用户的查询文本。
        :param EmbeddingModel: 用于将查询向量化的嵌入模型。
        :param k: 返回最相似的文档数量，默认为 1。
        :param min_similarity: 最低相似度阈值，低于此值的结果会被过滤。
        :return: 返回包含文档ID、文档内容、来源和相似度的列表。
        """
        if not self.vectors or not self.document:
            logger.warning("向量库为空，无法检索")
            return []

        query_vector = EmbeddingModel.get_embedding(query)
        if not query_vector:
            logger.warning("查询向量为空，无法检索")
            return []

        similarities = [self.get_similarity(query_vector, vector) for vector in self.vectors]

        # 获取相似度最高的 k 个文档索引
        top_k_indices = np.argsort(similarities)[-k:][::-1]

        result = []
        for idx in top_k_indices:
            sim = similarities[idx]
            if sim < min_similarity:
                continue
            source = self.sources[idx] if idx < len(self.sources) else ""
            result.append({
                "doc_id": self.doc_ids[idx],
                "document": self.document[idx],
                "source": source,
                "similarity": round(sim, 4),
            })

        logger.info(f"检索完成，返回 {len(result)} 条结果 (top-{k}, 阈值 {min_similarity})")
        return result

    def print_info(self):
        """输出存储信息的调试方法。"""
        print("===== 存储的信息 =====")
        for i in range(min(len(self.doc_ids), len(self.document))):
            print(f"文档 {i+1}:")
            print(f"  文档ID: {self.doc_ids[i]}")
            print(f"  文档内容: {self.document[i][:100]}...")
            if i < len(self.sources) and self.sources[i]:
                print(f"  来源: {self.sources[i]}")
            print("=======================")
