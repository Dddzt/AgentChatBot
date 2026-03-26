"""
RAG Bot：基于知识库检索的流式问答 Bot，用于 Web 端知识库模式。
支持对话历史、文档来源追踪、相似度过滤。
"""

import logging
from typing import AsyncIterator

from config.config import RAG_CONFIG
from config.templates.data.bot import RAG_PROMPT_TEMPLATE
from server.client.model_factory import create_model_client
from server.rag.knowledge_base_manager import KnowledgeBaseManager
from server.rag.v1.embedding.embedding_model import EmbeddingModel
from server.rag.v1.vectorstore.vectorstore import VectorStore

logger = logging.getLogger(__name__)

# 最低相似度阈值，低于此值的结果不展示
MIN_SIMILARITY = 0.15


class RAGBot:
    def __init__(self, knowledge_base_id: str):
        self.kb_id = knowledge_base_id
        self.kb_manager = KnowledgeBaseManager()
        self.embedding = EmbeddingModel()

    def retrieve(self, question: str, k: int = None) -> list[dict]:
        """
        加载已持久化的向量，检索 top-k 最相关文档片段。
        返回 list[dict]，每项包含 document, source, similarity。
        """
        if k is None:
            k = RAG_CONFIG.get("default_k", 3)

        storage_path = self.kb_manager._storage_path(self.kb_id)
        if not storage_path.exists():
            raise FileNotFoundError(f"知识库索引目录不存在: {storage_path}")

        vector = VectorStore()
        vector.load_vector(path=str(storage_path))

        results = vector.query(
            question,
            EmbeddingModel=self.embedding,
            k=k,
            min_similarity=MIN_SIMILARITY,
        )
        return results

    async def astream(self, question: str, history: str = "", provider: str | None = None) -> AsyncIterator[dict]:
        """检索上下文 → 流式生成回答，yield SSE 事件 dict。"""
        self._provider = provider

        # 检查知识库是否已索引
        if not self.kb_manager.is_indexed(self.kb_id):
            yield {"type": "status", "content": "知识库尚未构建索引，请先在管理面板中构建索引。"}
            return

        # 检索阶段
        yield {"type": "status", "content": "正在检索相关文档..."}

        try:
            k = RAG_CONFIG.get("default_k", 3)
            results = self.retrieve(question, k=k)
        except FileNotFoundError as e:
            logger.error(f"RAG 检索失败 - 索引文件缺失: {e}")
            yield {"type": "status", "content": "索引文件缺失，请重新构建索引。"}
            return
        except Exception as e:
            logger.error(f"RAG 检索失败: {e}", exc_info=True)
            yield {"type": "status", "content": f"检索失败: {e}"}
            return

        if not results:
            yield {"type": "status", "content": "未找到与问题相关的文档内容（相似度过低），请尝试换个问法或补充更多文档。"}
            return

        # 构建来源信息
        source_set = set()
        for r in results:
            if r.get("source"):
                source_set.add(r["source"])
        source_info = "、".join(source_set) if source_set else "未知来源"

        yield {
            "type": "status",
            "content": f"已找到 {len(results)} 条相关内容（来源: {source_info}），正在生成回答...",
        }

        # 组装上下文（带来源标注）
        context_parts = []
        for i, r in enumerate(results, 1):
            source_label = f"[来源: {r['source']}]" if r.get("source") else ""
            sim_label = f"(相似度: {r['similarity']})" if r.get("similarity") else ""
            context_parts.append(f"片段{i} {source_label} {sim_label}\n{r['document']}")
        context = "\n\n---\n\n".join(context_parts)

        # 组装 RAG Prompt（包含对话历史）
        prompt_template = RAG_PROMPT_TEMPLATE.get("prompt_template", "")
        if not prompt_template:
            logger.error("RAG prompt 模板为空")
            yield {"type": "content", "content": "系统配置错误：RAG prompt 模板缺失。"}
            return

        history_text = history if history else "无历史记录"
        rag_prompt = prompt_template.format(
            question=question,
            history=history_text,
            context=context,
        )

        messages = [{"role": "user", "content": rag_prompt}]

        # 流式生成回答
        try:
            client = create_model_client(mode="rag", provider=self._provider)
            has_content = False
            async for chunk in client.astream(messages):
                if chunk:
                    has_content = True
                    yield {"type": "content", "content": chunk}

            # 回答结束后追加来源引用
            if has_content and source_set:
                source_footer = "\n\n---\n*参考文档: " + "、".join(f"**{s}**" for s in source_set) + "*"
                yield {"type": "content", "content": source_footer}

        except Exception as e:
            logger.error(f"RAG 生成回答失败: {e}", exc_info=True)
            # fallback 到非流式
            try:
                client = create_model_client(mode="rag", provider=self._provider)
                full_response = await client.ainvoke(messages)
                if full_response:
                    yield {"type": "content", "content": full_response}
                    if source_set:
                        source_footer = "\n\n---\n*参考文档: " + "、".join(f"**{s}**" for s in source_set) + "*"
                        yield {"type": "content", "content": source_footer}
            except Exception as e2:
                logger.error(f"RAG fallback 也失败: {e2}", exc_info=True)
                yield {"type": "content", "content": f"生成回答时出错: {e2}"}
