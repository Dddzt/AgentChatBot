from typing import List, Dict, AsyncIterator
import logging
import time

import httpx
from openai import AsyncOpenAI
from server.client.base_client import BaseModelClient
from config.config import MOONSHOT_DATA

logger = logging.getLogger(__name__)


class MoonshotClient(BaseModelClient):
    """通过 OpenAI 兼容接口调用 Moonshot (Kimi) 模型"""

    # kimi-k2.5 等模型仅允许 temperature=1，不传该参数让 API 使用默认值
    SKIP_TEMPERATURE_MODELS = {"kimi-k2.5", "kimi-k2.5-thinking"}

    def __init__(self, model: str = None, temperature: float = None):
        self.model = model or MOONSHOT_DATA.get("model", "moonshot-v1-8k")
        self.temperature = temperature
        self._skip_temp = self.model in self.SKIP_TEMPERATURE_MODELS
        self._client = AsyncOpenAI(
            api_key=MOONSHOT_DATA.get("key"),
            base_url=MOONSHOT_DATA.get("url"),
            http_client=httpx.AsyncClient(
                proxy=None,
                verify=True,
                timeout=httpx.Timeout(120, connect=15.0),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            ),
        )

    def _create_kwargs(self, messages, stream=False):
        kwargs = {"model": self.model, "messages": messages}
        if not self._skip_temp and self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if stream:
            kwargs["stream"] = True
        return kwargs

    async def ainvoke(self, messages: List[Dict[str, str]]) -> str:
        resp = await self._client.chat.completions.create(**self._create_kwargs(messages))
        return resp.choices[0].message.content

    async def astream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(**self._create_kwargs(messages, stream=True))

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
            if buffer_len >= 24 or now - last_flush_time >= 0.12:
                yield "".join(buffer)
                buffer.clear()
                buffer_len = 0
                last_flush_time = now

        if buffer:
            yield "".join(buffer)
