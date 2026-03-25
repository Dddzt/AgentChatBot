import traceback
from typing import Any, AsyncIterator
from langchain_core.prompts import MessagesPlaceholder, ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain.agents.agent import AgentExecutor
from langchain.agents.format_scratchpad.openai_tools import format_to_openai_tool_messages
from langchain.agents.output_parsers.openai_tools import OpenAIToolsAgentOutputParser

from config.config import CHATGPT_DATA, REDIS_DATA
from config.templates.data.bot import MAX_HISTORY_SIZE, MAX_HISTORY_LENGTH, AGENT_BOT_PROMPT_DATA, BOT_DATA
import logging
from datetime import datetime
import json
import redis
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from tools.tool_loader import ToolLoader

# 初始化工具加载器
tool_loader = ToolLoader()
tool_loader.load_tools()  # 加载工具

# 获取加载的工具函数列表
tools = tool_loader.get_tools()

# 设置日志记录
logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s][%(levelname)s]: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

os.environ["OPENAI_API_KEY"] = CHATGPT_DATA.get("key")
os.environ["OPENAI_API_BASE"] = CHATGPT_DATA.get("url")

# Redis 连接池
def get_redis_client():
    """获取Redis客户端，如果连接失败则返回None"""
    try:
        redis_pool = redis.ConnectionPool(host=REDIS_DATA.get("host"), port=REDIS_DATA.get("port"), db=REDIS_DATA.get("db"))
        client = redis.StrictRedis(connection_pool=redis_pool)
        client.ping()  # 测试连接
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

# 当前时间
current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

class AgentBot:
    def __init__(self, user_id, user_name, query):
        self.query = query
        self.user_name = user_name
        self.chatModel_4o_mini = ChatOpenAI(
            model=CHATGPT_DATA.get("model"),  # 从配置读取模型名
            api_key=CHATGPT_DATA.get("key"),  # 从配置读取 API Key
            base_url=CHATGPT_DATA.get("url"),  # 从配置读取 API URL
            temperature=CHATGPT_DATA.get("temperature", 0),  # 从配置读取温度
            streaming=True
        )
        self.redis_key_prefix = "chat_history:"
        self.history = []  # 自定义的历史记录列表
        self.saved_files = {}  # 保存文件路径的字典
        self.user_id = user_id
        # 创建聊天模板，包括上下文信息和结构化的交互模式
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    AGENT_BOT_PROMPT_DATA.get("description").format
                        (
                        name=BOT_DATA["agent"].get("name"),
                        capabilities=BOT_DATA["agent"].get("capabilities"),
                        welcome_message=BOT_DATA["agent"].get("default_responses").get("welcome_message"),
                        unknown_command=BOT_DATA["agent"].get("default_responses").get("unknown_command"),
                        language_support=BOT_DATA["agent"].get("language_support"),
                        current_time=current_time,
                        history=self.format_history(),
                        query=self.query,
                        user_name=self.user_name,
                        user_id=self.user_id
                    ),
                ),
                (
                    "user",
                    "{input}"
                ),
                MessagesPlaceholder(variable_name="agent_scratchpad") # 用于存储智能体在执行工具调用过程中的中间思考和观察结果
            ]
        )

        # 绑定工具到模型
        llm_with_tools = self.chatModel_4o_mini.bind_tools(tools)
        
        # 创建智能体链
        agent = (
            {
                "input": lambda x: x["input"],
                "agent_scratchpad": lambda x: format_to_openai_tool_messages(
                    x["intermediate_steps"]
                ),
            }
            | self.prompt
            | llm_with_tools
            | OpenAIToolsAgentOutputParser()
        )

        # 创建智能体执行器
        self.agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=True,
            return_intermediate_steps=True
        )

    @staticmethod
    def _contains_code_block(text: str) -> bool:
        return isinstance(text, str) and "```" in text

    @staticmethod
    def _extract_tool_output(result: dict[str, Any], tool_name: str) -> str:
        for step in reversed(result.get("intermediate_steps", [])):
            if not isinstance(step, tuple) or len(step) != 2:
                continue

            action, observation = step
            if getattr(action, "tool", "") != tool_name:
                continue

            if isinstance(observation, str) and observation.strip():
                return observation.strip()

        return ""

    def _build_final_response(self, result: dict[str, Any]) -> str:
        response = result.get("output", "Error occurred")
        code_output = self._extract_tool_output(result, "code_gen")

        if code_output and not self._contains_code_block(response):
            return (
                f"{response}\n\n"
                "下面是这次生成的完整代码：\n\n"
                f"{code_output}"
            )

        return response

    def _build_combined_input(self, query, image_path, file_path, user_id, history):
        return (
            f"{query}\n"
            f"用户id:{user_id}\n"
            f"图像路径: {image_path}\n"
            f"文件路径:{file_path}\n"
            f"历史记录:\n {history}"
        )

    @staticmethod
    def _tool_status_text(tool_name: str) -> str:
        status_map = {
            "code_gen": "正在生成代码，请稍等...",
            "search_tool": "正在联网搜索并整理信息...",
        }
        return status_map.get(tool_name, f"正在调用工具 {tool_name} ...")

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

            active_tool = None
            code_tool_streamed = False
            visible_parts = []
            final_result = None

            yield {"type": "status", "content": "正在分析你的问题，并规划处理步骤..."}

            async for event in self.agent_executor.astream_events(
                {"input": combined_input},
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
                    if active_tool == "code_gen" and not code_tool_streamed:
                        tool_output = event_data.get("output")
                        if isinstance(tool_output, str) and tool_output.strip():
                            visible_parts.append(tool_output)
                            code_tool_streamed = True
                            yield {"type": "content", "content": tool_output}
                    elif active_tool and active_tool != "code_gen":
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

                    if active_tool == "code_gen":
                        visible_parts.append(chunk_text)
                        code_tool_streamed = True
                        yield {"type": "content", "content": chunk_text}
                        continue

                    if active_tool is None and not code_tool_streamed:
                        visible_parts.append(chunk_text)
                        yield {"type": "content", "content": chunk_text}
                    continue

                if event_name == "on_chain_end" and event_node_name == "AgentExecutor":
                    output = event_data.get("output")
                    if isinstance(output, dict):
                        final_result = output

            final_response = self._build_final_response(final_result) if isinstance(final_result, dict) else ""
            streamed_response = "".join(visible_parts)

            if final_response and not streamed_response:
                yield {"type": "content", "content": final_response}
            elif final_response and streamed_response and final_response.startswith(streamed_response):
                remainder = final_response[len(streamed_response):]
                if remainder:
                    yield {"type": "content", "content": remainder}

            self.save_history_to_redis(self.user_id, self.history)
        except Exception as e:
            logging.error(f"运行时发生错误: {e}")
            traceback.print_exc()
            yield {"type": "content", "content": "发生错误"}

    def format_history(self):
        """从Redis获取并格式化历史记录"""
        history = self.get_history_from_redis(self.user_id)
        if not history:
            logging.info("没有从Redis中获取到历史记录")
            return ""

        formatted_history = []
        for entry in history:
            human_text = entry.get('Human', '')

            formatted_history.append(f"Human: {human_text}\n")

        return "\n".join(formatted_history)

    def get_history_from_redis(self, user_id):
        """从Redis获取历史记录"""
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
        """将历史记录保存到Redis"""
        if redis_client is None:
            return
        key = f"{self.redis_key_prefix}{user_id}"
        try:
            redis_client.set(key, json.dumps(history))
        except redis.RedisError as e:
            logging.error(f"保存历史记录到Redis时出错: {e}")

    def manage_history(self):
        """管理历史记录：删除最早de记录或截断字符长度"""
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
            # 从Redis获取历史记录并管理
            self.manage_history()

            # 添加用户输入到历史记录
            self.history.append({
                "Human": query,
            })

            # 调用格式化历史记录的方法
            history = self.format_history()

            # 生成结合用户输入和历史记录的输入
            combined_input = self._build_combined_input(query, image_path, file_path, user_id, history)

            result = await asyncio.get_event_loop().run_in_executor(executor, lambda: self.agent_executor.invoke(
                {"input": combined_input}))

            response = self._build_final_response(result)

            # # 将生成的回复加入历史记录
            # self.history.append({
            #     "AI": response,
            # })
            # 可以做保存也可以不做保存，保存提问的问题就可以满足很多需求

            # 保存更新后的历史记录到Redis
            self.save_history_to_redis(self.user_id, self.history)

            return response
        except Exception as e:
            logging.error(f"运行时发生错误: {e}")
            traceback.print_exc()
            return "发生错误"

if __name__ == "__main__":
    query = "使用代码工具，给我生成一份可执行的二叉树的python代码"
    user_id = "123"
    user_name = ""
    bot = AgentBot(query=query, user_id=user_id, user_name=user_name)

    # 运行异步函数
    response = asyncio.run(bot.run(user_id=user_id, query=query, user_name=user_name, file_path=None, image_path=None))

    print(response)
