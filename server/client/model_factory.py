from server.client.base_client import BaseModelClient
from config.config import QWEN_DATA, OLLAMA_DATA, MOONSHOT_DATA


def create_model_client(mode: str = "chat", provider: str | None = None) -> BaseModelClient:
    """
    根据模式和 config 优先级创建模型客户端。
    - 如果指定了 provider，则强制使用该模型
    - chat 模式：优先使用本地 Ollama，兜底使用 Qwen API
    - 其余模式（agent/rag/feishu 等）：优先使用 Qwen API，兜底使用 Ollama
    """

    # 用户明确指定了模型提供方
    if provider:
        return _create_by_provider(provider)

    if mode == "chat":
        # 聊天模式：Ollama 优先
        if OLLAMA_DATA.get("use"):
            from server.client.async_ollama_client import AsyncOllamaClient
            return AsyncOllamaClient()

        if QWEN_DATA.get("use"):
            from server.client.qwen_client import QwenClient
            return QwenClient()
    else:
        # agent / rag / feishu 等模式：Qwen 优先
        if QWEN_DATA.get("use"):
            from server.client.qwen_client import QwenClient
            return QwenClient()

        if OLLAMA_DATA.get("use"):
            from server.client.async_ollama_client import AsyncOllamaClient
            return AsyncOllamaClient()

    raise RuntimeError(
        "未配置任何可用模型，请在 config/config.py 中启用 QWEN_DATA 或 OLLAMA_DATA"
    )


def _create_by_provider(provider: str) -> BaseModelClient:
    """根据指定的 provider 创建模型客户端。"""
    if provider == "qwen" and QWEN_DATA.get("use"):
        from server.client.qwen_client import QwenClient
        return QwenClient()

    if provider == "ollama" and OLLAMA_DATA.get("use"):
        from server.client.async_ollama_client import AsyncOllamaClient
        return AsyncOllamaClient()

    if provider == "moonshot" and MOONSHOT_DATA.get("use"):
        from server.client.moonshot_client import MoonshotClient
        return MoonshotClient()

    raise RuntimeError(f"模型 '{provider}' 未启用或不可用，请检查 config/config.py")
