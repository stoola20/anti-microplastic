import json
import os

from openai import OpenAI

from bot.analyzer import (
    ERROR_BRIEF,
    NOT_FOUND_BRIEF,
    _download_line_image,
    _resize_and_encode,
    _strip_markdown,
    tavily_client,
)
from bot.prompts import NOT_RELEVANT_PREFIX, SYSTEM_PROMPT

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

OPENAI_MODEL = "gpt-5.6-terra"

SEARCH_TOOL_OPENAI = [{
    "type": "function",
    "name": "search_web",
    "description": "搜尋產品成分或食品容器材質資訊",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜尋關鍵字，例如 'CeraVe PM INCI ingredients list'"
            }
        },
        "required": ["query"],
        "additionalProperties": False
    },
    "strict": True
}]


def _extract_text(response) -> str:
    return getattr(response, "output_text", None) or ""


def _get_function_calls(response) -> list:
    return [item for item in response.output if getattr(item, "type", None) == "function_call"]


def analyze_image_openai(message_id: str) -> dict:
    try:
        image_bytes = _download_line_image(message_id)
        b64 = _resize_and_encode(image_bytes)

        # Step 1: Generate FULL analysis from image
        full_response = openai_client.responses.create(
            model=OPENAI_MODEL,
            instructions=SYSTEM_PROMPT + "\nOUTPUT=FULL",
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"},
                    {"type": "input_text", "text": "請分析這張圖片中的產品成分或容器材質，評估有害化學物質風險，用指定格式回覆。"}
                ]
            }]
        )
        full_text = _strip_markdown(_extract_text(full_response))

        # Irrelevant image — return guidance without brief analysis
        if full_text.startswith(NOT_RELEVANT_PREFIX):
            cleaned = full_text[len(NOT_RELEVANT_PREFIX):].strip()
            return {"brief": cleaned, "full": full_response.id}

        # Step 2: Derive BRIEF from FULL by continuing the same response
        # chain (no image re-upload, no re-pasted text — previous_response_id
        # carries the FULL text forward server-side).
        brief_response = openai_client.responses.create(
            model=OPENAI_MODEL,
            instructions=SYSTEM_PROMPT + "\nOUTPUT=BRIEF",
            previous_response_id=full_response.id,
            input="請根據以上分析，用 OUTPUT=BRIEF 格式輸出簡短版本。",
        )
        brief_text = _strip_markdown(_extract_text(brief_response))
        # "full" holds the FULL response's id (not the text) — state_openai.py
        # retrieves it later via responses.retrieve(), it is never stored as text.
        return {"brief": brief_text, "full": full_response.id}
    except Exception:
        return {"brief": ERROR_BRIEF, "full": None}


def analyze_product_name_openai(product_name: str) -> dict:
    MAX_ROUNDS = 3
    previous_id = None
    next_input = f"請分析這個產品或物品的有害化學物質風險：{product_name}"

    brief_text = None
    brief_response = None
    try:
        for _ in range(MAX_ROUNDS):
            response = openai_client.responses.create(
                model=OPENAI_MODEL,
                instructions=SYSTEM_PROMPT + "\nOUTPUT=BRIEF",
                input=next_input,
                tools=SEARCH_TOOL_OPENAI,
                previous_response_id=previous_id,
            )
            function_calls = _get_function_calls(response)
            if not function_calls:
                brief_response = response
                brief_text = _strip_markdown(_extract_text(response))
                break

            tool_outputs = []
            for call in function_calls:
                args = json.loads(call.arguments)
                search_result = tavily_client.search(args["query"])
                result_text = "\n".join(r.get("content", "") for r in search_result.get("results", []))
                tool_outputs.append({
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": result_text or "找不到相關成分資訊。",
                })
            previous_id = response.id
            next_input = tool_outputs
    except Exception:
        return {"brief": ERROR_BRIEF, "full": None}

    if not brief_text:
        return {"brief": NOT_FOUND_BRIEF, "full": None}

    # Irrelevant input — return guidance without full analysis
    if brief_text.startswith(NOT_RELEVANT_PREFIX):
        cleaned = brief_text[len(NOT_RELEVANT_PREFIX):].strip()
        return {"brief": cleaned, "full": brief_response.id}

    # Reuse accumulated search context (via previous_response_id) for full
    # analysis — same request-processing pass as BRIEF, not a later,
    # independently-triggered generation.
    try:
        full_response = openai_client.responses.create(
            model=OPENAI_MODEL,
            instructions=SYSTEM_PROMPT + "\nOUTPUT=FULL",
            previous_response_id=brief_response.id,
            input="請輸出完整分析（OUTPUT=FULL）。",
        )
        full_text = _strip_markdown(_extract_text(full_response))
    except Exception:
        return {"brief": brief_text, "full": brief_response.id}

    return {"brief": brief_text, "full": full_response.id if full_text else brief_response.id}


# Aliases matching bot/analyzer.py's public names — lets bot/main.py's call
# sites (analyzer.analyze_image / analyzer.analyze_product_name) work
# unmodified regardless of which provider module is imported as `analyzer`.
analyze_image = analyze_image_openai
analyze_product_name = analyze_product_name_openai
