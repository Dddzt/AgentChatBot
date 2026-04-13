"""
统一对话记忆管理模块。

所有对话模式（聊天 / 智能体 / 知识库 / 多智能体）共用此模块管理多轮对话历史，
采用滑动窗口策略，保留最近 N 轮完整对话（user + assistant）。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import redis
from config.config import REDIS_DATA
from config.templates.data.bot import MAX_CONVERSATION_TURNS

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

# 全局 Redis 连接（复用单一连接池）
_redis_pool = redis.ConnectionPool(
    host=REDIS_DATA.get("host", "localhost"),
    port=REDIS_DATA.get("port", 6379),
    db=REDIS_DATA.get("db", 0),
)

_KEY_PREFIX = "conversation:"
_TTL_SECONDS = 7 * 24 * 3600  # 7 天过期


def _get_redis() -> redis.StrictRedis | None:
    try:
        client = redis.StrictRedis(connection_pool=_redis_pool)
        client.ping()
        return client
    except redis.RedisError as e:
        logger.warning("Redis 连接失败，记忆功能不可用: %s", e)
        return None


class ConversationMemory:
    """统一对话记忆管理。

    消息格式统一为::

        [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]

    Parameters
    ----------
    session_id : str
        会话唯一标识（Web 端为 session_id，CLI 端可使用 user_id）。
    max_turns : int
        保留的最大对话轮数（1 轮 = 1 user + 1 assistant）。
    """

    def __init__(self, session_id: str, max_turns: int = MAX_CONVERSATION_TURNS):
        self.session_id = session_id
        self.max_turns = max_turns
        self.messages: list[dict[str, str]] = []

    # ------------------------------------------------------------------
    # 加载 / 保存
    # ------------------------------------------------------------------

    def load(self) -> None:
        """从 Redis 加载历史消息。"""
        client = _get_redis()
        if client is None:
            return
        try:
            raw = client.get(f"{_KEY_PREFIX}{self.session_id}")
            if raw:
                data = json.loads(raw)
                # 兼容新旧格式
                if isinstance(data, list):
                    self.messages = self._normalize(data)
                elif isinstance(data, dict) and "messages" in data:
                    self.messages = self._normalize(data["messages"])
        except (json.JSONDecodeError, redis.RedisError) as e:
            logger.error("加载对话历史失败 [%s]: %s", self.session_id, e)

    def save(self) -> None:
        """将当前消息列表保存到 Redis。"""
        client = _get_redis()
        if client is None:
            return
        try:
            client.setex(
                f"{_KEY_PREFIX}{self.session_id}",
                _TTL_SECONDS,
                json.dumps(self.messages, ensure_ascii=False),
            )
        except redis.RedisError as e:
            logger.error("保存对话历史失败 [%s]: %s", self.session_id, e)

    # ------------------------------------------------------------------
    # 添加消息
    # ------------------------------------------------------------------

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})
        self._truncate()

    def add_assistant_message(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})
        self._truncate()

    # ------------------------------------------------------------------
    # 从外部消息列表初始化（Web 端前端传入完整 messages 时使用）
    # ------------------------------------------------------------------

    @classmethod
    def from_messages(cls, messages: list[dict[str, str]], session_id: str = "", max_turns: int = MAX_CONVERSATION_TURNS) -> ConversationMemory:
        """从已有消息列表创建记忆实例（不读 Redis）。"""
        mem = cls(session_id=session_id, max_turns=max_turns)
        mem.messages = cls._normalize(messages)
        mem._truncate()
        return mem

    # ------------------------------------------------------------------
    # 输出格式
    # ------------------------------------------------------------------

    def to_messages(self) -> list[dict[str, str]]:
        """返回标准 messages 列表，可直接传给 LLM。"""
        return list(self.messages)

    def to_text(self, max_turns: int | None = None) -> str:
        """返回纯文本格式的对话历史（供 RAG prompt 嵌入）。"""
        msgs = self.messages
        limit = max_turns or self.max_turns
        if len(msgs) > limit * 2:
            msgs = msgs[-(limit * 2):]

        parts: list[str] = []
        for m in msgs:
            role_name = "用户" if m["role"] == "user" else "助手"
            parts.append(f"{role_name}: {m['content']}")
        return "\n\n".join(parts) if parts else ""

    def to_langchain_messages(self) -> list[BaseMessage]:
        """返回 LangChain HumanMessage / AIMessage 列表。"""
        from langchain_core.messages import AIMessage, HumanMessage

        result: list[BaseMessage] = []
        for m in self.messages:
            if m["role"] == "user":
                result.append(HumanMessage(content=m["content"]))
            elif m["role"] == "assistant":
                result.append(AIMessage(content=m["content"]))
        return result

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _truncate(self) -> None:
        """滑动窗口截断，保留最近 max_turns 轮。"""
        max_messages = self.max_turns * 2
        if len(self.messages) > max_messages:
            self.messages = self.messages[-max_messages:]

    @staticmethod
    def _normalize(messages: list) -> list[dict[str, str]]:
        """将各种格式的历史统一为标准 role/content 格式。

        兼容旧格式：[{"Human": "..."}, {"AI": "..."}]
        """
        result: list[dict[str, str]] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            # 标准格式
            if "role" in item and "content" in item:
                if item["role"] in ("user", "assistant"):
                    result.append({"role": item["role"], "content": item["content"]})
            # 旧格式兼容
            elif "Human" in item:
                result.append({"role": "user", "content": item["Human"]})
                if "AI" in item:
                    result.append({"role": "assistant", "content": item["AI"]})
        return result
