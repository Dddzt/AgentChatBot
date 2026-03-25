"""
飞书机器人服务入口 —— 基于 FastAPI + Lark SDK EventDispatcher。
使用官方 SDK 处理事件订阅（自动完成加解密与签名校验），
废弃手动 AES 解密逻辑。
"""

import sys
import os
import logging
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1, P2ImMessageMessageReadV1
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config.config import FEISHU_DATA
from playground.feishu.feishu_message_handler import FeishuMessageHandler
from playground.feishu.user import FeishuUser

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 全局实例 ──────────────────────────────────────────────
feishu_user = FeishuUser()
handler = FeishuMessageHandler(feishu_user)


# ── Lark SDK 事件回调 ────────────────────────────────────
def on_message_receive(data: P2ImMessageReceiveV1) -> None:
    """
    SDK 事件回调（同步函数，SDK 要求）。
    uvicorn 已有运行中的事件循环，不能在同一线程再 run_until_complete，
    因此在独立线程中用 asyncio.run() 执行异步 handler。
    副作用：回调瞬间返回，飞书能快速收到 200，处理在后台完成。
    """
    try:
        event = data.event
        header = data.header
        event_type = header.event_type if header else "unknown"
        logger.info("[事件回调] event_type=%s", event_type)

        msg = event.message
        sender = event.sender

        mentions_list = []
        if msg.mentions:
            for m in msg.mentions:
                mentions_list.append({
                    "key": getattr(m, "key", ""),
                    "name": getattr(m, "name", ""),
                })

        event_dict = {
            "message": {
                "message_id": msg.message_id,
                "chat_type": msg.chat_type,
                "message_type": msg.message_type,
                "content": msg.content,
                "chat_id": msg.chat_id,
                "mentions": mentions_list,
            },
            "sender": {
                "sender_id": {
                    "open_id": sender.sender_id.open_id if sender and sender.sender_id else None,
                }
            },
        }
        logger.info("[事件回调] message_type=%s, content=%s", msg.message_type, msg.content)

        import threading
        threading.Thread(
            target=asyncio.run,
            args=(handler.handle_message(event_dict, event_type),),
            daemon=True,
        ).start()

    except Exception as e:
        logger.exception("[事件回调] 处理失败: %s", e)


def on_message_read(data: P2ImMessageMessageReadV1) -> None:
    """消息已读事件，仅记录日志，无需业务处理"""
    logger.debug("[消息已读] %s", data)


event_handler = (
    lark.EventDispatcherHandler.builder(
        encrypt_key=FEISHU_DATA.get("encrypt_key", ""),
        verification_token=FEISHU_DATA.get("verification_token", ""),
    )
    .register_p2_im_message_receive_v1(on_message_receive)
    .register_p2_im_message_message_read_v1(on_message_read)
    .build()
)

# ── FastAPI 应用 ──────────────────────────────────────────
app = FastAPI(title="飞书智能体机器人", version="2.0")


@app.post("/")
async def webhook(request: Request):
    """
    接收飞书事件推送。
    将原始请求封装为 SDK 的 RawRequest 后交由 EventDispatcher 处理，
    SDK 内部自动完成 challenge 验证、消息解密、签名校验。
    """
    body = await request.body()

    # Starlette 将 header 键全部转为小写，但 Lark SDK 期望 Title-Case
    # (如 X-Lark-Request-Timestamp)，需要还原大小写格式
    headers = {
        "-".join(part.capitalize() for part in k.split("-")): v
        for k, v in request.headers.items()
    }

    raw_req = lark.RawRequest()
    raw_req.uri = str(request.url.path)
    raw_req.headers = headers
    raw_req.body = body

    raw_resp: lark.RawResponse = event_handler.do(raw_req)

    import json as _json
    try:
        resp_body = _json.loads(raw_resp.content) if raw_resp.content else {}
    except (TypeError, _json.JSONDecodeError):
        resp_body = {}

    return JSONResponse(
        content=resp_body,
        status_code=raw_resp.status_code or 200,
    )


@app.get("/health")
async def health():
    return {"status": "running", "version": "2.0"}


if __name__ == "__main__":
    import uvicorn

    logger.info("飞书机器人服务启动 (FastAPI + Lark SDK)")
    logger.info("webhook 地址: http://0.0.0.0:8071/")
    uvicorn.run(app, host="0.0.0.0", port=8071)
