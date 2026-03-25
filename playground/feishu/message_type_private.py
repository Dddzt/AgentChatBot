"""
私聊消息格式化 —— 使用 Lark SDK 上传文件/图片/音频资源。
消除硬编码路径和 global 变量。
"""

import json
import os
import subprocess
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateImageRequest,
    CreateImageRequestBody,
    CreateFileRequest,
    CreateFileRequestBody,
)

from playground.feishu.lark_client import get_lark_client

logger = logging.getLogger(__name__)

MIME_MAP = {
    ".pdf": ("pdf", "application/pdf"),
    ".doc": ("doc", "application/msword"),
    ".docx": ("doc", "application/msword"),
    ".xls": ("xls", "application/vnd.ms-excel"),
    ".xlsx": ("xls", "application/vnd.ms-excel"),
    ".ppt": ("ppt", "application/vnd.ms-powerpoint"),
    ".pptx": ("ppt", "application/vnd.ms-powerpoint"),
    ".mp4": ("mp4", "video/mp4"),
}


class MessageTypePrivate:
    """格式化私聊回复消息"""

    def __init__(self, receive_id: str, receive_id_type: str):
        self.receive_id = receive_id
        self.receive_id_type = receive_id_type

    def handle(self, message: str) -> dict | None:
        _, ext = os.path.splitext(message)
        ext = ext.lower()

        if ext == ".png":
            image_key = _upload_image(message)
            return self._image_message(image_key)
        elif ext == ".mp3":
            opus_path = _convert_to_opus(message)
            file_key = _upload_file(opus_path, "opus")
            return self._audio_message(file_key)
        elif ext in MIME_MAP:
            file_key = _upload_file(message, MIME_MAP[ext][0])
            if ext == ".mp4":
                cover_key = _upload_image(message) if os.path.exists(message) else None
                return self._video_message(file_key, cover_key)
            return self._file_message(file_key)
        else:
            return self._text_message(message)

    # ── 各消息类型格式化 ──────────────────────────────────

    def _text_message(self, message: str) -> dict:
        return {
            "receive_id": self.receive_id,
            "content": json.dumps({"text": message}),
            "msg_type": "text",
            "receive_id_type": self.receive_id_type,
        }

    def _image_message(self, image_key: str | None) -> dict | None:
        if not image_key:
            return None
        return {
            "receive_id": self.receive_id,
            "content": json.dumps({"image_key": image_key}),
            "msg_type": "image",
            "receive_id_type": self.receive_id_type,
        }

    def _audio_message(self, audio_key: str | None) -> dict | None:
        if not audio_key:
            return None
        return {
            "receive_id": self.receive_id,
            "content": json.dumps({"file_key": audio_key}),
            "msg_type": "audio",
            "receive_id_type": self.receive_id_type,
        }

    def _file_message(self, file_key: str | None) -> dict | None:
        if not file_key:
            return None
        return {
            "receive_id": self.receive_id,
            "content": json.dumps({"file_key": file_key}),
            "msg_type": "file",
            "receive_id_type": self.receive_id_type,
        }

    def _video_message(self, file_key: str | None, image_key: str | None) -> dict | None:
        if not file_key:
            return None
        return {
            "receive_id": self.receive_id,
            "content": json.dumps({"file_key": file_key, "image_key": image_key}),
            "msg_type": "media",
            "receive_id_type": self.receive_id_type,
        }


# ── SDK 上传工具函数 ──────────────────────────────────────


def _upload_image(image_path: str) -> str | None:
    """通过 Lark SDK 上传图片"""
    try:
        with open(image_path, "rb") as f:
            image_data = f.read()

        request = (
            CreateImageRequest.builder()
            .request_body(
                CreateImageRequestBody.builder()
                .image_type("message")
                .image(image_data)
                .build()
            )
            .build()
        )
        response = get_lark_client().im.v1.image.create(request)

        if response.success():
            return response.data.image_key
        logger.error("[上传图片] 失败: code=%s, msg=%s", response.code, response.msg)
        return None
    except Exception as e:
        logger.exception("[上传图片] 异常: %s", e)
        return None


def _upload_file(file_path: str, file_type: str) -> str | None:
    """通过 Lark SDK 上传文件"""
    try:
        file_name = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            file_data = f.read()

        request = (
            CreateFileRequest.builder()
            .request_body(
                CreateFileRequestBody.builder()
                .file_type(file_type)
                .file_name(file_name)
                .file(file_data)
                .build()
            )
            .build()
        )
        response = get_lark_client().im.v1.file.create(request)

        if response.success():
            return response.data.file_key
        logger.error("[上传文件] 失败: code=%s, msg=%s", response.code, response.msg)
        return None
    except Exception as e:
        logger.exception("[上传文件] 异常: %s", e)
        return None


def _convert_to_opus(source_file: str) -> str:
    """将音频文件转换为 opus 格式（飞书语音消息要求）"""
    output_dir = os.path.join(os.path.dirname(source_file), "opus_cache")
    os.makedirs(output_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(source_file))[0]
    target = os.path.join(output_dir, f"{base_name}.opus")

    subprocess.run(
        ["ffmpeg", "-y", "-i", source_file, "-acodec", "libopus", "-ac", "1", "-ar", "16000", "-f", "opus", target],
        check=True,
        capture_output=True,
    )
    return target
