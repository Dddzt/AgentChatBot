"""Supervisor 调度节点 —— 分析任务并决定路由到哪个 Worker。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, AIMessage

from server.bot.multi_agent.prompts import SUPERVISOR_PROMPT, FINAL_ANSWER_PROMPT
from server.bot.multi_agent.state import AgentState, build_llm

logger = logging.getLogger(__name__)

VALID_WORKERS = {"researcher", "coder", "analyst", "writer"}
MAX_ITERATIONS = 5


def _format_task_results(results: list[dict]) -> str:
    if not results:
        return "（暂无）"
    parts = []
    for r in results:
        parts.append(f"[{r.get('agent', '?')}] {r.get('summary', '')}")
    return "\n".join(parts)


def _extract_json(text: str) -> dict | None:
    """从 LLM 输出中提取 JSON 对象。"""
    # 尝试直接解析
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # 尝试从 ```json ... ``` 中提取
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 尝试从文本中提取第一个 { ... }
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def create_supervisor_node(llm_config: dict):
    """创建 Supervisor 节点函数（闭包，捕获 llm_config）。"""

    llm = build_llm(llm_config, streaming=True)

    async def supervisor_node(state: AgentState) -> dict[str, Any]:
        iteration = state.get("iteration", 0)

        # 防止无限循环
        if iteration >= MAX_ITERATIONS:
            logger.warning("达到最大调度轮次 %d，强制结束", MAX_ITERATIONS)
            return {"next_agent": "FINISH", "instruction": "", "iteration": iteration}

        # 构建 Supervisor prompt
        task_results_text = _format_task_results(state.get("task_results", []))
        system_prompt = SUPERVISOR_PROMPT.format(task_results=task_results_text)

        # 提取用户原始消息
        messages = [{"role": "system", "content": system_prompt}]
        for msg in state.get("messages", []):
            if isinstance(msg, HumanMessage):
                messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                messages.append({"role": "assistant", "content": msg.content})

        try:
            response = await llm.ainvoke(messages)
            content = response.content if hasattr(response, "content") else str(response)
            decision = _extract_json(content)

            if decision and decision.get("next") in (VALID_WORKERS | {"FINISH"}):
                next_agent = decision["next"]
                instruction = decision.get("instruction", "")
                logger.info("Supervisor 调度: 第%d轮 → %s | 指令: %s", iteration + 1, next_agent, instruction[:100])
                return {
                    "next_agent": next_agent,
                    "instruction": instruction,
                    "iteration": iteration + 1,
                }

            # JSON 解析成功但 next 无效
            logger.warning("Supervisor 输出无效决策: %s，降级到 analyst", content[:200])
        except Exception as e:
            logger.error("Supervisor 调用失败: %s", e)

        # 降级：默认走 analyst
        return {
            "next_agent": "analyst",
            "instruction": "请直接回答用户的问题。",
            "iteration": iteration + 1,
        }

    return supervisor_node


def create_final_answer_node(llm_config: dict):
    """创建最终回答生成节点（当 Supervisor 决定 FINISH 时触发）。"""

    llm = build_llm(llm_config, streaming=True)

    async def final_answer_node(state: AgentState) -> dict[str, Any]:
        task_results = state.get("task_results", [])
        supervisor_instruction = state.get("instruction", "")

        # 取最后一条 HumanMessage 作为当前问题
        user_question = ""
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, HumanMessage):
                user_question = msg.content
                break

        # 构建专家成果文本（含 Supervisor 的 FINISH 指令，避免信息丢失）
        results_text = _format_task_results(task_results)
        if supervisor_instruction:
            results_text += f"\n\n[调度总结] {supervisor_instruction}"

        prompt = FINAL_ANSWER_PROMPT.format(question=user_question, results=results_text)

        # 构建消息列表：包含对话历史，让 LLM 能看到完整上下文
        messages: list[dict[str, str]] = [{"role": "system", "content": prompt}]
        for msg in state.get("messages", []):
            if isinstance(msg, HumanMessage):
                messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                messages.append({"role": "assistant", "content": msg.content})

        try:
            response = await llm.ainvoke(messages)
            content = response.content if hasattr(response, "content") else str(response)
            return {"messages": [AIMessage(content=content)]}
        except Exception as e:
            logger.error("最终回答生成失败: %s", e)
            fallback = "\n\n".join(r.get("summary", "") for r in task_results)
            return {"messages": [AIMessage(content=fallback)]}

    return final_answer_node
