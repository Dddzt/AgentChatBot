import logging
from typing import List

from openai import OpenAI

from config.config import OLLAMA_DATA, QWEN_DATA
from server.client.loadmodel.Ollama.OllamaClient import OllamaClient

logger = logging.getLogger(__name__)

client = OllamaClient()
client_ollama = client.get_client()

gpt_client = OpenAI(
    api_key=QWEN_DATA.get("key"),
    base_url=QWEN_DATA.get("url")
)


class EmbeddingModel:
    """向量模型客户端，支持 GPT / Ollama 两种后端。"""

    def __init__(self) -> None:
        self.client = gpt_client if QWEN_DATA.get("use") else client_ollama

    def get_embedding(self, text: str) -> List[float]:
        """
        将文本转化为向量表示。
        :param text: 需要转化为向量的文本
        :return: 向量列表，失败时返回空列表
        """
        if not text or not text.strip():
            logger.warning("输入文本为空，返回空向量")
            return []

        # 去掉换行符，保证输入格式规范
        text = text.replace("\n", " ").strip()

        try:
            if QWEN_DATA.get("use"):
                model = QWEN_DATA.get("embedding_model")
                if not model:
                    logger.error("QWEN_DATA 中未配置 embedding_model")
                    return []
                result = self.client.embeddings.create(input=[text], model=model)
                embedding = result.data[0].embedding
                if not embedding:
                    logger.warning("GPT embedding 返回了空向量")
                    return []
                return embedding
            else:
                model = OLLAMA_DATA.get("embedding_model")
                if not model:
                    # fallback 到聊天模型
                    model = OLLAMA_DATA.get("model")
                if not model:
                    logger.error("Ollama 未配置 embedding_model 或 model")
                    return []
                result = self.client.embeddings.create(input=[text], model=model)
                embedding = result.data[0].embedding
                if not embedding:
                    logger.warning("Ollama embedding 返回了空向量")
                    return []
                return embedding
        except Exception as e:
            logger.error(f"生成向量失败: {e}")
            return []
