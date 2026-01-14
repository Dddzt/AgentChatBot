import requests
import json
import time


class OllamaChatBot:
    """Ollama 本地模型测试类，支持系统提示词和多轮对话记忆"""

    def __init__(self, model_name: str = "", base_url: str = "http://localhost:11434"):
        # 初始化核心参数
        self.model_name = model_name  # 你的模型名（如qwen2:7b-chat/my-chatbot）
        self.base_url = base_url
        self.api_url = f"{self.base_url}/api/chat"
        self.chat_history = []  # 存储多轮对话历史
        self.system_prompt = ""  # 系统提示词

    def set_system_prompt(self, prompt: str):
        """设置系统提示词（项目指定的规则）"""
        self.system_prompt = prompt
        # 将系统提示词加入对话历史的最开头
        self.chat_history.insert(0, {"role": "system", "content": self.system_prompt})

    def send_message(self, user_input: str, stream: bool = True) -> str:
        """
        发送用户消息，获取模型回复
        :param user_input: 用户输入的问题
        :param stream: 是否流式输出（强制为True，保证实时输出）
        :return: 模型的完整回复内容
        """
        # 1. 添加用户当前输入到对话历史
        self.chat_history.append({"role": "user", "content": user_input})

        # 2. 构造API请求参数（强制流式输出）
        payload = {
            "model": self.model_name,
            "messages": self.chat_history,
            "stream": True,  # 固定为True，确保流式输出
            "temperature": 0.3,  # 低温度保证系统提示词遵循性
            "num_ctx": 8192  # 增大上下文窗口，强化多轮记忆
        }

        try:
            # 3. 调用Ollama API（流式请求）
            response = requests.post(
                self.api_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=60,  # 超时时间（适配AMD显卡推理速度）
                stream=True  # 关键：开启流式响应接收
            )
            response.raise_for_status()  # 抛出HTTP错误

            # 4. 解析流式响应（核心修改：实时逐段输出）
            reply = ""
            print("机器人：", end="", flush=True)  # 先打印前缀，不换行
            for line in response.iter_lines(chunk_size=1024):
                if line:
                    # 解析单条流式数据
                    line_data = json.loads(line.decode("utf-8").strip())
                    # 处理结束标识（Ollama流式响应最后一条会带done: true）
                    if line_data.get("done", False):
                        break
                    # 提取实时回复内容并输出
                    if "message" in line_data and "content" in line_data["message"]:
                        chunk = line_data["message"]["content"]
                        reply += chunk
                        print(chunk, end="", flush=True)  # 实时打印，不换行
            print()  # 回复结束后换行
            # 将完整回复加入对话历史（维护多轮记忆）
            self.chat_history.append({"role": "assistant", "content": reply})
            return reply

        except requests.exceptions.ConnectionError:
            error_msg = "错误：无法连接到Ollama服务，请确认模型已启动（ollama run 模型名），且端口11434未被占用。"
            print(f"\n机器人：{error_msg}")
            return error_msg
        except requests.exceptions.Timeout:
            error_msg = "错误：请求超时，AMD显卡推理可能较慢，可适当增大timeout参数。"
            print(f"\n机器人：{error_msg}")
            return error_msg
        except Exception as e:
            error_msg = f"错误：{str(e)}"
            print(f"\n机器人：{error_msg}")
            return error_msg

    def clear_history(self):
        """清空对话历史（保留系统提示词）"""
        if self.chat_history and self.chat_history[0]["role"] == "system":
            self.chat_history = [self.chat_history[0]]
        else:
            self.chat_history = []


# ---------------------- 测试示例 ----------------------
if __name__ == "__main__":
    # 1. 初始化机器人（替换为你的模型名，如qwen2:7b-chat/deepseek-r1:7b-chat）
    # 注意：替换base_url为Ubuntu的IP，如http://192.168.1.105:11434
    bot = OllamaChatBot(model_name="qwen:1.8b", base_url="http://localhost:11434")

    # 2. 设置项目指定的系统提示词（核心需求）
    system_prompt = """你是智能客服机器人，必须遵循以下规则：
    1. 回答简洁，不超过100字；
    2. 仅处理电商售后相关问题；
    3. 多轮对话中记住用户的问题上下文。"""
    bot.set_system_prompt(system_prompt)

    # 3. 多轮对话测试
    print("===== 智能聊天机器人测试 =====")
    print("输入 'exit' 退出测试，输入 'clear' 清空对话历史\n")

    while True:
        user_input = input("你：")
        if user_input.lower() == "exit":
            print("机器人：测试结束～")
            break
        if user_input.lower() == "clear":
            bot.clear_history()
            print("机器人：对话历史已清空！")
            continue

        # 发送消息并获取回复（强制流式输出）
        start_time = time.time()
        reply = bot.send_message(user_input, stream=True)
        end_time = time.time()

        # 输出耗时（不干扰流式回复的实时显示）
        print(f"（推理耗时：{end_time - start_time:.2f}秒）\n")