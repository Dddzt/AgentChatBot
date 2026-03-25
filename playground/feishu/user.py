"""
飞书用户信息查询 —— 使用共享 Lark Client。
"""

import json
import logging

import lark_oapi as lark
from lark_oapi.api.contact.v3 import GetUserRequest

from playground.feishu.lark_client import get_lark_client
from config.config import FEISHU_DATA

logger = logging.getLogger(__name__)

GENDER_MAP = {1: "man", 0: "women"}


class FeishuUser:
    def __init__(self):
        self.client = get_lark_client()

    def get_user_info_by_id(
        self, user_id: str, user_id_type: str = "open_id"
    ) -> dict:
        request = (
            GetUserRequest.builder()
            .user_id(user_id)
            .user_id_type(user_id_type)
            .department_id_type("open_department_id")
            .build()
        )

        response = self.client.contact.v3.user.get(request)

        if not response.success():
            error_msg = (
                f"获取用户信息失败, code={response.code}, "
                f"msg={response.msg}, log_id={response.get_log_id()}"
            )
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        user_info = json.loads(lark.JSON.marshal(response.data))
        return {"success": True, "data": user_info}

    @staticmethod
    def format_user_info(user_info: dict) -> dict:
        user = user_info.get("user", {})
        return {
            "name": user.get("name", "N/A"),
            "gender": GENDER_MAP.get(user.get("gender"), "未知"),
            "mobile": user.get("mobile", "N/A"),
            "department_ids": ", ".join(user.get("department_ids", [])),
            "job_title": user.get("job_title", "N/A"),
            "is_tenant_manager": bool(user.get("is_tenant_manager")),
        }
