"""Analyst Worker —— 分析专家，纯 LLM 推理，无外部工具。"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage

from server.bot.multi_agent.prompts import ANALYST_PROMPT
from server.bot.multi_agent.state import AgentState, build_llm, format_task_context

logger = logging.getLogger(__name__)


def create_analyst_node(llm_config: dict):
    """创建分析专家节点。"""

    llm = build_llm(llm_config, streaming=True)

    async def analyst_node(state: AgentState) -> dict[str, Any]:
        instruction = state.get("instruction", "请进行分析")
        context = format_task_context(state.get("task_results", []))
        prompt = ANALYST_PROMPT.format(instruction=instruction, context=context)

        try:
            response = await llm.ainvoke([{"role": "user", "content": prompt}])
            response_text = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.error("Analyst 执行失败: %s", e)
            response_text = f"分析过程中出错: {e}"

        task_results = list(state.get("task_results", []))
        task_results.append({
            "agent": "分析专家",
            "agent_key": "analyst",
            "summary": response_text,
        })

        return {
            "task_results": task_results,
            "messages": [AIMessage(content=f"[分析专家完成]\n{response_text}")],
        }

    return analyst_node
