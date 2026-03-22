import asyncio
import logging
import os, json, hashlib, hmac, base64
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import httpx
from bot.prompts import DETAIL_TRIGGERS
from bot import state, analyzer

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

app = FastAPI()
logger = logging.getLogger(__name__)


def verify_signature(body: bytes, signature: str) -> bool:
    mac = hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode()
    return hmac.compare_digest(expected, signature)


def push_message(user_id: str, text: str) -> None:
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": text}]
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
        if event.get("type") != "message":
            continue
        user_id = event["source"]["userId"]
        msg = event["message"]

        if msg["type"] == "image":
            await loop.run_in_executor(None, push_message, user_id, "⏳ 正在辨識成分表，請稍候...")
            result = await loop.run_in_executor(None, analyzer.analyze_image, msg["id"])
            state.save_full_analysis(user_id, result["full"])
            await loop.run_in_executor(None, push_message, user_id, result["brief"])

        elif msg["type"] == "text":
            text = msg["text"].strip()
            if text in DETAIL_TRIGGERS:
                full = state.get_full_analysis(user_id)
                reply = full if full else "請先查詢一個產品，再回覆「詳細」。"
                await loop.run_in_executor(None, push_message, user_id, reply)
            else:
                await loop.run_in_executor(None, push_message, user_id, f"⏳ 正在分析「{text}」的成分，請稍候...")
                result = await loop.run_in_executor(None, analyzer.analyze_product_name, text)
                state.save_full_analysis(user_id, result["full"])
                await loop.run_in_executor(None, push_message, user_id, result["brief"])
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
