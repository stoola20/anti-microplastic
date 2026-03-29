import asyncio
import logging
import os, json, hashlib, hmac, base64
from typing import Optional
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import httpx
from bot.prompts import DETAIL_TRIGGERS, HELP_MESSAGE
from bot import state, analyzer

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

DETAIL_QUICK_REPLY = {
    "items": [{
        "type": "action",
        "action": {
            "type": "message",
            "label": "📋 查看詳細分析",
            "text": "詳細"
        }
    }]
}

app = FastAPI()
logger = logging.getLogger(__name__)


def verify_signature(body: bytes, signature: str) -> bool:
    mac = hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode()
    return hmac.compare_digest(expected, signature)


def push_message(user_id: str, text: str, *, quick_reply: Optional[dict] = None) -> None:
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    message = {"type": "text", "text": text}
    if quick_reply is not None:
        message["quickReply"] = quick_reply
    payload = {
        "to": user_id,
        "messages": [message]
    }
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(LINE_PUSH_URL, json=payload, headers=headers)
            resp.raise_for_status()
    except Exception as e:
        logger.error("push_message failed for user %s: %s", user_id, e)


async def process_events(events: list) -> None:
    loop = asyncio.get_event_loop()
    for event in events:
        user_id = event.get("source", {}).get("userId")
        if not user_id:
            continue

        if event.get("type") == "postback":
            postback = event.get("postback") or {}
            data = postback.get("data", "")
            if data == "action=help":
                await loop.run_in_executor(None, push_message, user_id, HELP_MESSAGE)
            elif data == "action=detail":
                full = state.get_full_analysis(user_id)
                reply = full if full else "請先查詢一個產品，再點選「查看詳細」喔！"
                await loop.run_in_executor(None, push_message, user_id, reply)
            else:
                logger.warning("Unknown postback data '%s' from user %s", data, user_id)
            continue

        if event.get("type") != "message":
            continue
        msg = event["message"]

        if msg["type"] == "image":
            await loop.run_in_executor(None, push_message, user_id, "⏳ 收到！正在辨識成分表，預計約 1 分鐘內完成。您可以先離開對話，結果會自動傳送給您 📩")
            result = await loop.run_in_executor(None, analyzer.analyze_image, msg["id"])
            state.save_full_analysis(user_id, result["full"])
            await loop.run_in_executor(
                None, lambda uid=user_id, brief=result["brief"]: push_message(uid, brief, quick_reply=DETAIL_QUICK_REPLY)
            )

        elif msg["type"] == "text":
            text = msg["text"].strip()
            if text in DETAIL_TRIGGERS:
                full = state.get_full_analysis(user_id)
                reply = full if full else "請先查詢一個產品，再回覆「詳細」。"
                await loop.run_in_executor(None, push_message, user_id, reply)
            else:
                await loop.run_in_executor(None, push_message, user_id, f"⏳ 收到！正在查詢「{text}」的相關資訊，預計約 1 分鐘內完成。您可以先離開對話，結果會自動傳送給您 📩")
                result = await loop.run_in_executor(None, analyzer.analyze_product_name, text)
                state.save_full_analysis(user_id, result["full"])
                await loop.run_in_executor(
                    None, lambda uid=user_id, brief=result["brief"]: push_message(uid, brief, quick_reply=DETAIL_QUICK_REPLY)
                )
        # else: ignore stickers, video, etc.


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")
    if not signature or not verify_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")
    payload = json.loads(body)
    background_tasks.add_task(process_events, payload.get("events", []))
    return JSONResponse({"status": "ok"})
