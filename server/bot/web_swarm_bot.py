"""
Web Swarm Bot：通用多智能体协作 Bot，用于 Web 端协作体模式。

智能体网络：
  分诊智能体 (Triage Agent)
    ├── 代码助手 (Code Agent)    — 代码生成、调试、解释
    ├── 搜索助手 (Search Agent)  — 联网搜索、信息整合
    └── 知识问答助手 (QA Agent)  — 通用问答、总结分析
"""

import json
import logging
from typing import Iterable

from swarm import Agent, Swarm

from config.config import OLLAMA_DATA, QWEN_DATA
from config.templates.data.bot import CODE_BOT_PROMPT_DATA, SEARCH_BOT_PROMPT_DATA
from tools.agent_tool.code_gen.tool import CodeGenAPIWrapper
from tools.agent_tool.search_tool.tool import SearchAPIWrapper

logger = logging.getLogger(__name__)

# ======================== 工具函数（Swarm 兼容签名） ========================

_code_generator = CodeGenAPIWrapper()
_search_engine = SearchAPIWrapper()


def swarm_code_gen(query: str) -> str:
    """代码生成工具：根据用户描述生成相应的代码实现。"""
    return _code_generator.generate_code(query)


def swarm_search(query: str) -> str:
    """联网搜索工具：搜索互联网获取最新信息。"""
    return _search_engine.generate_result(query)


# ======================== 获取模型名称 ========================

def _get_model_name() -> str:
    """根据配置获取当前使用的模型名称。"""
    if OLLAMA_DATA.get("use"):
        return OLLAMA_DATA.get("model", "qwen3:14b")
    if QWEN_DATA.get("use"):
        return QWEN_DATA.get("model", "qwen-plus")
    return "qwen3:14b"


# ======================== WebSwarmBot ========================

class WebSwarmBot:
    def __init__(self):
        self._init_client()
        self.triage_agent = self._build_agent_network()

    def _init_client(self):
        """初始化 Swarm 客户端。"""
        if OLLAMA_DATA.get("use"):
            from server.client.loadmodel.Ollama.OllamaClient import OllamaClient
            client = OllamaClient()
            self.swarm = Swarm(client.get_client())
        else:
            from openai import OpenAI
            openai_client = OpenAI(
                api_key=QWEN_DATA.get("key", ""),
                base_url=QWEN_DATA.get("url", ""),
            )
            self.swarm = Swarm(openai_client)

    def _build_agent_network(self) -> Agent:
        """构建 分诊 → 代码/搜索/问答 智能体网络。"""
        model = _get_model_name()

        # --- 子智能体 ---

        code_agent = Agent(
            name="代码助手",
            instructions=CODE_BOT_PROMPT_DATA.get("description", "") + """

你是代码助手，专门负责代码生成、调试和解释。
当用户的需求涉及编程、代码、算法、调试或技术实现时，由你来处理。
如果用户的后续问题不再与代码相关，调用 transfer_back_to_triage 将对话交回分诊智能体。
使用中文回答。""",
            functions=[swarm_code_gen],
            model=model,
        )

        search_agent = Agent(
            name="搜索助手",
            instructions=SEARCH_BOT_PROMPT_DATA.get("description", "").replace("{time}", "") + """

你是搜索助手，专门负责联网搜索和信息整合。
当用户需要查询最新信息、新闻、实时数据或需要验证事实时，由你来处理。
使用搜索工具获取信息，然后整理成清晰、有用的回答。
如果用户的后续问题不再需要搜索，调用 transfer_back_to_triage 将对话交回分诊智能体。
使用中文回答。""",
            functions=[swarm_search],
            model=model,
        )

        qa_agent = Agent(
            name="知识问答助手",
            instructions="""你是知识问答助手，专门负责通用知识问答、概念解释、内容总结和分析推理。
当用户的问题属于常识性知识、概念解释、文本总结、分析建议等不需要代码或搜索的场景时，由你来处理。
提供清晰、准确、有深度的回答。
如果用户的后续问题需要代码或搜索，调用 transfer_back_to_triage 将对话交回分诊智能体。
使用中文回答。""",
            functions=[],
            model=model,
        )

        # --- transfer 函数 ---

        def transfer_to_code():
            """将对话转移给代码助手，处理编程和代码相关的任务。"""
            return code_agent

        def transfer_to_search():
            """将对话转移给搜索助手，处理需要联网搜索的任务。"""
            return search_agent

        def transfer_to_qa():
            """将对话转移给知识问答助手，处理通用知识和分析任务。"""
            return qa_agent

        def transfer_back_to_triage():
            """将对话交回分诊智能体，重新分析用户意图并路由。"""
            return triage_agent

        # 给子智能体绑定回退函数
        code_agent.functions.append(transfer_back_to_triage)
        search_agent.functions.append(transfer_back_to_triage)
        qa_agent.functions.append(transfer_back_to_triage)

        # --- 分诊智能体 ---

        triage_agent = Agent(
            name="分诊智能体",
            instructions="""你是分诊智能体，负责分析用户的问题并将其路由到最合适的专家智能体。

你有三个专家可以调用：
1. **代码助手** — 处理编程、代码生成、调试、算法、技术实现相关问题。调用 transfer_to_code。
2. **搜索助手** — 处理需要联网查询最新信息、新闻、实时数据的问题。调用 transfer_to_search。
3. **知识问答助手** — 处理通用知识、概念解释、总结分析、建议推荐等问题。调用 transfer_to_qa。

分诊规则：
- 包含"代码""编程""实现""函数""debug""bug""算法""API"等关键词 → 代码助手
- 包含"搜索""查一下""最新""新闻""今天""最近"等关键词 → 搜索助手
- 其他通用问题（解释概念、总结内容、给建议等）→ 知识问答助手
- 如果不确定，优先交给知识问答助手

不要自己直接回答用户的问题，总是将问题转交给合适的专家智能体。
使用中文。""",
            functions=[transfer_to_code, transfer_to_search, transfer_to_qa],
            model=model,
        )

        return triage_agent

    def iter_events(self, messages: list[dict]) -> Iterable[dict]:
        """
        运行 Swarm 并将流式响应翻译为 SSE 事件。

        事件类型:
        - agent_transfer: 智能体切换
        - content: 回答内容片段
        - tool_call: 工具调用通知
        """
        try:
            yield {"type": "status", "content": "正在连接智能体网络..."}

            response_stream = self.swarm.run(
                agent=self.triage_agent,
                messages=messages,
                stream=True,
            )

            last_sender = ""
            content_buffer = ""

            for chunk in response_stream:
                # 智能体切换
                if "sender" in chunk:
                    sender = chunk["sender"]
                    if sender and sender != last_sender:
                        last_sender = sender
                        yield {"type": "agent_transfer", "content": sender}

                # 内容片段
                if "content" in chunk and chunk["content"] is not None:
                    text = chunk["content"]
                    if text:
                        content_buffer += text
                        yield {"type": "content", "content": text}

                # 工具调用
                if "tool_calls" in chunk and chunk["tool_calls"] is not None:
                    for tc in chunk["tool_calls"]:
                        func = tc.get("function", {})
                        name = func.get("name", "")
                        if name:
                            yield {"type": "tool_call", "content": name}

                # 消息分隔
                if "delim" in chunk and chunk["delim"] == "end" and content_buffer:
                    content_buffer = ""

                # 流结束
                if "response" in chunk:
                    break

        except Exception as e:
            logger.error(f"Swarm 流式执行失败: {e}", exc_info=True)
            # fallback: 尝试非流式执行
            try:
                yield {"type": "status", "content": "流式模式失败，切换到普通模式..."}
                response = self.swarm.run(
                    agent=self.triage_agent,
                    messages=messages,
                    stream=False,
                )
                for msg in response.messages:
                    if msg["role"] == "assistant" and msg.get("content"):
                        sender = msg.get("sender", "")
                        if sender:
                            yield {"type": "agent_transfer", "content": sender}
                        yield {"type": "content", "content": msg["content"]}
            except Exception as e2:
                logger.error(f"Swarm 非流式执行也失败: {e2}", exc_info=True)
                yield {"type": "content", "content": f"智能体网络执行出错: {e2}"}
