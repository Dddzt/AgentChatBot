"""
飞书消息处理器 —— 异步版本。
通过 BaseModelClient 统一调用模型，消除私聊/群聊的重复代码。
"""

import json
import re
import os
import time
import logging
import asyncio
from datetime import datetime

from lark_oapi.api.im.v1 import GetMessageResourceRequest

from config.config import DOWNLOAD_ADDRESS
from config.templates.data.bot import (
    CHATBOT_PROMPT_DATA,
    AGENT_BOT_PROMPT_DATA,
    BOT_DATA,
)
from playground.feishu.lark_client import get_lark_client
from playground.feishu.message_type_group import MessageTypeGroup
from playground.feishu.message_type_private import MessageTypePrivate
from playground.feishu.send_message import SendMessage
from server.client.base_client import BaseModelClient
from server.client.model_factory import create_model_client
from tools.file_processor import file_processor

logger = logging.getLogger(__name__)

BOT_NAMES = {"智能体机器人", "机器人小助手", "小助手"}

_FILE_TYPE_DIR_MAP = {
    "image": ("image", "downloads/image", ".png"),
    "audio": ("audio", "downloads/audio", ".opus"),
    "video": ("vidio", "downloads/vidio", ".mp4"),
}


class FeishuMessageHandler:
    def __init__(self, feishu_user):
        self.feishu_user = feishu_user
        self.model: BaseModelClient = create_model_client()
        self.processed_messages: set[str] = set()
        self.send_message_tool = SendMessage()

    # ── 文件下载（使用共享 Lark Client） ──────────────────

    def download_feishu_file(
        self,
        file_key: str,
        file_type: str,
        message_id: str | None = None,
        file_name: str | None = None,
    ) -> str | None:
        try:
            cfg_key, default_dir, ext = _FILE_TYPE_DIR_MAP.get(
                file_type, ("file", "downloads/file", "")
            )
            save_dir = DOWNLOAD_ADDRESS.get(cfg_key, default_dir)
            if not file_name:
                file_name = f"{file_type}_{file_key[:20]}{ext}"

            os.makedirs(save_dir, exist_ok=True)
            file_path = os.path.join(save_dir, file_name)

            client = get_lark_client()

            if not message_id:
                logger.warning("[文件下载] 缺少 message_id")
                return None

            # 用户发来的消息附件（图片/文件/音频/视频）统一通过
            # Get Message Resource 接口下载，GetImage 接口仅适用于机器人自己上传的图片
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(file_key)
                .type(file_type)
                .build()
            )
            response = client.im.v1.message_resource.get(request)

            if not response.success():
                logger.error(
                    "[文件下载] 失败: code=%s msg=%s", response.code, response.msg
                )
                return None

            with open(file_path, "wb") as f:
                f.write(response.raw.content)
            logger.info("[文件下载] 成功: %s", file_path)
            return file_path

        except Exception as e:
            logger.exception("[文件下载] 异常: %s", e)
            return None

    # ── 消息内容解析 ─────────────────────────────────────

    @staticmethod
    def _parse_message_content(
        message: dict, message_type: str, message_id: str, download_fn
    ) -> tuple[str, str]:
        """返回 (query, file_content)"""
        raw_content = message.get("content", "{}")

        # content 可能是 JSON 字符串，也可能已经被 SDK 序列化为 dict
        if isinstance(raw_content, dict):
            content_json = raw_content
        else:
            try:
                content_json = json.loads(raw_content)
            except (json.JSONDecodeError, TypeError):
                content_json = {}

        logger.info("[解析] message_type=%s, content_json=%s", message_type, content_json)

        if message_type == "text":
            return content_json.get("text", ""), ""

        type_handlers = {
            "image": ("image_key", "image", "[用户发送了图片，请根据图片内容回答问题]"),
            "file": ("file_key", "file", None),
            "audio": ("file_key", "audio", "[用户发送了语音，请根据语音信息回答问题]"),
            "media": ("file_key", "video", "[用户发送了视频，请根据视频信息回答问题]"),
        }

        cfg = type_handlers.get(message_type)
        if not cfg:
            logger.warning("[解析] 不支持的消息类型: %s", message_type)
            return f"[不支持的消息类型: {message_type}]", ""

        key_field, ft, default_query = cfg
        file_key = content_json.get(key_field, "")
        file_name = content_json.get("file_name")

        file_path = download_fn(file_key, ft, message_id, file_name)
        if not file_path:
            return f"[{ft}下载失败]", ""

        file_content = file_processor.convert_to_text(file_path)
        if default_query is None:
            default_query = f"[用户发送了文件: {file_name or ft}，请根据文件内容回答问题]"
        return default_query, file_content

    # ── 流式模型调用 + 逐步更新消息 ─────────────────────

    STREAM_CHUNK_SIZE = 90
    STREAM_PUNCTUATION_CHUNK_SIZE = 24
    STREAM_CODE_BLOCK_CHUNK_SIZE = 120
    STREAM_INTERVAL = 0.8
    STREAM_PUNCTUATION = "，。！？；：,.!?;:\n"

    @staticmethod
    def _is_in_code_block(text: str) -> bool:
        return text.count("```") % 2 == 1

    def _should_patch_stream(
        self,
        pending_text: str,
        full_text: str,
        now: float,
        last_patch_time: float,
    ) -> bool:
        pending_len = len(pending_text)
        if pending_len <= 0:
            return False

        time_exceeded = now - last_patch_time >= self.STREAM_INTERVAL
        stripped = pending_text.rstrip()
        hits_boundary = bool(stripped) and stripped[-1] in self.STREAM_PUNCTUATION

        if self._is_in_code_block(full_text):
            return (
                pending_len >= self.STREAM_CODE_BLOCK_CHUNK_SIZE
                or ("\n" in pending_text and pending_len >= self.STREAM_PUNCTUATION_CHUNK_SIZE)
                or (time_exceeded and pending_len >= self.STREAM_PUNCTUATION_CHUNK_SIZE)
            )

        return (
            pending_len >= self.STREAM_CHUNK_SIZE
            or (hits_boundary and pending_len >= self.STREAM_PUNCTUATION_CHUNK_SIZE)
            or (time_exceeded and pending_len >= self.STREAM_PUNCTUATION_CHUNK_SIZE)
        )

    async def _patch_stream_message(
        self,
        message_id: str,
        text: str,
        last_display: str,
    ) -> str:
        if not text or text == last_display:
            return last_display

        ok = await asyncio.to_thread(
            self.send_message_tool.patch_message,
            message_id,
            text,
        )
        return text if ok else last_display

    async def _stream_to_message(
        self, system_prompt: str, user_query: str, message_id: str,
        prefix: str = "", suffix: str = "",
    ) -> str:
        """
        流式调用模型，通过 PatchMessage 逐步更新已发送的消息内容。
        prefix/suffix 用于群聊场景在文本前后包裹 @用户 标签。
        返回完整的模型回复文本。
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query},
        ]

        buffer = ""
        pending = ""
        last_display = ""
        last_patch_time = time.time()

        async for token in self.model.astream(messages):
            buffer += token
            pending += token
            now = time.time()
            should_patch = self._should_patch_stream(
                pending,
                buffer,
                now,
                last_patch_time,
            )
            if should_patch and buffer:
                display = f"{prefix}{buffer}{suffix}" if prefix or suffix else buffer
                last_display = await self._patch_stream_message(
                    message_id,
                    display,
                    last_display,
                )
                pending = ""
                last_patch_time = now

        # 最终更新，确保完整内容显示
        if buffer:
            display = f"{prefix}{buffer}{suffix}" if prefix or suffix else buffer
            await self._patch_stream_message(message_id, display, last_display)

        return buffer

    def _send_placeholder(self, receive_id: str, receive_id_type: str,
                          text: str = "正在思考...") -> str | None:
        """发送卡片占位消息，返回 message_id（PatchMessage 仅支持卡片类型）"""
        card_content = SendMessage._build_card_content(text)
        params = {
            "receive_id": receive_id,
            "receive_id_type": receive_id_type,
            "msg_type": "interactive",
            "content": card_content,
        }
        result = self.send_message_tool.send_message(params)
        return result.get("message_id") if result.get("success") else None

    # ── 核心消息处理入口 ─────────────────────────────────

    async def handle_message(self, event_data: dict, event_type: str):
        logger.info("[handle_message] event_type=%s", event_type)

        if event_type == "im.message.message_read_v1":
            return

        if event_type != "im.message.receive_v1":
            return

        message = event_data.get("message", {})
        message_id = message.get("message_id")
        chat_type = message.get("chat_type")
        message_type = message.get("message_type")
        sender_id = (
            event_data.get("sender", {}).get("sender_id", {}).get("open_id")
        )

        if message_id in self.processed_messages:
            logger.info("[跳过] 消息 %s 已处理", message_id)
            return
        self.processed_messages.add(message_id)

        query, file_content = self._parse_message_content(
            message, message_type, message_id, self.download_feishu_file
        )
        enhanced_query = f"{file_content}\n\n{query}" if file_content else query
        logger.info("[用户消息] %s", query)

        if chat_type == "p2p":
            await self._handle_private(sender_id, enhanced_query)
        elif chat_type == "group":
            await self._handle_group(message, sender_id, query, enhanced_query)

    # ── 私聊处理 ─────────────────────────────────────────

    async def _handle_private(self, sender_id: str, enhanced_query: str):
        try:
            user_name = self._get_user_name(sender_id)
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            system_prompt = AGENT_BOT_PROMPT_DATA["description"].format(
                name=BOT_DATA["agent"]["name"],
                capabilities=BOT_DATA["agent"]["capabilities"],
                welcome_message=BOT_DATA["agent"]["default_responses"]["welcome_message"],
                unknown_command=BOT_DATA["agent"]["default_responses"]["unknown_command"],
                language_support=BOT_DATA["agent"]["language_support"],
                current_time=current_time,
                history=None,
                query=enhanced_query,
                user_name=user_name,
                user_id=sender_id,
            )

            # 1. 先发占位消息
            msg_id = self._send_placeholder(sender_id, "open_id")
            if not msg_id:
                logger.error("[错误] 占位消息发送失败，回退到一次性发送")
                response = await self.model.ainvoke([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": enhanced_query},
                ])
                params = MessageTypePrivate(
                    receive_id=sender_id, receive_id_type="open_id"
                ).handle(response)
                self.send_message_tool.send_message(message_params=params)
                return

            # 2. 流式输出，逐步 patch 消息
            response = await self._stream_to_message(
                system_prompt, enhanced_query, msg_id
            )
            logger.info("[模型回复] %s", response[:100])

        except Exception as e:
            logger.exception("[错误] 处理私聊消息失败: %s", e)

    # ── 群聊处理 ─────────────────────────────────────────

    async def _handle_group(
        self,
        message: dict,
        sender_id: str,
        raw_query: str,
        enhanced_query: str,
    ):
        chat_id = message.get("chat_id")
        mentions = message.get("mentions", [])

        if not mentions:
            return

        mentioned_name = mentions[0].get("name", "")
        if mentioned_name not in BOT_NAMES:
            logger.info("[跳过] 未@机器人，@的是: %s", mentioned_name)
            return

        clean_query = re.sub(r"@\w+", "", raw_query).strip()
        enhanced_query = re.sub(r"@\w+", "", enhanced_query).strip()

        at_prefix = f'<at user_id="{sender_id}"></at> '

        try:
            user_name = self._get_user_name(sender_id)

            system_prompt = CHATBOT_PROMPT_DATA["description"].format(
                name=BOT_DATA["chat"]["name"],
                capabilities=BOT_DATA["chat"]["capabilities"],
                welcome_message=BOT_DATA["chat"]["default_responses"]["welcome_message"],
                unknown_command=BOT_DATA["chat"]["default_responses"]["unknown_command"],
                language_support=BOT_DATA["chat"]["language_support"],
                history=None,
                query=enhanced_query,
            )

            # 1. 先发占位消息（群聊带 @用户）
            msg_id = self._send_placeholder(
                chat_id, "chat_id", text=f"{at_prefix}正在思考..."
            )
            if not msg_id:
                logger.error("[错误] 占位消息发送失败，回退到一次性发送")
                response = await self.model.ainvoke([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": enhanced_query},
                ])
                params = MessageTypeGroup(
                    query=clean_query, send_id=sender_id,
                    receive_id=chat_id, receive_id_type="chat_id",
                ).handle(response)
                self.send_message_tool.send_message(message_params=params)
                return

            # 2. 流式输出，每次 patch 都保留 @用户 前缀
            response = await self._stream_to_message(
                system_prompt, enhanced_query, msg_id, prefix=at_prefix
            )
            logger.info("[模型回复] %s", response[:100])

        except Exception as e:
            logger.exception("[错误] 处理群聊消息失败: %s", e)

    # ── 工具方法 ─────────────────────────────────────────

    def _get_user_name(self, sender_id: str) -> str:
        user_info = self.feishu_user.get_user_info_by_id(
            user_id=sender_id, user_id_type="open_id"
        )
        formatted = self.feishu_user.format_user_info(user_info.get("data", {}))
        return formatted.get("name", "未知用户")
