import hashlib, hmac, base64, json, pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Set env vars before importing app
import os
os.environ["LINE_CHANNEL_SECRET"] = "test_secret"
os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = "test_token"
os.environ["ANTHROPIC_API_KEY"] = "test"
os.environ["TAVILY_API_KEY"] = "test"

from bot.main import app

client = TestClient(app)

def make_signature(body: bytes, secret: str = "test_secret") -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode()

def make_text_event(text: str, user_id: str = "U123") -> dict:
    return {
        "events": [{
            "type": "message",
            "replyToken": "nHuyWiB7yP5Zw52FIkcQobQuGDXCTA",
            "source": {"userId": user_id, "type": "user"},
            "message": {"id": "msg001", "type": "text", "text": text}
        }]
    }

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200

def test_webhook_bad_signature_returns_400():
    body = json.dumps(make_text_event("hello")).encode()
    response = client.post(
        "/webhook",
        content=body,
        headers={"X-Line-Signature": "bad_signature", "Content-Type": "application/json"}
    )
    assert response.status_code == 400

def test_webhook_good_signature_returns_200():
    body = json.dumps(make_text_event("CeraVe PM")).encode()
    sig = make_signature(body)
    with patch("bot.main.analyzer.analyze_product_name", return_value={"brief": "ok", "full": "ok"}), \
         patch("bot.main.push_message"):
        response = client.post(
            "/webhook",
            content=body,
            headers={"X-Line-Signature": sig, "Content-Type": "application/json"}
        )
    assert response.status_code == 200

def test_webhook_missing_signature_returns_400():
    body = json.dumps(make_text_event("hello")).encode()
    response = client.post("/webhook", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 400

def test_waiting_message_is_first_push_for_product_query():
    """push_message should be called first with ⏳ waiting text, then with analysis result."""
    body = json.dumps(make_text_event("CeraVe PM")).encode()
    sig = make_signature(body)
    mock_push = MagicMock()
    with patch("bot.main.analyzer.analyze_product_name", return_value={"brief": "ok", "full": "ok"}), \
         patch("bot.main.push_message", mock_push):
        client.post(
            "/webhook",
            content=body,
            headers={"X-Line-Signature": sig, "Content-Type": "application/json"}
        )
    assert mock_push.call_count == 2
    first_msg = mock_push.call_args_list[0][0][1]  # (user_id, text) — second arg
    assert "⏳" in first_msg
    assert "正在分析" in first_msg
    assert "CeraVe PM" in first_msg
