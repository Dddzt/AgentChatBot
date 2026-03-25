"""
飞书消息发送 —— 使用共享 Lark Client。
支持发送、编辑（用于流式输出效果）。
"""

import json
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    PatchMessageRequest,
    PatchMessageRequestBody,
)

from playground.feishu.lark_client import get_lark_client

logger = logging.getLogger(__name__)


class SendMessage:
    def __init__(self):
        self.client = get_lark_client()

    def send_message(self, message_params: dict | None) -> dict:
        """发送消息并返回 message_id（供后续 patch 使用）"""
        if not message_params:
            return {"success": False, "error": "message_params 为空"}

        request = (
            CreateMessageRequest.builder()
            .receive_id_type(message_params["receive_id_type"])
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(message_params["receive_id"])
                .msg_type(message_params["msg_type"])
                .content(message_params["content"])
                .build()
            )
            .build()
        )

        response = self.client.im.v1.message.create(request)

        if not response.success():
            error_msg = (
                f"发送失败: code={response.code}, "
                f"msg={response.msg}, log_id={response.get_log_id()}"
            )
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        message_id = response.data.message_id if response.data else None
        logger.info("[发送成功] message_id=%s", message_id)
        return {"success": True, "message_id": message_id}

    @staticmethod
    def _build_card_content(text: str) -> str:
        """构造一个仅含文本的简易卡片 JSON（lark_md 支持 Markdown + @用户）"""
        card = {
            "config": {"wide_screen_mode": True},
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": text},
                }
            ],
        }
        return json.dumps(card)

    def patch_message(self, message_id: str, text: str) -> bool:
        """编辑已发送的卡片消息内容（用于模拟流式输出）"""
        request = (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                PatchMessageRequestBody.builder()
                .content(self._build_card_content(text))
                .build()
            )
            .build()
        )

        response = self.client.im.v1.message.patch(request)

        if not response.success():
            logger.warning(
                "[Patch失败] code=%s msg=%s, ext=%s",
                response.code, response.msg,
                getattr(response, 'ext', ''),
            )
            return False
        return True
