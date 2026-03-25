"""
飞书 Lark SDK 客户端单例。
全局共享同一个 Client 实例，避免各模块重复创建、重复鉴权。
"""

import lark_oapi as lark
from config.config import FEISHU_DATA

_client: lark.Client | None = None


def get_lark_client(log_level=lark.LogLevel.INFO) -> lark.Client:
    """获取全局唯一的 Lark Client 实例（线程安全由 SDK 内部保证）"""
    global _client
    if _client is None:
        _client = (
            lark.Client.builder()
            .app_id(FEISHU_DATA["app_id"])
            .app_secret(FEISHU_DATA["app_secret"])
            .log_level(log_level)
            .build()
        )
    return _client
