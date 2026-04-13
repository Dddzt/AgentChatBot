"""Writer Worker —— 写作专家，纯 LLM 生成，无外部工具。"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage

from server.bot.multi_agent.prompts import WRITER_PROMPT
from server.bot.multi_agent.state import AgentState, build_llm, format_task_context

logger = logging.getLogger(__name__)


def create_writer_node(llm_config: dict):
    """创建写作专家节点。"""

    llm = build_llm(llm_config, streaming=True)
    # 本地小模型上下文窗口有限，限制输入长度
    _is_local = "awq" in llm_config.get("model", "").lower() or llm_config.get("key") == "EMPTY"
    _ctx_limit = 2500 if _is_local else 0

    async def writer_node(state: AgentState) -> dict[str, Any]:
        instruction = state.get("instruction", "请撰写内容")
        context = format_task_context(state.get("task_results", []), max_chars=_ctx_limit)
        prompt = WRITER_PROMPT.format(instruction=instruction, context=context)

        try:
            response = await llm.ainvoke([{"role": "user", "content": prompt}])
            response_text = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.error("Writer 执行失败: %s", e)
            response_text = f"写作过程中出错: {e}"

        task_results = list(state.get("task_results", []))
        task_results.append({
            "agent": "写作专家",
            "agent_key": "writer",
            "summary": response_text,
        })

        return {
            "task_results": task_results,
            "messages": [AIMessage(content=f"[写作专家完成]\n{response_text}")],
        }

    return writer_node
