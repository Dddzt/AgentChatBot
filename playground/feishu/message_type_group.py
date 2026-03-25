"""
群聊消息格式化 —— 使用 Lark SDK 上传图片资源。
"""

import json
import os
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody

from playground.feishu.lark_client import get_lark_client

logger = logging.getLogger(__name__)


class MessageTypeGroup:
    """格式化群聊回复消息"""

    def __init__(self, query: str, send_id: str, receive_id: str, receive_id_type: str):
        self.query = query
        self.send_id = send_id
        self.receive_id = receive_id
        self.receive_id_type = receive_id_type

    def handle(self, message: str) -> dict | None:
        _, ext = os.path.splitext(message)
        if ext.lower() == ".png":
            image_key = upload_image(message)
            return self._image_message(image_key)
        return self._text_message(message)

    def _text_message(self, message: str) -> dict:
        return {
            "receive_id": self.receive_id,
            "content": json.dumps(
                {"text": f'<at user_id="{self.send_id}"></at> {message}'}
            ),
            "msg_type": "text",
            "receive_id_type": self.receive_id_type,
        }

    def _image_message(self, image_key: str | None) -> dict | None:
        if not image_key:
            return None
        return {
            "receive_id": self.receive_id,
            "content": json.dumps(
                {
                    "zh_cn": {
                        "title": "生成的图像结果",
                        "content": [
                            [
                                {"tag": "at", "user_id": self.send_id, "style": ["bold"]},
                                {"tag": "text", "text": "描述信息:", "style": ["bold"]},
                                {"tag": "text", "text": self.query, "style": ["underline"]},
                            ],
                            [{"tag": "img", "image_key": image_key}],
                        ],
                    }
                }
            ),
            "msg_type": "post",
            "receive_id_type": self.receive_id_type,
        }


def upload_image(image_path: str) -> str | None:
    """通过 Lark SDK 上传图片，返回 image_key"""
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
