"""构建 Supervisor-Worker 多智能体 StateGraph。"""

from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from server.bot.multi_agent.state import AgentState
from server.bot.multi_agent.nodes.supervisor import (
    create_final_answer_node,
    create_supervisor_node,
)
from server.bot.multi_agent.nodes.analyst import create_analyst_node
from server.bot.multi_agent.nodes.coder import create_coder_node
from server.bot.multi_agent.nodes.researcher import create_researcher_node
from server.bot.multi_agent.nodes.writer import create_writer_node

logger = logging.getLogger(__name__)

WORKER_NAMES = ["researcher", "coder", "analyst", "writer"]

AGENT_DISPLAY_NAMES = {
    "supervisor": "调度中心",
    "researcher": "搜索专家",
    "coder": "代码专家",
    "analyst": "分析专家",
    "writer": "写作专家",
    "final_answer": "生成最终回答",
}


def _route_decision(state: AgentState) -> str:
    """根据 Supervisor 的决策路由到对应 Worker 或结束。"""
    next_agent = state.get("next_agent", "FINISH")
    if next_agent in WORKER_NAMES:
        return next_agent
    return "final_answer"


def build_graph(
    supervisor_config: dict,
    tool_worker_config: dict,
    code_worker_config: dict,
    reasoning_worker_config: dict,
    writing_worker_config: dict,
    final_answer_config: dict,
) -> StateGraph:
    """构建并编译多智能体图（每个节点可使用不同模型）。

    Args:
        supervisor_config: Supervisor 使用的 LLM 配置。
        tool_worker_config: Researcher（需要工具调用）使用的 LLM 配置。
        code_worker_config: Coder（代码专家，需要工具调用）使用的 LLM 配置。
        reasoning_worker_config: Analyst（分析专家，纯推理）使用的 LLM 配置。
        writing_worker_config: Writer（写作专家，纯生成）使用的 LLM 配置。
        final_answer_config: FinalAnswer 使用的 LLM 配置。
    """
    graph = StateGraph(AgentState)

    # 添加节点（每个节点独立配模型）
    graph.add_node("supervisor", create_supervisor_node(supervisor_config))
    graph.add_node("researcher", create_researcher_node(tool_worker_config))
    graph.add_node("coder", create_coder_node(code_worker_config))
    graph.add_node("analyst", create_analyst_node(reasoning_worker_config))
    graph.add_node("writer", create_writer_node(writing_worker_config))
    graph.add_node("final_answer", create_final_answer_node(final_answer_config))

    # 入口：所有请求先经过 Supervisor
    graph.set_entry_point("supervisor")

    # Supervisor 条件路由
    graph.add_conditional_edges(
        "supervisor",
        _route_decision,
        {
            "researcher": "researcher",
            "coder": "coder",
            "analyst": "analyst",
            "writer": "writer",
            "final_answer": "final_answer",
        },
    )

    # 所有 Worker 完成后回到 Supervisor（循环边）
    for worker in WORKER_NAMES:
        graph.add_edge(worker, "supervisor")

    # final_answer → 结束
    graph.add_edge("final_answer", END)

    return graph.compile()
