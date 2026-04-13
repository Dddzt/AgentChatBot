"""MultiAgentBot —— 对外统一接口，封装 Supervisor-Worker 多智能体图。"""

from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage

from config.config import QWEN_DATA, OLLAMA_DATA, MOONSHOT_DATA
from server.bot.multi_agent.graph import AGENT_DISPLAY_NAMES, WORKER_NAMES, build_graph

logger = logging.getLogger(__name__)


def _make_llm_config(provider: str = "qwen") -> dict:
    """根据 provider 构造 LLM 配置字典。"""
    if provider == "moonshot" and MOONSHOT_DATA.get("use"):
        model_name = MOONSHOT_DATA.get("model", "kimi-k2.5")
        cfg = {
            "model": model_name,
            "key": MOONSHOT_DATA.get("key"),
            "url": MOONSHOT_DATA.get("url"),
            "temperature": 0.6,
        }
        # kimi-k2.5 的 thinking 模式与工具调用不兼容，需要禁用
        if model_name in ("kimi-k2.5", "kimi-k2.5-thinking"):
            cfg["model_kwargs"] = {"extra_body": {"thinking": {"type": "disabled"}}}
        return cfg
    if provider == "ollama" and OLLAMA_DATA.get("use"):
        return {
            "model": OLLAMA_DATA["model"],
            "key": OLLAMA_DATA.get("key", "EMPTY"),
            "url": OLLAMA_DATA.get("api_url", "http://localhost:11434/v1/"),
            "temperature": 0.7,
        }
    # 默认 / qwen
    return {
        "model": QWEN_DATA["model"],
        "key": QWEN_DATA["key"],
        "url": QWEN_DATA["url"],
        "temperature": QWEN_DATA.get("temperature", 0.7),
    }


class MultiAgentBot:
    """Supervisor-Worker 多智能体机器人（多模型协作）。

    模型分配策略：
    - Supervisor / Researcher / FinalAnswer → qwen-plus（稳定、支持工具调用）
    - Coder / Analyst → kimi-k2.5（代码和推理能力最强）
    - Writer → 本地模型 qwen2.5-32b-awq（速度快、免费）

    Usage::

        bot = MultiAgentBot()
        async for event in bot.astream("帮我搜索并分析最新的AI框架"):
            print(event)
    """

    def __init__(self, provider: str | None = None):
        # 三种模型配置（检测可用性）
        qwen_config = _make_llm_config("qwen")
        moonshot_config = _make_llm_config("moonshot") if MOONSHOT_DATA.get("use") else qwen_config
        # 本地模型：仅在配置启用时尝试，不可用时自动降级
        if OLLAMA_DATA.get("use"):
            ollama_config = _make_llm_config("ollama")
            try:
                import httpx
                resp = httpx.get(OLLAMA_DATA.get("api_url", "") + "models", timeout=3)
                if resp.status_code != 200:
                    raise ConnectionError(f"status {resp.status_code}")
            except Exception as e:
                logger.warning("本地模型不可用 (%s)，Writer 降级到 Qwen", e)
                ollama_config = qwen_config
        else:
            ollama_config = qwen_config

        # 多智能体模式始终走差异化分配，忽略前端的单一 provider 选择
        # （前端的模型选择器仅对 chat/agent 等单模型模式有效）

        # 按节点角色差异化分配模型
        supervisor_config = qwen_config
        tool_worker_config = qwen_config           # Researcher：需要工具调用
        code_worker_config = moonshot_config        # Coder：kimi 代码能力最强
        reasoning_worker_config = moonshot_config   # Analyst：kimi 推理能力最强
        writing_worker_config = ollama_config       # Writer：本地模型速度快
        final_answer_config = qwen_config

        # 保存节点→模型名称映射，用于前端展示
        self.node_models = {
            "supervisor": supervisor_config["model"],
            "researcher": tool_worker_config["model"],
            "coder": code_worker_config["model"],
            "analyst": reasoning_worker_config["model"],
            "writer": writing_worker_config["model"],
            "final_answer": final_answer_config["model"],
        }

        self.graph = build_graph(
            supervisor_config=supervisor_config,
            tool_worker_config=tool_worker_config,
            code_worker_config=code_worker_config,
            reasoning_worker_config=reasoning_worker_config,
            writing_worker_config=writing_worker_config,
            final_answer_config=final_answer_config,
        )

        logger.info(
            "MultiAgentBot 初始化完成 | Supervisor=%s | Researcher=%s | Coder=%s | Analyst=%s | Writer=%s",
            supervisor_config["model"], tool_worker_config["model"],
            code_worker_config["model"], reasoning_worker_config["model"],
            writing_worker_config["model"],
        )

    async def astream(
        self,
        query: str,
        history: list[dict] | None = None,
    ) -> AsyncIterator[dict]:
        """流式执行多智能体协作，产出 SSE 兼容事件。

        事件格式：
            {"type": "status",              "content": "..."}
            {"type": "agent_active",        "content": "搜索专家", "model": "qwen-plus"}
            {"type": "supervisor_decision", "content": "{json}"}
            {"type": "tool_call",           "content": "search_tool"}
            {"type": "worker_result",       "content": "{json}"}
            {"type": "content",             "content": "..."}  (最终回答 token)
            {"type": "trace",               "content": [...]}  (执行追踪)
            {"type": "done",                "content": ""}
        """
        # 构建初始消息
        messages = []
        if history:
            for h in history:
                if h.get("role") == "user":
                    messages.append(HumanMessage(content=h["content"]))
                elif h.get("role") == "assistant":
                    messages.append(AIMessage(content=h["content"]))
        messages.append(HumanMessage(content=query))

        initial_state = {
            "messages": messages,
            "next_agent": "",
            "instruction": "",
            "task_results": [],
            "iteration": 0,
        }

        yield {"type": "status", "content": "多智能体协作启动，正在分析任务..."}

        trace = []
        start_time = time.time()

        try:
            async for event in self.graph.astream_events(
                initial_state, version="v2"
            ):
                event_name = event.get("event", "")
                event_data = event.get("data", {})
                node_name = event.get("name", "")
                tags = event.get("tags", [])

                # 节点开始 → 发送 agent_active 事件（附带模型名称）
                if event_name == "on_chain_start" and node_name in AGENT_DISPLAY_NAMES:
                    display = AGENT_DISPLAY_NAMES[node_name]
                    model = self.node_models.get(node_name, "")
                    yield {"type": "agent_active", "content": display, "model": model}
                    trace.append({
                        "agent": display,
                        "node": node_name,
                        "model": model,
                        "start_time": time.time() - start_time,
                    })

                # 节点结束 → 记录追踪 + 发送决策/结果事件
                elif event_name == "on_chain_end" and node_name in AGENT_DISPLAY_NAMES:
                    if trace and trace[-1].get("node") == node_name:
                        trace[-1]["end_time"] = time.time() - start_time

                    output = event_data.get("output", {})
                    if isinstance(output, dict):
                        # Supervisor 决策事件
                        if node_name == "supervisor" and output.get("next_agent"):
                            yield {
                                "type": "supervisor_decision",
                                "content": json.dumps({
                                    "next": output.get("next_agent", ""),
                                    "instruction": output.get("instruction", ""),
                                    "iteration": output.get("iteration", 0),
                                }, ensure_ascii=False),
                            }

                        # Worker 完成事件
                        elif node_name in WORKER_NAMES:
                            results = output.get("task_results", [])
                            if results:
                                latest = results[-1]
                                yield {
                                    "type": "worker_result",
                                    "content": json.dumps({
                                        "agent": latest.get("agent", node_name),
                                        "summary": latest.get("summary", ""),
                                    }, ensure_ascii=False),
                                }

                # 工具调用
                elif event_name == "on_tool_start":
                    yield {"type": "tool_call", "content": node_name}

                elif event_name == "on_tool_end":
                    yield {"type": "status", "content": "工具执行完成，继续处理..."}

                # LLM 流式输出 → 分发到对应卡片或最终回答区
                elif event_name == "on_chat_model_stream":
                    chunk = event_data.get("chunk")
                    text = getattr(chunk, "content", None)
                    if not isinstance(text, str) or not text:
                        continue

                    metadata = event.get("metadata", {})
                    langgraph_node = metadata.get("langgraph_node", "")

                    if langgraph_node == "final_answer" or "final_answer" in tags:
                        yield {"type": "content", "content": text}
                    elif langgraph_node in WORKER_NAMES or langgraph_node == "supervisor":
                        yield {
                            "type": "worker_stream",
                            "node": langgraph_node,
                            "content": text,
                        }

        except Exception as e:
            logger.error("多智能体执行出错: %s", e)
            yield {"type": "content", "content": f"多智能体协作过程中出错: {e}"}

        # 发送执行追踪
        if trace:
            yield {"type": "trace", "content": trace}

        yield {"type": "done", "content": ""}

    async def run(self, query: str, history: list[dict] | None = None) -> str:
        """非流式执行，返回最终回答文本。"""
        final_text = []
        async for event in self.astream(query, history):
            if event.get("type") == "content":
                final_text.append(event["content"])
        return "".join(final_text)


def _is_final_answer_event(event: dict) -> bool:
    """判断事件是否属于 final_answer 节点的 LLM 输出。"""
    metadata = event.get("metadata", {})
    langgraph_node = metadata.get("langgraph_node", "")
    return langgraph_node == "final_answer"
