import json
import re
import os
import requests
from datetime import datetime
from flask import jsonify
from urllib.parse import quote

from config.templates.data.bot import CHATBOT_PROMPT_DATA, BOT_DATA, AGENT_BOT_PROMPT_DATA
from config.config import FEISHU_DATA, DOWNLOAD_ADDRESS
from playground.feishu.message_type_group import MessageTypeGroup
from playground.feishu.message_type_private import MessageTypePrivate
from playground.feishu.send_message import SendMessage
from config.config import CHATGPT_DATA, OLLAMA_DATA
from langchain_openai import ChatOpenAI
from tools.file_processor import file_processor

# 当前时间
current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

class FeishuMessageHandler:
    def __init__(self, feishu_user,):
        # 创建 client
        self.feishu_user = feishu_user
        
        # 优先使用阿里云API，兜底使用Ollama
        if CHATGPT_DATA.get('use'):
            self.chat_model = ChatOpenAI(
                model=CHATGPT_DATA.get('model'),
                openai_api_key=CHATGPT_DATA.get('key'),
                openai_api_base=CHATGPT_DATA.get('url'),
                temperature=CHATGPT_DATA.get('temperature', 0.7)
            )
        else:
            # 使用Ollama本地模型
            from server.client.loadmodel.Ollama.OllamaClient import OllamaClient
            self.chat_model = OllamaClient()
        
        # 存储已处理过的 message_id
        self.processed_messages = set()
        self.send_message_tool = SendMessage()
        self.message_type_private = MessageTypePrivate
        self.message_type_group = MessageTypeGroup
        
        # 初始化时获取有效的token
        self.tenant_access_token = self._get_tenant_access_token()
    
    def _get_tenant_access_token(self) -> str:
        """获取飞书 tenant_access_token"""
        try:
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            payload = {
                "app_id": FEISHU_DATA.get('app_id'),
                "app_secret": FEISHU_DATA.get('app_secret')
            }
            response = requests.post(url, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('code') == 0:
                    token = result.get('tenant_access_token')
                    print(f"[Token刷新] 成功获取 tenant_access_token")
                    return token
                else:
                    print(f"[Token刷新] 失败: {result.get('msg')}")
                    return FEISHU_DATA.get('tenant_access_token')  # 使用配置中的兜底
            else:
                print(f"[Token刷新] HTTP错误: {response.status_code}")
                return FEISHU_DATA.get('tenant_access_token')
        except Exception as e:
            print(f"[Token刷新] 异常: {e}")
            return FEISHU_DATA.get('tenant_access_token')
    
    def download_feishu_file(self, file_key: str, file_type: str, message_id: str = None, file_name: str = None) -> str:
        """
        从飞书下载文件到本地
        
        Args:
            file_key: 飞书文件key
            file_type: 文件类型 (image/file/audio/video)
            message_id: 消息ID（下载文件资源时需要）
            file_name: 文件名称
        
        Returns:
            本地文件路径
        """
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import GetImageRequest, GetMessageResourceRequest
            
            # 根据类型选择存储目录
            if file_type == 'image':
                save_dir = DOWNLOAD_ADDRESS.get('image', 'downloads/image')
                if not file_name:
                    file_name = f"image_{file_key[:20]}.png"
            elif file_type == 'audio':
                save_dir = DOWNLOAD_ADDRESS.get('audio', 'downloads/audio')
                if not file_name:
                    file_name = f"audio_{file_key[:20]}.opus"
            elif file_type == 'video':
                save_dir = DOWNLOAD_ADDRESS.get('vidio', 'downloads/vidio')
                if not file_name:
                    file_name = f"video_{file_key[:20]}.mp4"
            else:
                save_dir = DOWNLOAD_ADDRESS.get('file', 'downloads/file')
                if not file_name:
                    file_name = f"file_{file_key[:20]}"
            
            # 确保目录存在
            os.makedirs(save_dir, exist_ok=True)
            file_path = os.path.join(save_dir, file_name)
            
            # 使用飞书SDK下载
            if file_type == 'image':
                # 使用SDK下载图片
                request = GetImageRequest.builder() \
                    .image_key(file_key) \
                    .build()
                
                response = self.feishu_user.client.im.v1.image.get(request)
                
                if response.success():
                    # 保存图片
                    with open(file_path, 'wb') as f:
                        f.write(response.raw.content)
                    print(f"[文件下载] 成功: {file_path}")
                    return file_path
                else:
                    print(f"[文件下载] 失败: code={response.code}, msg={response.msg}")
                    return None
            else:
                # 下载文件/音频/视频需要message_id
                if not message_id:
                    print(f"[文件下载] 缺少message_id参数")
                    return None
                    
                request = GetMessageResourceRequest.builder() \
                    .message_id(message_id) \
                    .file_key(file_key) \
                    .type(file_type) \
                    .build()
                
                response = self.feishu_user.client.im.v1.message_resource.get(request)
                
                if response.success():
                    with open(file_path, 'wb') as f:
                        f.write(response.raw.content)
                    print(f"[文件下载] 成功: {file_path}")
                    return file_path
                else:
                    print(f"[文件下载] 失败: code={response.code}, msg={response.msg}")
                    return None
                
        except Exception as e:
            print(f"[文件下载] 异常: {e}")
            import traceback
            traceback.print_exc()
            return None

    def handle_message(self, event_data,event_type):
        print(f"\n[handle_message] event_type={event_type}")
        print(f"[handle_message] event_data={event_data}\n")
                
        if event_type == "im.message.receive_v1":
            message = event_data.get('message', {})
            message_id = message.get('message_id')
            chat_type = message.get('chat_type')
            message_type = message.get('message_type')  # 获取消息类型
                
            # 根据消息类型解析内容
            content_raw = message.get('content', '{}')
            sender_id = event_data.get('sender', {}).get('sender_id', {}).get('open_id')
                
            print(f"[消息信息] message_id={message_id}, chat_type={chat_type}, message_type={message_type}, sender_id={sender_id}")
                
            # 解析不同类型的消息内容
            try:
                content_json = json.loads(content_raw)
            except:
                content_json = {}
                
            # 根据消息类型提取查询内容并处理文件
            file_content = ""  # 存储文件分析内容
            
            if message_type == "text":
                query = content_json.get('text', '')
            elif message_type == "image":
                image_key = content_json.get('image_key', '')
                print(f"[图片消息] image_key={image_key}")
                
                # 下载并处理图片
                file_path = self.download_feishu_file(image_key, 'image', message_id)
                if file_path:
                    file_content = file_processor.convert_to_text(file_path)
                    query = "[用户发送了图片，请根据图片内容回答问题]"
                else:
                    query = "[图片下载失败]"
                    
            elif message_type == "file":
                file_key = content_json.get('file_key', '')
                file_name = content_json.get('file_name', '未知文件')
                print(f"[文件消息] file_key={file_key}, file_name={file_name}")
                
                # 下载并处理文件
                file_path = self.download_feishu_file(file_key, 'file', message_id, file_name)
                if file_path:
                    file_content = file_processor.convert_to_text(file_path)
                    query = f"[用户发送了文件: {file_name}，请根据文件内容回答问题]"
                else:
                    query = f"[文件 {file_name} 下载失败]"
                    
            elif message_type == "audio":
                file_key = content_json.get('file_key', '')
                print(f"[语音消息] file_key={file_key}")
                
                # 下载并处理音频
                file_path = self.download_feishu_file(file_key, 'audio', message_id)
                if file_path:
                    file_content = file_processor.convert_to_text(file_path)
                    query = "[用户发送了语音，请根据语音信息回答问题]"
                else:
                    query = "[语音下载失败]"
                    
            elif message_type == "media":
                file_key = content_json.get('file_key', '')
                print(f"[视频消息] file_key={file_key}")
                
                # 下载并处理视频
                file_path = self.download_feishu_file(file_key, 'video', message_id)
                if file_path:
                    file_content = file_processor.convert_to_text(file_path)
                    query = "[用户发送了视频，请根据视频信息回答问题]"
                else:
                    query = "[视频下载失败]"
                    
            else:
                query = f"[不支持的消息类型: {message_type}]"
                print(f"[警告] 收到不支持的消息类型: {message_type}")
                
            print(f"[用户消息] {query}")
                
            if chat_type == "p2p":
                # \u68c0\u67e5\u662f\u5426\u5df2\u7ecf\u5904\u7406\u8fc7\u8fd9\u6761\u6d88\u606f
                if message_id in self.processed_messages:
                    print(f"[\u8df3\u8fc7] \u6d88\u606f {message_id} \u5df2\u7ecf\u5904\u7406\u8fc7")
                    return jsonify({"success": False, "message": "\u6d88\u606f\u5df2\u5904\u7406"})
    
                # \u6807\u8bb0\u6d88\u606f\u4e3a\u5df2\u5904\u7406
                self.processed_messages.add(message_id)
                print(f"[\u5f00\u59cb\u5904\u7406] \u79c1\u804a\u6d88\u606f")
    
                try:
                    # \u83b7\u53d6\u7528\u6237\u4fe1\u606f
                    user_info = self.feishu_user.get_user_info_by_id(
                        user_id=sender_id,
                        user_id_type="open_id"
                    )
                    formatted_info = self.feishu_user.format_user_info(user_info.get("data", {}))
                    user_name = formatted_info.get("name", "未知用户")
                    print(f"[用户信息] {user_name}")
                        
                    # 如果有文件内容，添加到查询中
                    if file_content:
                        enhanced_query = f"{file_content}\n\n{query}"
                    else:
                        enhanced_query = query
                        
                    messages = [
                        {"role": "system", "content": AGENT_BOT_PROMPT_DATA.get("description").format
                                                        (
                                                        name=BOT_DATA["agent"].get("name"),
                                                        capabilities=BOT_DATA["agent"].get("capabilities"),
                                                        welcome_message=BOT_DATA["agent"].get("default_responses").get("welcome_message"),
                                                        unknown_command=BOT_DATA["agent"].get("default_responses").get("unknown_command"),
                                                        language_support=BOT_DATA["agent"].get("language_support"),
                                                        current_time=current_time,
                                                        history=None,
                                                        query=enhanced_query,
                                                        user_name=user_name,
                                                        user_id=sender_id
                                                    )},
                        {"role": "user", "content": enhanced_query}
                    ]
    
                    print(f"[调用模型] 开始生成回复...")
                    # 调用模型，兼容两种类型
                    if hasattr(self.chat_model, 'invoke') and 'ChatOpenAI' in str(type(self.chat_model)):
                        # LangChain ChatOpenAI
                        from langchain_core.messages import HumanMessage, SystemMessage
                        lc_messages = [
                            SystemMessage(content=messages[0]['content']),
                            HumanMessage(content=messages[1]['content'])
                        ]
                        response = self.chat_model.invoke(lc_messages).content
                    else:
                        # OllamaClient
                        response = self.chat_model.invoke(messages=messages).content
                    print(f"[模型回复] {response}")
    
                    message_params = self.message_type_private(
                        receive_id=sender_id,
                        receive_id_type="open_id"
                    ).handle(response)
    
                    print(f"[\u53d1\u9001\u6d88\u606f] \u5f00\u59cb\u53d1\u9001...")
                    send_result = self.send_message_tool.send_message(message_params=message_params)
                    print(f"[\u53d1\u9001\u7ed3\u679c] {send_result}")
    
                    return jsonify({
                        "message": f"\u6d88\u606f\u5904\u7406\u6210\u529f\uff0c\u6765\u81ea\u7528\u6237 {user_name} \u7684\u6d88\u606f\u5df2\u56de\u590d\u3002",
                        "success": True
                    })
                        
                except Exception as e:
                    print(f"[\u9519\u8bef] \u5904\u7406\u79c1\u804a\u6d88\u606f\u5931\u8d25: {e}")
                    import traceback
                    traceback.print_exc()
                    return jsonify({"error": str(e), "success": False}), 500
            elif chat_type == "group":
                chat_id = message.get('chat_id')
                mentions = message.get('mentions', [])
                
                # 检查是否有mentions且第一个mention存在
                if not mentions or len(mentions) == 0:
                    print("[跳过] 群聊消息未@任何人")
                    return jsonify({
                        "message": "群聊消息未@机器人",
                        "success": False
                    })
                
                # 获取被@的用户名称
                mentioned_name = mentions[0].get('name', '')
                print(f"[群聊@信息] 被@的名称: {mentioned_name}")
                
                # 清除群聊消息中@聊天机器人携带类似@_user_1字眼的内容
                query = re.sub(r'@\w+', '', query).strip()
                print(f"[清理后的问题] {query}")
                
                # 检查是否@了机器人（支持多种机器人名称）
                bot_names = ["智能体机器人", "机器人小助手", "小助手"]
                if mentioned_name not in bot_names:
                    print(f"[跳过] 未@机器人，@的是: {mentioned_name}")
                    return jsonify({
                        "message": f"未@机器人，@的是 {mentioned_name}",
                        "success": False
                    })
                
                # 检查是否已经处理过这条消息
                if message_id in self.processed_messages:
                    print(f"[跳过] 消息 {message_id} 已处理过")
                    return jsonify({"success": False, "message": "消息已处理"})

                # 标记消息为已处理
                self.processed_messages.add(message_id)
                print(f"[开始处理] 群聊消息")

                # 获取用户信息
                user_info = self.feishu_user.get_user_info_by_id(
                    user_id=sender_id,
                    user_id_type="open_id"
                )
                formatted_info = self.feishu_user.format_user_info(user_info.get("data", {}))
                user_name = formatted_info.get("name", "未知用户")
                print(f"[用户信息] {user_name}")

                # 如果有文件内容，添加到查询中
                if file_content:
                    enhanced_query = f"{file_content}\n\n{query}"
                else:
                    enhanced_query = query

                messages = [
                    {"role": "system", "content": CHATBOT_PROMPT_DATA.get("description").format(
                                                    name=BOT_DATA["chat"].get("name"),
                                                    capabilities=BOT_DATA["chat"].get("capabilities"),
                                                    welcome_message=BOT_DATA["chat"].get("default_responses").get("welcome_message"),
                                                    unknown_command=BOT_DATA["chat"].get("default_responses").get("unknown_command"),
                                                    language_support=BOT_DATA["chat"].get("language_support"),
                                                    history=None,
                                                    query=enhanced_query,
                                                )},
                    {"role": "user", "content": enhanced_query}
                ]

                print(f"[调用模型] 开始生成回复...")
                # 调用模型，兼容两种类型
                if hasattr(self.chat_model, 'invoke') and 'ChatOpenAI' in str(type(self.chat_model)):
                    # LangChain ChatOpenAI
                    from langchain_core.messages import HumanMessage, SystemMessage
                    lc_messages = [
                        SystemMessage(content=messages[0]['content']),
                        HumanMessage(content=messages[1]['content'])
                    ]
                    response = self.chat_model.invoke(lc_messages).content
                else:
                    # OllamaClient
                    response = self.chat_model.invoke(messages=messages).content
                print(f"[模型回复] {response}")
                
                message_params = self.message_type_group(
                    query=query,
                    send_id = sender_id,
                    receive_id=chat_id,
                    receive_id_type="chat_id"
                ).handle(response)

                print(f"[发送消息] 开始发送...")
                send_result = self.send_message_tool.send_message(message_params=message_params)
                print(f"[发送结果] {send_result}")

                # 发送回复消息
                return jsonify({
                    "message": f"消息处理成功，来自用户 {user_name} 的消息已回复。",
                    "success": True
                })

        elif event_type == "im.message.message_read_v1":
            return jsonify({
                "message": "消息已读",
                "success": True
            })
