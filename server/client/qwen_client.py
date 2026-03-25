from typing import List, Dict, AsyncIterator
import logging
import time

import httpx
from openai import AsyncOpenAI
from server.client.base_client import BaseModelClient
from config.config import CHATGPT_DATA

logger = logging.getLogger(__name__)


class QwenClient(BaseModelClient):
    """通过 OpenAI 兼容接口调用阿里云百炼 / Qwen 系列模型"""

    def __init__(self, model: str = None, temperature: float = None):
        self.model = model or CHATGPT_DATA.get("model", "qwen-plus")
        self.temperature = temperature if temperature is not None else CHATGPT_DATA.get("temperature", 0.7)
        self.request_timeout = float(CHATGPT_DATA.get("timeout", 120))
        self.stream_flush_chars = max(1, int(CHATGPT_DATA.get("stream_flush_chars", 24)))
        self.stream_flush_interval = float(CHATGPT_DATA.get("stream_flush_interval", 0.12))
        self._client = AsyncOpenAI(
            api_key=CHATGPT_DATA.get("key"),
            base_url=CHATGPT_DATA.get("url"),
            http_client=httpx.AsyncClient(
                proxy=None,
                verify=True,
                timeout=httpx.Timeout(self.request_timeout, connect=min(15.0, self.request_timeout)),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            ),
        )

    async def ainvoke(self, messages: List[Dict[str, str]]) -> str:
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
        )
        return resp.choices[0].message.content

    async def astream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            stream=True,
        )

        buffer: list[str] = []
        buffer_len = 0
        last_flush_time = time.perf_counter()

        async for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            content = delta.content if delta else None
            if not content:
                continue

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
