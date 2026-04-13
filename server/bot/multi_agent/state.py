"""多智能体共享状态定义与工具函数"""

from __future__ import annotations

import logging
from typing import Annotated, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph.message import add_messages

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """Supervisor-Worker 多智能体共享状态。

    Attributes:
        messages: 完整对话消息列表（由 add_messages reducer 自动合并）。
        next_agent: Supervisor 路由决策——下一个要执行的 Worker 名称或 "FINISH"。
        instruction: Supervisor 给 Worker 的具体指令。
        task_results: 各 Worker 子任务执行结果累积。
        iteration: 当前 Supervisor 调度轮次（用于防止无限循环）。
    """

    messages: Annotated[list, add_messages]
    next_agent: str
    instruction: str
    task_results: list[dict]
    iteration: int


def build_llm(config: dict, streaming: bool = False) -> ChatOpenAI:
    """根据配置字典构建 ChatOpenAI 实例。支持 model_kwargs 透传（如 kimi-k2.5 的 thinking 禁用）。"""
    kwargs = {
        "model": config["model"],
        "api_key": config["key"],
        "base_url": config["url"],
        "temperature": config.get("temperature", 0.7),
        "streaming": streaming,
    }
    # 处理额外参数（如 kimi-k2.5 禁用 thinking 模式）
    model_kwargs = config.get("model_kwargs", {})
    if "extra_body" in model_kwargs:
        kwargs["extra_body"] = model_kwargs["extra_body"]
    elif model_kwargs:
        kwargs["model_kwargs"] = model_kwargs
    return ChatOpenAI(**kwargs)


def format_task_context(task_results: list[dict], max_chars: int = 0) -> str:
    """将已完成的子任务结果格式化为上下文文本，供 Worker 节点使用。

    Args:
        task_results: 子任务结果列表。
        max_chars: 最大字符数限制。0 表示不限制。超出时对每条结果等比截断。
    """
    if not task_results:
        return "（暂无前置信息）"
    parts = []
    for r in task_results:
        parts.append(f"[{r.get('agent', '?')}]\n{r.get('summary', '')}")
    text = "\n\n".join(parts)
    if max_chars and len(text) > max_chars:
        # 等比截断每条结果
        per = max(200, max_chars // len(task_results))
        truncated = []
        for r in task_results:
            summary = r.get("summary", "")
            if len(summary) > per:
                summary = summary[:per] + "…（已截断）"
            truncated.append(f"[{r.get('agent', '?')}]\n{summary}")
        text = "\n\n".join(truncated)
    return text
