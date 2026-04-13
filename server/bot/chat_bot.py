import asyncio
import logging
import os

from langchain_openai import ChatOpenAI

from config.config import QWEN_DATA, OLLAMA_DATA, MOONSHOT_DATA, BAICHUAN_DATA
from config.templates.data.bot import BOT_DATA, CHATBOT_PROMPT_DATA
from server.client.loadmodel.Ollama.OllamaClient import OllamaClient
from server.client.online.BaiChuanClient import BaiChuanClient
from server.client.online.moonshotClient import MoonshotClient
from server.memory import ConversationMemory

logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s][%(levelname)s]: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

base_dir = os.path.dirname(os.path.abspath(__file__))


class ChatBot:
    def __init__(self, user_name, user_id):
        self.user_id = user_id
        self.user_name = user_name
        self.memory = ConversationMemory(session_id=user_id)
        self.model = self.get_model_client()

    def get_model_client(self):
        """根据配置文件选择返回的模型"""
        if OLLAMA_DATA.get("use"):
            logging.info(f"使用Ollama模型生成回复: {OLLAMA_DATA.get('model')}")
            return OllamaClient()
        elif MOONSHOT_DATA.get("use") and MOONSHOT_DATA.get("key") is not None:
            logging.info(f"使用kimi模型生成回复: {MOONSHOT_DATA.get('model')}")
            return MoonshotClient()
        elif BAICHUAN_DATA.get("use") and BAICHUAN_DATA.get("key") is not None:
            logging.info(f"使用百川模型生成回复: {BAICHUAN_DATA.get('model')}")
            return BaiChuanClient()
        elif QWEN_DATA.get("use") and QWEN_DATA.get("key") is not None:
            logging.info(f"使用OpenAI模型生成回复: {QWEN_DATA.get('model')}")
            return ChatOpenAI(
                api_key=QWEN_DATA.get("key"),
                base_url=QWEN_DATA.get("url"),
                model=QWEN_DATA.get("model")
            )

    def generate_response(self, query):
        """生成AI回复，使用完整的对话历史"""
        try:
            if self.model is None:
                return "所有模型出错，key为空或者没有设置'use'为True"

            # 百川模型不支持系统提示词
            if BAICHUAN_DATA.get("use") and BAICHUAN_DATA.get("key") is not None:
                messages = self.memory.to_messages()
            else:
                # 构建系统提示词（不含历史和当前问题）
                system_prompt = CHATBOT_PROMPT_DATA.get("description").format(
                    name=BOT_DATA["chat"].get("name"),
                    capabilities=BOT_DATA["chat"].get("capabilities"),
                    welcome_message=BOT_DATA["chat"].get("default_responses").get("welcome_message"),
                    unknown_command=BOT_DATA["chat"].get("default_responses").get("unknown_command"),
                    language_support=BOT_DATA["chat"].get("language_support"),
                )
                # 组装完整消息列表：system + 历史对话 + 当前问题
                messages = [{"role": "system", "content": system_prompt}] + self.memory.to_messages()

            response = self.model.invoke(messages)
            if response:
                logging.info("成功生成回复")
                return response.content
        except Exception as e:
            logging.warning(f"模型生成回复失败: {e}")
            return "模型生成回复失败，请稍后再试。"

    async def run(self, user_name, query, user_id, image_path, file_path):
        """主运行逻辑，管理历史记录、生成回复，并保存会话记录"""
        logging.info(f"接收到用户id为：{user_id}，用户名为{user_name}的消息")

        # 加载历史并添加当前用户消息
        self.memory.load()
        self.memory.add_user_message(query)

        # 生成AI回复
        response = self.generate_response(query)

        # 保存AI回复到记忆
        self.memory.add_assistant_message(response)
        self.memory.save()

        return response


if __name__ == "__main__":
    query = "你是谁"
    user_id = "0101"
    user_name = "pan"
    bot = ChatBot(user_id=user_id, user_name=user_name)

    response = asyncio.run(bot.run(user_id=user_id, query=query, user_name=user_name, file_path=None, image_path=None))

    print(response)
