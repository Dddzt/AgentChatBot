"""
Web Bot - 基于Flask的Web界面聊天机器人
支持流式输出、历史记录管理、多模式切换
"""

import os
import json
import time
import uuid
import logging
import asyncio
from datetime import datetime
from flask import Flask, render_template_string, request, Response, jsonify, stream_with_context
from flask_cors import CORS
from werkzeug.utils import secure_filename
import redis

from config.config import CHATGPT_DATA, OLLAMA_DATA, REDIS_DATA, UPLOAD_FOLDER, FILE_CONFIG
from config.templates.data.bot import CHATBOT_PROMPT_DATA, AGENT_BOT_PROMPT_DATA, BOT_DATA
from tools.file_processor import file_processor

# 配置日志
logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s][%(levelname)s]: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 文件上传配置（从config读取）
MAX_FILE_SIZE = FILE_CONFIG.get('max_size', 50 * 1024 * 1024)
ALLOWED_EXTENSIONS = FILE_CONFIG.get('allowed_extensions', {
    'image': {'png', 'jpg', 'jpeg', 'gif', 'bmp'},
    'document': {'txt', 'md', 'pdf', 'doc', 'docx'},
    'audio': {'mp3', 'wav', 'ogg', 'flac', 'm4a'},
    'video': {'mp4', 'avi', 'mov', 'mkv', 'wmv'}
})

# 确保上传目录存在
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Redis 连接
try:
    redis_client = redis.StrictRedis(
        host=REDIS_DATA.get('host', 'localhost'),
        port=REDIS_DATA.get('port', 6379),
        db=REDIS_DATA.get('db', 0),
        decode_responses=False
    )
    redis_client.ping()
    logging.info("Redis连接成功")
except Exception as e:
    logging.warning(f"Redis连接失败: {e}")
    redis_client = None


def allowed_file(filename, file_type='all'):
    """检查文件类型是否允许"""
    if '.' not in filename:
        return False
    
    ext = filename.rsplit('.', 1)[1].lower()
    
    if file_type == 'all':
        # 检查所有允许的扩展名
        all_extensions = set()
        for exts in ALLOWED_EXTENSIONS.values():
            all_extensions.update(exts)
        return ext in all_extensions
    else:
        return ext in ALLOWED_EXTENSIONS.get(file_type, set())


def get_file_type(filename):
    """根据文件名获取文件类型"""
    if '.' not in filename:
        return 'unknown'
    
    ext = filename.rsplit('.', 1)[1].lower()
    
    for file_type, extensions in ALLOWED_EXTENSIONS.items():
        if ext in extensions:
            return file_type
    
    return 'unknown'


async def run_chatbot(messages, mode, file_context=None):
    """运行聊天机器人 - 只保留最近2条历史对话"""
    from langchain_openai import ChatOpenAI
    
    # 只保留最近的2条历史消息（即1轮对话：1条用户消息 + 1条助手回复）
    recent_messages = messages[-3:] if len(messages) > 3 else messages
    
    # 构建历史对话文本（只包含倒数第2、3条，不包含当前最新的用户消息）
    history_text = ""
    if len(recent_messages) > 1:
        for msg in recent_messages[:-1]:
            role_name = "用户" if msg["role"] == "user" else "助手"
            history_text += f"{role_name}: {msg['content']}\n\n"
    
    # 获取当前查询
    current_query = messages[-1]["content"] if messages else ""
    
    # 如果有文件上传，将文件信息添加到查询中
    if file_context:
        current_query = f"{file_context}\n\n用户问题: {current_query}"
    
    # 使用配置的模型
    if OLLAMA_DATA.get("use"):
        from server.client.loadmodel.Ollama.OllamaClient import OllamaClient
        model = OllamaClient()
    elif CHATGPT_DATA.get("use"):
        model = ChatOpenAI(
            api_key=CHATGPT_DATA.get("key"),
            base_url=CHATGPT_DATA.get("url"),
            model=CHATGPT_DATA.get("model")
        )
    else:
        return "请在config/config.py中配置OLLAMA_DATA或CHATGPT_DATA"
    
    # 构建完整的提示词（包含历史记录）
    system_prompt = CHATBOT_PROMPT_DATA.get("description").format(
        name=BOT_DATA["chat"].get("name"),
        capabilities=BOT_DATA["chat"].get("capabilities"),
        welcome_message=BOT_DATA["chat"].get("default_responses").get("welcome_message"),
        unknown_command=BOT_DATA["chat"].get("default_responses").get("unknown_command"),
        language_support=BOT_DATA["chat"].get("language_support"),
        history=history_text if history_text else "无历史记录",
        query=current_query,
    )
    
    # 调用模型生成回复
    messages_for_model = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": current_query}
    ]
    
    response = model.invoke(messages_for_model)
    return response.content if hasattr(response, 'content') else str(response)


async def run_agentbot(messages, mode, file_context=None, file_path=None):
    """运行智能体模式"""
    from server.bot.agent_bot import AgentBot
    
    current_query = messages[-1]["content"] if messages else ""
    
    # 如果有图片分析结果，将其添加到查询中
    if file_context:
        current_query = f"{file_context}\n\n用户问题: {current_query}"
        logging.info(f"智能体模式：已将图片分析结果添加到查询中")
    
    agent_bot = AgentBot(
        query=current_query,
        user_id="web_user",
        user_name="Web用户"
    )
    
    response = await agent_bot.run(
        user_name="Web用户",
        query=current_query,
        image_path=file_path if file_path and any(file_path.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']) else None,
        file_path=file_path if file_path and not any(file_path.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']) else None,
        user_id="web_user"
    )
    
    return response


def generate_stream_response(messages, mode="chat", file_path=None, user_query=None):
    """生成流式响应 - 真正的流式输出，支持图片延迟分析"""
    try:
        file_context = None
        
        # 如果有图片文件，在发送时调用视觉模型分析
        if file_path and os.path.exists(file_path):
            # 判断文件类型
            ext = os.path.splitext(file_path)[1].lower()
            image_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp']
            
            if ext in image_extensions:
                # 图片文件：调用视觉模型分析
                logging.info(f"正在分析图片: {file_path}")
                
                try:
                    result = file_processor.process_image(file_path)
                    if result.get('success'):
                        vision_desc = result.get('vision_description', '')
                        if vision_desc:
                            file_context = f"[用户上传了一张图片，以下是图片内容分析]\n图片尺寸: {result.get('width')}x{result.get('height')}像素\n图片内容描述: {vision_desc}\n\n请根据以上图片信息回答用户的问题。"
                            logging.info(f"图片分析成功，描述长度: {len(vision_desc)}")
                        else:
                            # 如果视觉模型没有返回结果，使用基础描述
                            basic_desc = result.get('basic_description', '')
                            file_context = f"[用户上传了一张图片]\n图片尺寸: {result.get('width')}x{result.get('height')}像素\n基础信息: {basic_desc}\n\n请根据图片信息回答用户的问题。"
                            logging.warning("视觉模型未返回分析结果，使用基础描述")
                    else:
                        file_context = f"[图片处理失败: {result.get('error', '未知错误')}]"
                        logging.error(f"图片处理失败: {result.get('error')}")
                except Exception as e:
                    logging.error(f"图片分析异常: {e}")
                    file_context = f"[图片分析失败: {str(e)}]"
            else:
                # 非图片文件：直接读取文本内容
                try:
                    file_context = file_processor.convert_to_text(file_path)
                    logging.info(f"文件处理成功: {file_path}")
                except Exception as e:
                    file_context = f"[文件处理失败: {str(e)}]"
                    logging.error(f"文件处理失败: {e}")
        
        # 根据模式选择Bot
        if mode == "agent":
            if CHATGPT_DATA.get("use"):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                # 传递file_context和file_path给智能体
                response = loop.run_until_complete(run_agentbot(messages, mode, file_context, file_path))
                loop.close()
                # Agent模式暂时使用模拟流式（逐词输出）
                if response:
                    words = response.split(' ')
                    for word in words:
                        yield "data: " + json.dumps({"content": word + ' ', "done": False}, ensure_ascii=False) + "\n\n"
                        time.sleep(0.02)
            else:
                yield "data: " + json.dumps({"content": "智能体模式需要配置CHATGPT_DATA", "done": True}, ensure_ascii=False) + "\n\n"
                return
        else:
            # 聊天模式 - 使用真正的流式输出
            from langchain_openai import ChatOpenAI
            
            # 只保留最近的2条历史消息
            recent_messages = messages[-3:] if len(messages) > 3 else messages
            
            # 构建历史对话文本
            history_text = ""
            if len(recent_messages) > 1:
                for msg in recent_messages[:-1]:
                    role_name = "用户" if msg["role"] == "user" else "助手"
                    history_text += f"{role_name}: {msg['content']}\n\n"
            
            # 获取当前查询
            current_query = messages[-1]["content"] if messages else ""
            
            # 如果有文件上传，将文件信息添加到查询中
            if file_context:
                current_query = f"{file_context}\n\n用户问题: {current_query}"
            
            # 使用配置的模型
            if OLLAMA_DATA.get("use"):
                from server.client.loadmodel.Ollama.OllamaClient import OllamaClient
                model = OllamaClient()
                # Ollama模型暂时使用同步方式
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                response = loop.run_until_complete(run_chatbot(messages, mode, file_context))
                loop.close()
                # 逐词输出
                if response:
                    words = response.split(' ')
                    for word in words:
                        yield "data: " + json.dumps({"content": word + ' ', "done": False}, ensure_ascii=False) + "\n\n"
                        time.sleep(0.02)
            elif CHATGPT_DATA.get("use"):
                # 使用ChatGPT/阿里云百炼的流式API
                model = ChatOpenAI(
                    api_key=CHATGPT_DATA.get("key"),
                    base_url=CHATGPT_DATA.get("url"),
                    model=CHATGPT_DATA.get("model"),
                    streaming=True  # 启用流式
                )
                
                # 构建完整的提示词
                system_prompt = CHATBOT_PROMPT_DATA.get("description").format(
                    name=BOT_DATA["chat"].get("name"),
                    capabilities=BOT_DATA["chat"].get("capabilities"),
                    welcome_message=BOT_DATA["chat"].get("default_responses").get("welcome_message"),
                    unknown_command=BOT_DATA["chat"].get("default_responses").get("unknown_command"),
                    language_support=BOT_DATA["chat"].get("language_support"),
                    history=history_text if history_text else "无历史记录",
                    query=current_query,
                )
                
                messages_for_model = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": current_query}
                ]
                
                # 真正的流式输出
                logging.info("开始流式生成回复...")
                for chunk in model.stream(messages_for_model):
                    if hasattr(chunk, 'content') and chunk.content:
                        yield "data: " + json.dumps({"content": chunk.content, "done": False}, ensure_ascii=False) + "\n\n"
            else:
                yield "data: " + json.dumps({"content": "请在config/config.py中配置OLLAMA_DATA或CHATGPT_DATA", "done": True}, ensure_ascii=False) + "\n\n"
                return
        
        yield "data: " + json.dumps({"content": "", "done": True}, ensure_ascii=False) + "\n\n"
        logging.info("流式回复生成完成")
        
    except Exception as e:
        logging.error(f"流式生成错误: {e}")
        yield "data: " + json.dumps({"content": f"\n\n**错误**: {str(e)}", "done": True}, ensure_ascii=False) + "\n\n"


def save_conversation(session_id, messages, mode):
    """保存对话到历史"""
    if not redis_client:
        return
    
    try:
        preview = messages[0]['content'][:50] if messages else '无内容'
        conversation_data = {
            'session_id': session_id,
            'messages': messages,
            'mode': mode,
            'timestamp': datetime.now().isoformat(),
            'preview': preview,
            'message_count': len(messages)
        }
        
        # Redis存储（保存7天）
        key = f"web_chat_history:{session_id}"
        redis_client.setex(key, 86400 * 7, json.dumps(conversation_data, ensure_ascii=False))
        
        # 更新会话列表（先删除旧的同session_id记录，避免重复）
        session_list_key = "web_chat_sessions"
        
        # 查找并删除已存在的同session_id记录
        existing_sessions = redis_client.lrange(session_list_key, 0, -1)
        for existing_session in existing_sessions:
            try:
                session_data = json.loads(existing_session.decode('utf-8'))
                if session_data.get('session_id') == session_id:
                    redis_client.lrem(session_list_key, 1, existing_session)
                    break
            except:
                continue
        
        # 添加新的会话记录
        session_info = {
            'session_id': session_id,
            'timestamp': conversation_data['timestamp'],
            'preview': preview,
            'mode': mode,
            'message_count': len(messages)
        }
        redis_client.lpush(session_list_key, json.dumps(session_info, ensure_ascii=False))
        redis_client.ltrim(session_list_key, 0, 99)  # 只保留最近100条
        
    except Exception as e:
        logging.error(f"保存对话历史失败: {e}")


@app.route('/')
def index():
    """主页"""
    html_file = 'web_page.html'
    if os.path.exists(html_file):
        with open(html_file, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        return "<h1>Web Bot</h1><p>未找到test_page.html文件</p>", 404


@app.route('/upload/file', methods=['POST'])
def upload_file():
    """文件上传接口（支持文档、音频、视频等）"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '没有文件被上传'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'success': False, 'error': '文件名为空'}), 400
        
        if not allowed_file(file.filename, 'all'):
            return jsonify({'success': False, 'error': f'不支持的文件类型: {file.filename}'}), 400
        
        # 保存文件
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        file.save(file_path)
        logging.info(f"文件上传成功: {file_path}")
        
        # 处理文件
        result = file_processor.process_file(file_path)
        
        if result.get('success'):
            # 生成文本内容（供大模型使用）
            text_content = file_processor.convert_to_text(file_path)
            
            return jsonify({
                'success': True,
                'file_path': file_path,
                'file_name': unique_filename,
                'file_type': result.get('type'),
                'file_info': result,
                'text_content': text_content[:500] + '...' if len(text_content) > 500 else text_content,  # 返回前500字符预览
                'message': '文件上传且处理成功'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', '文件处理失败'),
                'file_path': file_path
            }), 500
            
    except Exception as e:
        logging.error(f"文件上传失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/upload/image', methods=['POST'])
def upload_image():
    """图片上传接口 - 只保存文件，不调用视觉模型（延迟到发送消息时处理）"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '没有图片被上传'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'success': False, 'error': '文件名为空'}), 400
        
        if not allowed_file(file.filename, 'image'):
            return jsonify({'success': False, 'error': f'不支持的图片类型: {file.filename}'}), 400
        
        # 保存图片
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        file.save(file_path)
        logging.info(f"图片上传成功: {file_path}")
        
        # 只获取图片基础信息，不调用视觉模型（延迟处理）
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                width, height = img.size
        except Exception as e:
            width, height = 0, 0
            logging.warning(f"无法获取图片尺寸: {e}")
        
        return jsonify({
            'success': True,
            'file_path': file_path,
            'file_name': unique_filename,
            'file_type': 'image',
            'width': width,
            'height': height,
            'message': '图片上传成功，发送消息时将自动分析图片内容'
        })
            
    except Exception as e:
        logging.error(f"图片上传失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/chat/stream', methods=['POST'])
def chat_stream():
    """流式聊天接口"""
    try:
        data = request.get_json()
        messages = data.get('messages', [])
        mode = data.get('mode', 'chat')
        session_id = data.get('session_id', str(uuid.uuid4()))
        file_path = data.get('file_path')  # 文件路径（可选）
        
        # 保存对话到历史
        save_conversation(session_id, messages, mode)
        
        # 直接传递file_path，延迟到流式响应时处理图片/文件
        return Response(
            stream_with_context(generate_stream_response(messages, mode, file_path)),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no'
            }
        )
    except Exception as e:
        logging.error(f"聊天接口错误: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/chat/history', methods=['GET'])
def get_history():
    """获取历史会话列表"""
    if not redis_client:
        return jsonify({'success': False, 'error': 'Redis未连接'})
    
    try:
        session_list_key = "web_chat_sessions"
        sessions_data = redis_client.lrange(session_list_key, 0, 99)
        
        sessions = []
        for session_data in sessions_data:
            try:
                session_info = json.loads(session_data.decode('utf-8'))
                sessions.append(session_info)
            except:
                continue
        
        return jsonify({'success': True, 'sessions': sessions})
    except Exception as e:
        logging.error(f"获取历史失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/chat/history/<session_id>', methods=['GET', 'DELETE'])
def manage_session_history(session_id):
    """管理指定会话的历史记录（查询/删除）"""
    if not redis_client:
        return jsonify({'success': False, 'error': 'Redis未连接'})
    
    try:
        if request.method == 'GET':
            # 从Redis获取
            key = f"web_chat_history:{session_id}"
            data = redis_client.get(key)
            if data:
                session_data = json.loads(data.decode('utf-8'))
                return jsonify({'success': True, 'session': session_data})
            return jsonify({'success': False, 'error': '会话不存在'}), 404
        
        elif request.method == 'DELETE':
            # 从Redis删除
            key = f"web_chat_history:{session_id}"
            redis_client.delete(key)
            
            # 从会话列表中移除
            session_list_key = "web_chat_sessions"
            sessions_data = redis_client.lrange(session_list_key, 0, -1)
            
            for session_data in sessions_data:
                try:
                    session_info = json.loads(session_data.decode('utf-8'))
                    if session_info.get('session_id') == session_id:
                        redis_client.lrem(session_list_key, 1, session_data)
                        break
                except:
                    continue
            
            return jsonify({'success': True, 'message': '历史记录已删除'})
    except Exception as e:
        logging.error(f"管理历史记录失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/health', methods=['GET'])
def health_check():
    """健康检查"""
    status = {
        'status': 'running',
        'timestamp': datetime.now().isoformat(),
        'redis': 'connected' if redis_client else 'disconnected',
        'ollama': OLLAMA_DATA.get('use', False),
        'chatgpt': CHATGPT_DATA.get('use', False)
    }
    return jsonify(status)


if __name__ == '__main__':
    print("=" * 50)
    print("AgentChatBot Web版本启动中...")
    print("=" * 50)
    
    # 检查模型配置
    if OLLAMA_DATA.get("use"):
        print(f"✓ 使用Ollama模型: {OLLAMA_DATA.get('model')}")
    if CHATGPT_DATA.get("use"):
        print(f"✓ 使用ChatGPT模型: {CHATGPT_DATA.get('model')}")
    if not OLLAMA_DATA.get("use") and not CHATGPT_DATA.get("use"):
        print("⚠ 警告: 没有启用任何模型，请检查config/config.py配置")
    
    # 检查Redis
    if redis_client:
        print(f"✓ Redis连接成功")
    else:
        print("⚠ Redis未连接，历史记录功能将不可用")
    
    # 检查HTML文件
    if os.path.exists('web_page.html'):
        print(f"✓ 找到界面文件: web_page.html")
    else:
        print("⚠ 未找到test_page.html文件")
    
    print("=" * 50)
    print("服务器启动成功！")
    print("访问地址: http://127.0.0.1:5000")
    print("按 Ctrl+C 停止服务")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
