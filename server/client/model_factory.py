from server.client.base_client import BaseModelClient
from config.config import CHATGPT_DATA, OLLAMA_DATA


def create_model_client() -> BaseModelClient:
    """
    根据 config 优先级创建模型客户端。
    优先使用阿里云 Qwen API，兜底使用本地 Ollama。
    """

    if OLLAMA_DATA.get("use"):
        from server.client.async_ollama_client import AsyncOllamaClient
        return AsyncOllamaClient()
    
    if CHATGPT_DATA.get("use"):
        from server.client.qwen_client import QwenClient
        return QwenClient()

    

    raise RuntimeError(
        "未配置任何可用模型，请在 config/config.py 中启用 CHATGPT_DATA 或 OLLAMA_DATA"
    )
