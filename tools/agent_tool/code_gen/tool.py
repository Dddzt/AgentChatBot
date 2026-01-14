import logging
from typing import ClassVar
import requests
from langchain.agents import tool
from pydantic import BaseModel
from langchain_openai import ChatOpenAI

from config.config import OLLAMA_DATA, CHATGPT_DATA
from config.templates.data.bot import CODE_BOT_PROMPT_DATA

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


class CodeGenAPIWrapper(BaseModel):
    base_url: ClassVar[str] = "http://localhost:11434/api/chat"
    content_role: ClassVar[str] = CODE_BOT_PROMPT_DATA.get("description")  # 从字典中取出提示词
    model: ClassVar[str] = OLLAMA_DATA.get("code_model") #可以使用其他的本地模型，自行修改

    def run_ollama(self, query: str, model_name: str) -> str:
        """使用本地 Ollama 模型生成代码"""
        logging.info(f"使用 Ollama 模型 {model_name} 处理用户请求: {query}")
        data = {
            "model": model_name,
            "messages": [{"role": "user", "content": self.content_role + "\n" + query}],  # 字符串拼接
            "stream": False,
        }
        response = requests.post(self.base_url, json=data)
        response.raise_for_status()

        try:
            result = response.json()
            return result.get("message", {}).get("content", "无法生成代码，请检查输入。")
        except requests.exceptions.JSONDecodeError as e:
            return f"解析 JSON 时出错: {e}"

    def run_chatgpt(self, query: str) -> str:
        """使用 ChatGPT/阿里云等在线 API 生成代码"""
        logging.info(f"使用在线模型 {CHATGPT_DATA.get('model')} 处理用户请求: {query}")
        try:
            model = ChatOpenAI(
                model=CHATGPT_DATA.get("model"),
                api_key=CHATGPT_DATA.get("key"),
                base_url=CHATGPT_DATA.get("url"),
                temperature=0.3  # 代码生成用较低温度
            )
            messages = [
                {"role": "system", "content": self.content_role},
                {"role": "user", "content": query}
            ]
            response = model.invoke(messages)
            return response.content
        except Exception as e:
            logging.error(f"使用在线模型生成代码时出错: {e}")
            return f"代码生成失败: {e}"

    def generate_code(self, query: str) -> str:
        try:
            # 优先使用配置中启用的模型
            if CHATGPT_DATA.get("use") and CHATGPT_DATA.get("key"):
                result = self.run_chatgpt(query)
            elif OLLAMA_DATA.get("use"):
                result = self.run_ollama(query, self.model)
            else:
                return "未配置可用的模型，请检查 config.py"
            
            if result and "无法生成代码" not in result and "失败" not in result:
                return result
        except Exception as e:
            logging.error(f"生成代码时出错: {e}")
        return "代码生成失败，请稍后再试。"

code_generator = CodeGenAPIWrapper()

@tool
def code_gen(query: str) -> str:
    """代码生成工具：根据用户描述生成相应的代码实现。"""
    return code_generator.generate_code(query)

# 返回工具信息
def register_tool():
    tool_func = code_gen  # 工具函数
    tool_func.__name__ = "code_gen"
    return {
        "name": "code_gen",
        "agent_tool": tool_func,
        "description": "代码生成工具"
    }

