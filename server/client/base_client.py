from abc import ABC, abstractmethod
from typing import List, Dict, AsyncIterator
import logging

logger = logging.getLogger(__name__)


class BaseModelClient(ABC):
    """
    统一的模型客户端抽象基类。
    所有模型调用（Ollama / 云端API）必须继承此类，
    强制走 async/await 异步契约，避免长文本生成时阻塞事件循环。
    """

    @abstractmethod
    async def ainvoke(self, messages: List[Dict[str, str]]) -> str:
        """异步调用模型，返回完整的文本响应"""
        ...

    @abstractmethod
    async def astream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        """异步流式调用模型，逐 token 返回"""
        ...

    def invoke(self, messages: List[Dict[str, str]]) -> str:
        """同步兼容接口，内部委托给 ainvoke"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self.ainvoke(messages)).result()
        return asyncio.run(self.ainvoke(messages))
