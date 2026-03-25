from typing import List, Dict, AsyncIterator
import logging
import time

from openai import AsyncOpenAI
from server.client.base_client import BaseModelClient
from config.config import OLLAMA_DATA

logger = logging.getLogger(__name__)


class AsyncOllamaClient(BaseModelClient):
    """通过 OpenAI 兼容接口异步调用本地 Ollama 模型"""

    def __init__(self, model: str = None):
        self.model = model or OLLAMA_DATA.get("model", "qwen:1.8b")
        self.stream_flush_chars = max(1, int(OLLAMA_DATA.get("stream_flush_chars", 24)))
        self.stream_flush_interval = float(OLLAMA_DATA.get("stream_flush_interval", 0.12))
        self._client = AsyncOpenAI(
            api_key="ollama",
            base_url=OLLAMA_DATA.get("api_url", "http://localhost:11434/v1/"),
        )

    async def ainvoke(self, messages: List[Dict[str, str]]) -> str:
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        return resp.choices[0].message.content

    async def astream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
        )

        buffer: list[str] = []
        buffer_len = 0
        last_flush_time = time.perf_counter()

        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                content = delta.content
                buffer.append(content)
                buffer_len += len(content)

                now = time.perf_counter()
                should_flush = (
                    buffer_len >= self.stream_flush_chars
                    or now - last_flush_time >= self.stream_flush_interval
                )
                if should_flush:
                    yield "".join(buffer)
                    buffer.clear()
                    buffer_len = 0
                    last_flush_time = now

        if buffer:
            yield "".join(buffer)
