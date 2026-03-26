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
                # 使用智能体模式
                if QWEN_DATA.get("use"):
                    from server.bot.agent_bot import AgentBot
                    agent_bot = AgentBot(query=user_input, user_id="cli_user", user_name="CLI用户")
                    response = await agent_bot.run(
                        user_name="CLI用户",
                        query=user_input,
                        image_path=None,
                        file_path=None,
                        user_id="cli_user"
                    )
                elif OLLAMA_DATA.get("use"):
                    from server.bot.swarm_agent_bot import SwarmBot
                    swarm_bot = SwarmBot(query=user_input, user_id="cli_user", user_name="CLI用户")
                    response = await swarm_bot.run(
                        user_name="CLI用户",
                        query=user_input,
                        image_path=None,
                        file_path=None,
                        user_id="cli_user"
                    )
                else:
                    response = "请在config/config.py中启用QWEN_DATA或OLLAMA_DATA"
            else:
                # 使用普通聊天模式
                bot = ChatBot(user_id="cli_user", user_name="CLI用户")
                response = await bot.run(
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
