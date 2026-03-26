import traceback
import logging
import json
import asyncio
import os
from typing import Any, AsyncIterator
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

import redis
from config.config import QWEN_DATA, REDIS_DATA
from config.templates.data.bot import MAX_HISTORY_SIZE, MAX_HISTORY_LENGTH, AGENT_BOT_PROMPT_DATA, BOT_DATA
from tools.tool_loader import ToolLoader

# 初始化工具加载器
tool_loader = ToolLoader()
tool_loader.load_tools()

# 获取加载的工具函数列表
tools = tool_loader.get_tools()

logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s][%(levelname)s]: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

os.environ["OPENAI_API_KEY"] = QWEN_DATA.get("key")
os.environ["OPENAI_API_BASE"] = QWEN_DATA.get("url")

# Redis 连接池
def get_redis_client():
    try:
        redis_pool = redis.ConnectionPool(host=REDIS_DATA.get("host"), port=REDIS_DATA.get("port"), db=REDIS_DATA.get("db"))
        client = redis.StrictRedis(connection_pool=redis_pool)
        client.ping()
        return client
    except redis.RedisError as e:
        logging.warning(f"Redis连接失败，将不使用历史记录功能: {e}")
        return None

redis_client = get_redis_client()

# 存储会话中的图像路径
user_image_map = {}

# 存储会话中的文件路径
user_file_map = {}

# 执行任务的线程池
executor = ThreadPoolExecutor(max_workers=20)


class AgentBot:
    def __init__(self, user_id, user_name, query, provider: str | None = None):
        self.query = query
        self.user_name = user_name
        self.user_id = user_id
        self.redis_key_prefix = "chat_history:"
        self.history = []

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 构建系统提示词
        self.system_prompt = AGENT_BOT_PROMPT_DATA.get("description").format(
            name=BOT_DATA["agent"].get("name"),
            capabilities=BOT_DATA["agent"].get("capabilities"),
            welcome_message=BOT_DATA["agent"].get("default_responses").get("welcome_message"),
            unknown_command=BOT_DATA["agent"].get("default_responses").get("unknown_command"),
            language_support=BOT_DATA["agent"].get("language_support"),
            current_time=current_time,
            history=self.format_history(),
            query=self.query,
            user_name=self.user_name,
            user_id=self.user_id,
        )

        # 根据 provider 选择 LLM 配置
        llm_config = self._resolve_llm_config(provider)
        self.llm = ChatOpenAI(
            model=llm_config["model"],
            api_key=llm_config["key"],
            base_url=llm_config["url"],
            temperature=llm_config.get("temperature", 0.7),
            streaming=True,
            **(llm_config.get("model_kwargs") or {}),
        )

        # 使用 langgraph 创建 ReAct agent
        self.agent = create_react_agent(
            self.llm,
            tools,
            prompt=self.system_prompt,
        )

    @staticmethod
    def _resolve_llm_config(provider: str | None) -> dict:
        """根据 provider 返回对应的 LLM 配置。"""
        from config.config import OLLAMA_DATA, MOONSHOT_DATA
        if provider == "ollama" and OLLAMA_DATA.get("use"):
            return {
                "model": OLLAMA_DATA.get("model"),
                "key": OLLAMA_DATA.get("key", "EMPTY"),
                "url": OLLAMA_DATA.get("api_url"),
                "temperature": 0.7,
            }
        if provider == "moonshot" and MOONSHOT_DATA.get("use"):
            model_name = MOONSHOT_DATA.get("model")
            cfg = {
                "model": model_name,
                "key": MOONSHOT_DATA.get("key"),
                "url": MOONSHOT_DATA.get("url"),
            }
            # kimi-k2.5 / kimi-k2.5-thinking 的 thinking 模式与 langgraph 工具调用不兼容，
            # 需要禁用 thinking 并使用其允许的 temperature=0.6
            if model_name in ("kimi-k2.5", "kimi-k2.5-thinking"):
                cfg["temperature"] = 0.6
                cfg["model_kwargs"] = {
                    "extra_body": {"thinking": {"type": "disabled"}}
                }
            else:
                cfg["temperature"] = 0.3
            return cfg
        # 默认 / qwen
        return {
            "model": QWEN_DATA.get("model"),
            "key": QWEN_DATA.get("key"),
            "url": QWEN_DATA.get("url"),
            "temperature": QWEN_DATA.get("temperature", 0.7),
        }

    @staticmethod
    def _contains_code_block(text: str) -> bool:
        return isinstance(text, str) and "```" in text

    @staticmethod
    def _tool_status_text(tool_name: str) -> str:
        status_map = {
            "code_gen": "正在生成代码，请稍等...",
            "search_tool": "正在联网搜索并整理信息...",
        }
        return status_map.get(tool_name, f"正在调用工具 {tool_name} ...")

    def _build_combined_input(self, query, image_path, file_path, user_id, history):
        return (
            f"{query}\n"
            f"用户id:{user_id}\n"
            f"图像路径: {image_path}\n"
            f"文件路径:{file_path}\n"
            f"历史记录:\n {history}"
        )

    async def astream(
        self,
        user_name,
        query,
        image_path,
        file_path,
        user_id,
    ) -> AsyncIterator[dict[str, str]]:
        try:
            self.manage_history()
            self.history.append({"Human": query})

            history = self.format_history()
            combined_input = self._build_combined_input(query, image_path, file_path, user_id, history)

            yield {"type": "status", "content": "正在分析你的问题，并规划处理步骤..."}

            visible_parts = []
            active_tool = None

            async for event in self.agent.astream_events(
                {"messages": [("user", combined_input)]},
                version="v2",
            ):
                event_name = event.get("event", "")
                event_data = event.get("data", {})
                event_node_name = event.get("name", "")

                if event_name == "on_tool_start":
                    active_tool = event_node_name
                    yield {
                        "type": "status",
                        "content": self._tool_status_text(event_node_name),
                    }
                    continue

                if event_name == "on_tool_end":
                    yield {
                        "type": "status",
                        "content": "工具执行完成，正在整理最终回答...",
                    }
                    active_tool = None
                    continue

                if event_name == "on_chat_model_stream":
                    chunk = event_data.get("chunk")
                    chunk_text = getattr(chunk, "content", chunk)
                    if not isinstance(chunk_text, str) or not chunk_text:
                        continue

                    # 非工具调用阶段的 LLM 流式回复
                    if active_tool is None:
                        visible_parts.append(chunk_text)
                        yield {"type": "content", "content": chunk_text}
                    continue

            self.save_history_to_redis(self.user_id, self.history)
        except Exception as e:
            logging.error(f"运行时发生错误: {e}")
            traceback.print_exc()
            yield {"type": "content", "content": f"发生错误: {e}"}

    def format_history(self):
        history = self.get_history_from_redis(self.user_id)
        if not history:
            return ""

        formatted_history = []
        for entry in history:
            human_text = entry.get('Human', '')
            formatted_history.append(f"Human: {human_text}\n")

        return "\n".join(formatted_history)

    def get_history_from_redis(self, user_id):
        if redis_client is None:
            return []
        key = f"{self.redis_key_prefix}{user_id}"
        try:
            history = redis_client.get(key)
            if history:
                return json.loads(history)
        except redis.RedisError as e:
            logging.error(f"从Redis获取历史记录时出错: {e}")
        return []

    def save_history_to_redis(self, user_id, history):
        if redis_client is None:
            return
        key = f"{self.redis_key_prefix}{user_id}"
        try:
            redis_client.set(key, json.dumps(history))
        except redis.RedisError as e:
            logging.error(f"保存历史记录到Redis时出错: {e}")

    def manage_history(self):
        self.history = self.get_history_from_redis(self.user_id)

        while len(self.history) > MAX_HISTORY_SIZE:
            self.history.pop(0)

        history_str = json.dumps(self.history)
        while len(history_str) > MAX_HISTORY_LENGTH:
            if self.history:
                self.history.pop(0)
                history_str = json.dumps(self.history)
            else:
                break

    async def run(self, user_name, query, image_path, file_path, user_id):
        try:
            self.manage_history()
            self.history.append({"Human": query})
            history = self.format_history()
            combined_input = self._build_combined_input(query, image_path, file_path, user_id, history)

            result = await self.agent.ainvoke(
                {"messages": [("user", combined_input)]}
            )

            # 提取最终的 AI 回复
            messages = result.get("messages", [])
            response = ""
            for msg in reversed(messages):
                if hasattr(msg, "content") and getattr(msg, "type", "") == "ai" and msg.content:
                    response = msg.content
                    break

            self.save_history_to_redis(self.user_id, self.history)
            return response if response else "处理完成"
        except Exception as e:
            logging.error(f"运行时发生错误: {e}")
            traceback.print_exc()
            return f"发生错误: {e}"


if __name__ == "__main__":
    query = "使用代码工具，给我生成一份可执行的二叉树的python代码"
    user_id = "123"
    user_name = ""
    bot = AgentBot(query=query, user_id=user_id, user_name=user_name)

    response = asyncio.run(bot.run(user_id=user_id, query=query, user_name=user_name, file_path=None, image_path=None))
    print(response)
