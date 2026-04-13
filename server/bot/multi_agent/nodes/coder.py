"""Coder Worker —— 代码专家，擅长编写和调试代码。"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from server.bot.multi_agent.prompts import CODER_PROMPT
from server.bot.multi_agent.state import AgentState, build_llm
from tools.agent_tool.search_tool.tool import search_tool

logger = logging.getLogger(__name__)


def create_coder_node(llm_config: dict):
    """创建代码专家节点。直接在节点内调用 LLM + 工具，确保流式事件可被父图捕获。"""

    llm = build_llm(llm_config, streaming=True)
    llm_with_tools = llm.bind_tools([search_tool])

    async def coder_node(state: AgentState) -> dict[str, Any]:
        instruction = state.get("instruction", "请编写代码")
        prompt = CODER_PROMPT.format(instruction=instruction)
        msgs = [HumanMessage(content=prompt)]

        try:
            # 第一轮：LLM 决定是否需要搜索技术文档（流式可见）
            response = await llm_with_tools.ainvoke(msgs)

            # 如果 LLM 请求调用搜索工具
            if response.tool_calls:
                msgs.append(response)
                for tc in response.tool_calls:
                    try:
                        tool_result = await search_tool.ainvoke(tc["args"])
                    except Exception as te:
                        logger.warning("代码专家搜索工具执行失败: %s", te)
                        tool_result = f"搜索失败: {te}"
                    msgs.append(ToolMessage(content=str(tool_result), tool_call_id=tc["id"]))

                # 第二轮：LLM 根据搜索结果生成代码（流式可见）
                final = await llm_with_tools.ainvoke(msgs)
                response_text = final.content if hasattr(final, "content") else str(final)
            else:
                response_text = response.content if hasattr(response, "content") else str(response)

            if not response_text:
                response_text = "代码生成未返回有效结果。"

        except Exception as e:
            logger.warning("Coder 执行失败，降级为纯 LLM 回答: %s", e)
            try:
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                response_text = response.content
            except Exception as fallback_err:
                logger.error("Coder 降级也失败: %s", fallback_err)
                response_text = f"代码生成过程中出错: {e}"

        task_results = list(state.get("task_results", []))
        task_results.append({
            "agent": "代码专家",
            "agent_key": "coder",
            "summary": response_text,
        })

        return {
            "task_results": task_results,
            "messages": [AIMessage(content=f"[代码专家完成]\n{response_text}")],
        }

    return coder_node
