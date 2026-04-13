import asyncio
import logging
from server.bot.chat_bot import ChatBot
from config.config import QWEN_DATA, OLLAMA_DATA

# 配置日志
logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s][%(levelname)s]: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

async def main():
    print("=== AgentChatBot 命令行版 ===")
    print("输入 '#退出' 或 'exit' 结束对话")
    print("输入 '#智能体' 切换到智能体模式")
    print("输入 '#聊天' 切换到普通聊天模式")
    print("-" * 40)
    
    # 检查模型配置
    if OLLAMA_DATA.get("use"):
        print(f"当前使用Ollama模型: {OLLAMA_DATA.get('model')}")
    elif QWEN_DATA.get("use"):
        print(f"当前使用ChatGPT模型: {QWEN_DATA.get('model')}")
    else:
        print("警告: 没有启用任何模型，请检查config/config.py配置")
    print("-" * 40)
    
    use_agent = False
    # 在循环外创建 bot 实例，保持记忆跨轮次
    chat_bot = ChatBot(user_id="cli_user", user_name="CLI用户")

    while True:
        try:
            # 获取用户输入
            user_input = input("\n您: ").strip()

            # 退出命令
            if user_input.lower() in ['#退出', 'exit', 'quit']:
                print("再见！")
                break

            # 模式切换命令
            if user_input == "#智能体":
                use_agent = True
                print("已切换到智能体模式")
                continue
            elif user_input == "#聊天":
                use_agent = False
                print("已切换到普通聊天模式")
                continue

            if not user_input:
                continue

            # 处理用户输入
            print("机器人正在思考...")

            if use_agent:
                # 使用多智能体协作模式（Supervisor-Worker 架构）
                from server.bot.multi_agent.bot import MultiAgentBot
                provider = "ollama" if OLLAMA_DATA.get("use") else "qwen"
                bot = MultiAgentBot(provider=provider)
                response = await bot.run(query=user_input)
            else:
                # 使用普通聊天模式（复用同一实例，记忆自动管理）
                response = await chat_bot.run(
                    user_name="CLI用户",
                    query=user_input,
                    user_id="cli_user",
                    image_path=None,
                    file_path=None
                )
            
            print(f"\n机器人: {response}")
            
        except KeyboardInterrupt:
            print("\n\n程序被用户中断")
            break
        except Exception as e:
            logging.error(f"发生错误: {e}", exc_info=True)
            print(f"发生错误: {e}")

if __name__ == "__main__":
    asyncio.run(main())
