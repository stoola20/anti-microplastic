import hashlib, hmac, base64, json, pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Set env vars before importing app
import os
os.environ["LINE_CHANNEL_SECRET"] = "test_secret"
os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = "test_token"
os.environ["ANTHROPIC_API_KEY"] = "test"
os.environ["TAVILY_API_KEY"] = "test"

from bot.main import app, push_message

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
    assert "CeraVe PM" in first_msg
    assert "離開對話" in first_msg


def test_push_message_with_quick_reply():
    """push_message should include quickReply in payload when provided."""
    quick_reply = {
        "items": [{
            "type": "action",
            "action": {"type": "message", "label": "📋 查看詳細分析", "text": "詳細"}
        }]
    }
    with patch("bot.main.httpx.Client") as MockClient:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client

        push_message("U123", "test text", quick_reply=quick_reply)

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        msg = payload["messages"][0]
        assert msg["text"] == "test text"
        assert "quickReply" in msg
        assert msg["quickReply"]["items"][0]["action"]["text"] == "詳細"


def test_push_message_without_quick_reply():
    """push_message without quick_reply should not include quickReply key."""
    with patch("bot.main.httpx.Client") as MockClient:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client

        push_message("U123", "test text")

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        msg = payload["messages"][0]
        assert "quickReply" not in msg


def test_brief_result_includes_quick_reply_for_text_query():
    """After product analysis, brief result should include Quick Reply button."""
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
    # Second call is the brief result (first is waiting message)
    assert mock_push.call_count == 2
    brief_call_kwargs = mock_push.call_args_list[1]
    # Check quick_reply keyword argument is passed
    assert "quick_reply" in brief_call_kwargs.kwargs
    qr = brief_call_kwargs.kwargs["quick_reply"]
    assert qr["items"][0]["action"]["text"] == "詳細"
    assert brief_call_kwargs.args[1] == "ok"  # verify brief text content passed through


def test_brief_result_includes_quick_reply_for_image():
    """After image analysis, brief result should include Quick Reply button."""
    image_event = {
        "events": [{
            "type": "message",
            "replyToken": "nHuyWiB7yP5Zw52FIkcQobQuGDXCTA",
            "source": {"userId": "U123", "type": "user"},
            "message": {"id": "img001", "type": "image"}
        }]
    }
    body = json.dumps(image_event).encode()
    sig = make_signature(body)
    mock_push = MagicMock()
    with patch("bot.main.analyzer.analyze_image", return_value={"brief": "ok", "full": "ok"}), \
         patch("bot.main.push_message", mock_push):
        client.post(
            "/webhook",
            content=body,
            headers={"X-Line-Signature": sig, "Content-Type": "application/json"}
        )
    assert mock_push.call_count == 2
    brief_call_kwargs = mock_push.call_args_list[1]
    assert "quick_reply" in brief_call_kwargs.kwargs
    qr = brief_call_kwargs.kwargs["quick_reply"]
    assert qr["items"][0]["action"]["text"] == "詳細"
    assert brief_call_kwargs.args[1] == "ok"  # verify brief text content passed through


def make_postback_event(data: str, user_id: str = "U123") -> dict:
    return {
        "events": [{
            "type": "postback",
            "source": {"userId": user_id, "type": "user"},
            "postback": {"data": data}
        }]
    }


def test_postback_help_returns_help_message():
    """Postback action=help should push HELP_MESSAGE."""
    from bot.prompts import HELP_MESSAGE
    body = json.dumps(make_postback_event("action=help")).encode()
    sig = make_signature(body)
    mock_push = MagicMock()
    with patch("bot.main.push_message", mock_push):
        client.post(
            "/webhook",
            content=body,
            headers={"X-Line-Signature": sig, "Content-Type": "application/json"}
        )
    mock_push.assert_called_once_with("U123", HELP_MESSAGE)


def test_postback_detail_returns_full_analysis():
    """Postback action=detail should return stored full analysis."""
    from bot import state
    test_user = "U_postback_detail"
    state.save_full_analysis(test_user, "full analysis text")
    try:
        body = json.dumps(make_postback_event("action=detail", user_id=test_user)).encode()
        sig = make_signature(body)
        mock_push = MagicMock()
        with patch("bot.main.push_message", mock_push):
            client.post(
                "/webhook",
                content=body,
                headers={"X-Line-Signature": sig, "Content-Type": "application/json"}
            )
        mock_push.assert_called_once_with(test_user, "full analysis text")
    finally:
        state.clear_analysis(test_user)


def test_postback_detail_without_prior_analysis():
    """Postback action=detail without prior query should show guidance."""
    from bot import state
    state.clear_analysis("U999")
    body = json.dumps(make_postback_event("action=detail", user_id="U999")).encode()
    sig = make_signature(body)
    mock_push = MagicMock()
    with patch("bot.main.push_message", mock_push):
        client.post(
            "/webhook",
            content=body,
            headers={"X-Line-Signature": sig, "Content-Type": "application/json"}
        )
    pushed_text = mock_push.call_args[0][1]
    assert "先查詢" in pushed_text or "先" in pushed_text
