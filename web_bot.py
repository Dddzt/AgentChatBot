"""
Web Bot server for the browser-based chat UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable

import redis
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from werkzeug.utils import secure_filename

from config.config import CHATGPT_DATA, FILE_CONFIG, OLLAMA_DATA, REDIS_DATA, UPLOAD_FOLDER
from config.templates.data.bot import AGENT_BOT_PROMPT_DATA, BOT_DATA, CHATBOT_PROMPT_DATA
from server.client.model_factory import create_model_client
from tools.file_processor import file_processor


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(levelname)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            continue


configure_stdio()


APP_ROOT = Path(__file__).resolve().parent
UPLOAD_ROOT = (APP_ROOT / UPLOAD_FOLDER).resolve()
HTML_FILE = APP_ROOT / "web_page.html"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_SESSION_LIST = 100
VALID_MODES = {"chat", "agent"}
SESSION_LIST_KEY = "web_chat_sessions"
SESSION_KEY_PREFIX = "web_chat_history:"
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
PSEUDO_STREAM_CHUNK_SIZE = max(1, int(CHATGPT_DATA.get("stream_flush_chars", 24)))
PSEUDO_STREAM_DELAY_SECONDS = 0.02


app = Flask(__name__)
CORS(app)

UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_ROOT)
app.config["MAX_CONTENT_LENGTH"] = FILE_CONFIG.get("max_size", 50 * 1024 * 1024)

ALLOWED_EXTENSIONS = FILE_CONFIG.get(
    "allowed_extensions",
    {
        "image": {"png", "jpg", "jpeg", "gif", "bmp"},
        "document": {"txt", "md", "pdf", "doc", "docx"},
        "audio": {"mp3", "wav", "ogg", "flac", "m4a"},
        "video": {"mp4", "avi", "mov", "mkv", "wmv"},
    },
)


def init_redis_client() -> redis.Redis | None:
    try:
        client = redis.Redis(
            host=REDIS_DATA.get("host", "localhost"),
            port=REDIS_DATA.get("port", 6379),
            db=REDIS_DATA.get("db", 0),
            decode_responses=True,
        )
        client.ping()
        logger.info("Redis connected")
        return client
    except Exception as exc:
        logger.warning("Redis unavailable: %s", exc)
        return None


redis_client = init_redis_client()


def allowed_file(filename: str, file_type: str = "all") -> bool:
    if "." not in filename:
        return False

    ext = filename.rsplit(".", 1)[1].lower()
    if file_type == "all":
        return any(ext in extensions for extensions in ALLOWED_EXTENSIONS.values())
    return ext in ALLOWED_EXTENSIONS.get(file_type, set())


def sanitize_messages(messages: object) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant", "system"}:
            continue
        if not isinstance(content, str):
            continue

        normalized.append({"role": role, "content": content})

    return normalized


def build_history_text(messages: list[dict[str, str]]) -> str:
    recent_messages = messages[-3:] if len(messages) > 3 else messages
    history_parts: list[str] = []

    for message in recent_messages[:-1]:
        role_name = "用户" if message["role"] == "user" else "助手"
        history_parts.append(f"{role_name}: {message['content']}")

    return "\n\n".join(history_parts)


def build_current_query(messages: list[dict[str, str]], file_context: str | None = None) -> str:
    current_query = messages[-1]["content"] if messages else ""
    if file_context:
        current_query = f"{file_context}\n\n用户问题: {current_query}"
    return current_query


def build_model_messages(
    messages: list[dict[str, str]],
    mode: str = "chat",
    file_context: str | None = None,
) -> list[dict[str, str]]:
    history_text = build_history_text(messages)
    current_query = build_current_query(messages, file_context)

    bot_key = "agent" if mode == "agent" else "chat"
    bot_config = BOT_DATA[bot_key]
    prompt_data = AGENT_BOT_PROMPT_DATA if mode == "agent" else CHATBOT_PROMPT_DATA

    prompt_kwargs = {
        "name": bot_config.get("name"),
        "capabilities": bot_config.get("capabilities"),
        "welcome_message": bot_config.get("default_responses", {}).get("welcome_message"),
        "unknown_command": bot_config.get("default_responses", {}).get("unknown_command"),
        "language_support": bot_config.get("language_support"),
        "history": history_text if history_text else "无历史记录",
        "query": current_query,
    }

    if mode == "agent":
        prompt_kwargs.update(
            {
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user_id": "web_user",
                "user_name": "Web用户",
            }
        )

    system_prompt = prompt_data.get("description").format(**prompt_kwargs)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": current_query},
    ]


def chunk_text(text: str, chunk_size: int = PSEUDO_STREAM_CHUNK_SIZE) -> Iterable[str]:
    for index in range(0, len(text), chunk_size):
        yield text[index : index + chunk_size]


def sse_event(content: str = "", done: bool = False, event_type: str = "content") -> str:
    payload = {"type": event_type, "content": content, "done": done}
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        asyncio.set_event_loop(None)
        loop.close()


def iter_async_generator(async_gen) -> Iterable[object]:
    loop = asyncio.new_event_loop()
    aborted = False
    exhausted = False

    try:
        asyncio.set_event_loop(loop)

        while True:
            try:
                item = loop.run_until_complete(async_gen.__anext__())
            except StopAsyncIteration:
                exhausted = True
                break

            try:
                yield item
            except GeneratorExit:
                aborted = True
                raise
    finally:
        if not aborted and not exhausted:
            try:
                loop.run_until_complete(async_gen.aclose())
            except Exception:
                pass
        if not aborted:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
        asyncio.set_event_loop(None)
        loop.close()


async def invoke_base_model(
    messages: list[dict[str, str]],
    mode: str = "chat",
    file_context: str | None = None,
) -> str:
    model = create_model_client()
    return await model.ainvoke(build_model_messages(messages, mode, file_context))


def iter_base_model_chunks(
    messages: list[dict[str, str]],
    mode: str = "chat",
    file_context: str | None = None,
) -> Iterable[str]:
    model = create_model_client()
    model_name = getattr(model, "model", model.__class__.__name__)
    model_messages = build_model_messages(messages, mode, file_context)
    loop = asyncio.new_event_loop()
    stream = None

    try:
        asyncio.set_event_loop(loop)
        stream = model.astream(model_messages)

        while True:
            try:
                chunk = loop.run_until_complete(stream.__anext__())
            except StopAsyncIteration:
                break

            if chunk:
                yield chunk

    except Exception as exc:
        logger.warning(
            "Streaming failed for %s, using pseudo-stream fallback via ainvoke: %s",
            model_name,
            exc,
        )
        response = loop.run_until_complete(model.ainvoke(model_messages))
        for chunk in chunk_text(response):
            yield chunk
            time.sleep(PSEUDO_STREAM_DELAY_SECONDS)
    finally:
        if stream is not None:
            try:
                loop.run_until_complete(stream.aclose())
            except Exception:
                pass
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        asyncio.set_event_loop(None)
        loop.close()


async def run_agentbot(
    messages: list[dict[str, str]],
    file_context: str | None = None,
    file_path: str | None = None,
) -> str:
    current_query = build_current_query(messages, file_context)

    try:
        from server.bot.agent_bot import AgentBot
    except ModuleNotFoundError as exc:
        logger.warning("AgentBot dependencies missing, fallback to base mode: %s", exc)
        return await invoke_base_model(messages, mode="agent", file_context=file_context)

    try:
        agent_bot = AgentBot(
            query=current_query,
            user_id="web_user",
            user_name="Web用户",
        )
        return await agent_bot.run(
            user_name="Web用户",
            query=current_query,
            image_path=file_path
            if file_path and Path(file_path).suffix.lower() in IMAGE_EXTENSIONS
            else None,
            file_path=file_path
            if file_path and Path(file_path).suffix.lower() not in IMAGE_EXTENSIONS
            else None,
            user_id="web_user",
        )
    except ModuleNotFoundError as exc:
        logger.warning("AgentBot runtime dependencies missing, fallback to base mode: %s", exc)
        return await invoke_base_model(messages, mode="agent", file_context=file_context)


def iter_agentbot_events(
    messages: list[dict[str, str]],
    file_context: str | None = None,
    file_path: str | None = None,
) -> Iterable[dict[str, str]]:
    current_query = build_current_query(messages, file_context)
    yield {"type": "status", "content": "已收到请求，正在准备智能体..."}

    try:
        from server.bot.agent_bot import AgentBot
    except ModuleNotFoundError as exc:
        logger.warning("AgentBot dependencies missing, fallback to base mode: %s", exc)
        yield {"type": "status", "content": "智能体依赖缺失，正在切换到基础模型..."}
        response = run_async(invoke_base_model(messages, mode="agent", file_context=file_context))
        yield {"type": "content", "content": response}
        return

    try:
        agent_bot = AgentBot(
            query=current_query,
            user_id="web_user",
            user_name="Web用户",
        )
        stream = agent_bot.astream(
            user_name="Web用户",
            query=current_query,
            image_path=file_path
            if file_path and Path(file_path).suffix.lower() in IMAGE_EXTENSIONS
            else None,
            file_path=file_path
            if file_path and Path(file_path).suffix.lower() not in IMAGE_EXTENSIONS
            else None,
            user_id="web_user",
        )
        yield from iter_async_generator(stream)
    except ModuleNotFoundError as exc:
        logger.warning("AgentBot runtime dependencies missing, fallback to base mode: %s", exc)
        yield {"type": "status", "content": "智能体运行依赖缺失，正在切换到基础模型..."}
        response = run_async(invoke_base_model(messages, mode="agent", file_context=file_context))
        yield {"type": "content", "content": response}
    except Exception as exc:
        logger.warning("Agent streaming failed, fallback to pseudo-stream: %s", exc)
        yield {"type": "status", "content": "智能体流式输出异常，正在回退到普通模式..."}
        response = run_async(
            run_agentbot(messages, file_context=file_context, file_path=file_path)
        )
        for chunk in chunk_text(response):
            yield {"type": "content", "content": chunk}
            time.sleep(PSEUDO_STREAM_DELAY_SECONDS)


def make_client_file_path(file_path: Path) -> str:
    return file_path.relative_to(APP_ROOT).as_posix()


def resolve_uploaded_file_path(file_path: str | None) -> Path | None:
    if not file_path:
        return None

    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = (APP_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(UPLOAD_ROOT)
    except ValueError:
        return None

    if not candidate.exists() or not candidate.is_file():
        return None

    return candidate


def build_file_context(file_path: Path | None) -> str | None:
    if not file_path:
        return None

    if file_path.suffix.lower() in IMAGE_EXTENSIONS:
        logger.info("Analyzing image: %s", file_path)
        result = file_processor.process_image(str(file_path))
        if not result.get("success"):
            logger.error("Image processing failed: %s", result.get("error"))
            return f"[图片处理失败: {result.get('error', '未知错误')}]"

        vision_description = result.get("vision_description", "")
        if vision_description:
            return (
                "[用户上传了一张图片，以下是图片内容分析]\n"
                f"图片尺寸: {result.get('width')}x{result.get('height')}像素\n"
                f"图片内容描述: {vision_description}\n\n"
                "请根据以上图片信息回答用户的问题。"
            )

        basic_description = result.get("basic_description", "")
        logger.warning("Vision model returned empty result, using basic description")
        return (
            "[用户上传了一张图片]\n"
            f"图片尺寸: {result.get('width')}x{result.get('height')}像素\n"
            f"基础信息: {basic_description}\n\n"
            "请根据图片信息回答用户的问题。"
        )

    try:
        logger.info("Reading file content: %s", file_path)
        return file_processor.convert_to_text(str(file_path))
    except Exception as exc:
        logger.error("File processing failed: %s", exc)
        return f"[文件处理失败: {exc}]"


def build_preview(messages: list[dict[str, str]]) -> str:
    for message in messages:
        if message.get("role") == "user" and message.get("content"):
            return message["content"][:50]
    return "无内容"


def session_history_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def remove_session_summary(session_id: str) -> None:
    if not redis_client:
        return

    for session_data in redis_client.lrange(SESSION_LIST_KEY, 0, -1):
        try:
            session_info = json.loads(session_data)
        except json.JSONDecodeError:
            redis_client.lrem(SESSION_LIST_KEY, 1, session_data)
            continue

        if session_info.get("session_id") == session_id:
            redis_client.lrem(SESSION_LIST_KEY, 1, session_data)
            break


def load_session_summaries(prune_missing: bool = False) -> list[dict[str, object]]:
    if not redis_client:
        return []

    sessions: list[dict[str, object]] = []
    session_rows = redis_client.lrange(SESSION_LIST_KEY, 0, MAX_SESSION_LIST - 1)

    for session_data in session_rows:
        try:
            session_info = json.loads(session_data)
        except json.JSONDecodeError:
            redis_client.lrem(SESSION_LIST_KEY, 1, session_data)
            continue

        session_id = session_info.get("session_id")
        if not session_id:
            redis_client.lrem(SESSION_LIST_KEY, 1, session_data)
            continue

        if prune_missing and not redis_client.exists(session_history_key(str(session_id))):
            redis_client.lrem(SESSION_LIST_KEY, 1, session_data)
            continue

        sessions.append(session_info)

    return sessions


def save_conversation(session_id: str, messages: list[dict[str, str]], mode: str) -> None:
    if not redis_client:
        return

    try:
        conversation_data = {
            "session_id": session_id,
            "messages": messages,
            "mode": mode,
            "timestamp": datetime.now().isoformat(),
            "preview": build_preview(messages),
            "message_count": len(messages),
        }

        key = session_history_key(session_id)
        redis_client.setex(key, SESSION_TTL_SECONDS, json.dumps(conversation_data, ensure_ascii=False))

        remove_session_summary(session_id)

        session_summary = {
            "session_id": session_id,
            "timestamp": conversation_data["timestamp"],
            "preview": conversation_data["preview"],
            "mode": mode,
            "message_count": len(messages),
        }
        redis_client.lpush(SESSION_LIST_KEY, json.dumps(session_summary, ensure_ascii=False))
        redis_client.ltrim(SESSION_LIST_KEY, 0, MAX_SESSION_LIST - 1)
    except Exception as exc:
        logger.error("Failed to save conversation: %s", exc)


def save_uploaded_file(file_storage) -> Path:
    original_name = secure_filename(file_storage.filename or "")
    if not original_name:
        suffix = Path(file_storage.filename or "").suffix
        original_name = f"upload{suffix}"

    unique_name = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}_{original_name}"
    file_path = UPLOAD_ROOT / unique_name
    file_storage.save(file_path)
    return file_path


def validate_upload_request(expected_type: str = "all"):
    if "file" not in request.files:
        return None, (jsonify({"success": False, "error": "没有文件被上传"}), 400)

    file_storage = request.files["file"]
    if file_storage.filename == "":
        return None, (jsonify({"success": False, "error": "文件名为空"}), 400)

    if not allowed_file(file_storage.filename, expected_type):
        return None, (
            jsonify({"success": False, "error": f"不支持的文件类型: {file_storage.filename}"}),
            400,
        )

    return file_storage, None


def generate_stream_response(
    messages: list[dict[str, str]],
    mode: str,
    session_id: str,
    file_path: Path | None = None,
):
    file_context = build_file_context(file_path)
    assistant_chunks: list[str] = []

    save_conversation(session_id, messages, mode)

    try:
        if mode == "agent":
            for event in iter_agentbot_events(
                messages,
                file_context=file_context,
                file_path=str(file_path) if file_path else None,
            ):
                event_type = event.get("type", "content")
                content = event.get("content", "")
                if event_type == "content" and content:
                    assistant_chunks.append(content)
                yield sse_event(content, event_type=event_type)
        else:
            logger.info("Starting streaming response")
            for chunk in iter_base_model_chunks(messages, mode="chat", file_context=file_context):
                assistant_chunks.append(chunk)
                yield sse_event(chunk)

        assistant_message = "".join(assistant_chunks)
        if assistant_message:
            messages.append({"role": "assistant", "content": assistant_message})
            save_conversation(session_id, messages, mode)

        yield sse_event("", done=True)
        logger.info("Streaming response completed")
    except Exception as exc:
        logger.error("Streaming response failed: %s", exc)
        error_message = f"\n\n**错误**: {exc}"
        messages.append({"role": "assistant", "content": error_message})
        save_conversation(session_id, messages, mode)
        yield sse_event(error_message, done=True)


@app.route("/")
def index():
    if HTML_FILE.exists():
        return HTML_FILE.read_text(encoding="utf-8")
    return "<h1>Web Bot</h1><p>未找到 web_page.html 文件</p>", 404


@app.route("/upload/file", methods=["POST"])
def upload_file():
    file_storage, error_response = validate_upload_request("all")
    if error_response:
        return error_response

    try:
        file_path = save_uploaded_file(file_storage)
        logger.info("File uploaded: %s", file_path)

        result = file_processor.process_file(str(file_path))
        if not result.get("success"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": result.get("error", "文件处理失败"),
                        "file_path": make_client_file_path(file_path),
                    }
                ),
                500,
            )

        text_content = file_processor.convert_to_text(str(file_path)) or ""
        return jsonify(
            {
                "success": True,
                "file_path": make_client_file_path(file_path),
                "file_name": file_path.name,
                "file_type": result.get("type"),
                "file_info": result,
                "text_content": text_content[:500] + "..." if len(text_content) > 500 else text_content,
                "message": "文件上传且处理成功",
            }
        )
    except Exception as exc:
        logger.error("File upload failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/upload/image", methods=["POST"])
def upload_image():
    file_storage, error_response = validate_upload_request("image")
    if error_response:
        return error_response

    try:
        file_path = save_uploaded_file(file_storage)
        logger.info("Image uploaded: %s", file_path)

        width = 0
        height = 0
        try:
            from PIL import Image

            with Image.open(file_path) as image:
                width, height = image.size
        except Exception as exc:
            logger.warning("Failed to read image size: %s", exc)

        return jsonify(
            {
                "success": True,
                "file_path": make_client_file_path(file_path),
                "file_name": file_path.name,
                "file_type": "image",
                "width": width,
                "height": height,
                "message": "图片上传成功，发送消息时将自动分析图片内容",
            }
        )
    except Exception as exc:
        logger.error("Image upload failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    data = request.get_json(silent=True) or {}
    messages = sanitize_messages(data.get("messages", []))
    mode = data.get("mode", "chat")
    session_id = str(data.get("session_id") or f"session_{uuid.uuid4().hex}")
    file_path_value = data.get("file_path")

    if not messages:
        return jsonify({"success": False, "error": "消息内容不能为空"}), 400

    if mode not in VALID_MODES:
        return jsonify({"success": False, "error": f"不支持的模式: {mode}"}), 400

    file_path = None
    if file_path_value:
        file_path = resolve_uploaded_file_path(file_path_value)
        if file_path is None:
            return jsonify({"success": False, "error": "文件引用无效或已过期"}), 400

    return Response(
        stream_with_context(generate_stream_response(messages, mode, session_id, file_path)),
        mimetype="text/event-stream",
        headers=SSE_HEADERS,
    )


@app.route("/chat/history", methods=["GET"])
def get_history():
    if not redis_client:
        return jsonify({"success": False, "error": "Redis未连接"})

    try:
        sessions = load_session_summaries(prune_missing=True)

        return jsonify({"success": True, "sessions": sessions})
    except Exception as exc:
        logger.error("Failed to read history: %s", exc)
        return jsonify({"success": False, "error": str(exc)})


@app.route("/chat/history/<session_id>", methods=["GET", "DELETE"])
def manage_session_history(session_id: str):
    if not redis_client:
        return jsonify({"success": False, "error": "Redis未连接"})

    try:
        key = session_history_key(session_id)

        if request.method == "GET":
            data = redis_client.get(key)
            if data:
                return jsonify({"success": True, "session": json.loads(data)})
            remove_session_summary(session_id)
            return jsonify({"success": False, "error": "会话不存在"}), 404

        redis_client.delete(key)
        remove_session_summary(session_id)

        return jsonify({"success": True, "message": "历史记录已删除"})
    except Exception as exc:
        logger.error("Failed to manage history: %s", exc)
        return jsonify({"success": False, "error": str(exc)})


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify(
        {
            "status": "running",
            "timestamp": datetime.now().isoformat(),
            "redis": "connected" if redis_client else "disconnected",
            "ollama": OLLAMA_DATA.get("use", False),
            "chatgpt": CHATGPT_DATA.get("use", False),
        }
    )


if __name__ == "__main__":
    print("=" * 50)
    print("AgentChatBot Web starting...")
    print("=" * 50)

    if OLLAMA_DATA.get("use"):
        print(f"Ollama enabled: {OLLAMA_DATA.get('model')}")
    if CHATGPT_DATA.get("use"):
        print(f"ChatGPT compatible model enabled: {CHATGPT_DATA.get('model')}")
    if not OLLAMA_DATA.get("use") and not CHATGPT_DATA.get("use"):
        print("Warning: no model is enabled in config/config.py")

    if redis_client:
        print("Redis connected")
    else:
        print("Redis disconnected, history storage is unavailable")

    if HTML_FILE.exists():
        print("UI file found: web_page.html")
    else:
        print("Warning: web_page.html was not found")

    print("=" * 50)
    print("Server ready at http://127.0.0.1:5000")
    print("=" * 50)

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
