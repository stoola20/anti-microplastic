import os
import base64
import requests
from io import BytesIO
from PIL import Image
import anthropic
import re
from tavily import TavilyClient
from bot.prompts import EDC_SYSTEM_PROMPT

anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
tavily_client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY", ""))
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

ERROR_BRIEF = "😅 抱歉，無法清楚辨識成分表，請確認照片清晰且成分文字完整。"
ERROR_FULL = ERROR_BRIEF

NOT_FOUND_BRIEF = "😅 抱歉，找不到這個產品的成分資訊，可以嘗試拍攝產品背面成分表。"
NOT_FOUND_FULL = NOT_FOUND_BRIEF

SEARCH_TOOL = [{
    "name": "search_web",
    "description": "搜尋個人護理產品的 INCI 成分表",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜尋關鍵字，例如 'CeraVe PM INCI ingredients list'"
            }
        },
        "required": ["query"]
    }
}]


def _strip_markdown(text: str) -> str:
    # Remove fenced code blocks (``` ... ```, including language tags)
    text = re.sub(r'```[^\n]*\n.*?```', '', text, flags=re.DOTALL)
    # Remove bold **text** and __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', r'\1', text, flags=re.DOTALL)
    # Remove headings at start of line (# ## ###)
    text = re.sub(r'^#{1,3} ', '', text, flags=re.MULTILINE)
    return text


def _download_line_image(message_id: str) -> bytes:
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
    resp = requests.get(
        f"https://api-data.line.me/v2/bot/message/{message_id}/content",
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.content


def _resize_and_encode(image_bytes: bytes) -> str:
    img = Image.open(BytesIO(image_bytes))
    img = img.convert("RGB")
    img.thumbnail((1600, 1600))
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    # Second pass if still too large
    if len(buffer.getvalue()) > 3_500_000:
        buffer = BytesIO()
        img.thumbnail((800, 800))
        img.save(buffer, format="JPEG", quality=70)
    return base64.b64encode(buffer.getvalue()).decode()


def _extract_text(response) -> str:
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return ""


def analyze_image(message_id: str) -> dict:
    try:
        image_bytes = _download_line_image(message_id)
        b64 = _resize_and_encode(image_bytes)
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=EDC_SYSTEM_PROMPT + "\nOUTPUT=BRIEF",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": "請分析這個成分表的 EDC 風險，用指定格式回覆。"}
                ]
            }]
        )
        brief_text = _strip_markdown(_extract_text(response))

        # Get full analysis
        full_response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=EDC_SYSTEM_PROMPT + "\nOUTPUT=FULL",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": "請分析這個成分表的 EDC 風險，用指定格式回覆。"}
                ]
            }]
        )
        full_text = _strip_markdown(_extract_text(full_response))
        return {"brief": brief_text, "full": full_text}
    except Exception:
        return {"brief": ERROR_BRIEF, "full": ERROR_FULL}


def analyze_product_name(product_name: str) -> dict:
    MAX_ROUNDS = 3
    messages = [{"role": "user", "content": f"請分析這個個人護理產品的 EDC 風險：{product_name}"}]

    brief_text = None
    for _ in range(MAX_ROUNDS):
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=EDC_SYSTEM_PROMPT + "\nOUTPUT=BRIEF",
            tools=SEARCH_TOOL,
            messages=messages,
        )
        if response.stop_reason == "end_turn":
            brief_response = response
            brief_text = _strip_markdown(_extract_text(brief_response))
            break
        if response.stop_reason == "tool_use":
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tool_block in tool_blocks:
                search_result = tavily_client.search(tool_block.input["query"])
                result_text = "\n".join(r.get("content", "") for r in search_result.get("results", []))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result_text or "找不到相關成分資訊。"
                })
            messages.append({"role": "user", "content": tool_results})

    if not brief_text:
        return {"brief": NOT_FOUND_BRIEF, "full": NOT_FOUND_FULL}

    # Reuse accumulated search context for full analysis (avoids redundant Tavily call).
    # Append assistant's end_turn response first to maintain role alternation.
    messages.append({"role": "assistant", "content": brief_response.content})
    messages.append({"role": "user", "content": "請輸出完整分析（OUTPUT=FULL）。"})
    full_response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=EDC_SYSTEM_PROMPT + "\nOUTPUT=FULL",
        messages=messages,
    )
    full_text = _strip_markdown(_extract_text(full_response))
    return {"brief": brief_text, "full": full_text or brief_text}
