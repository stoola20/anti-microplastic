import os
import pathlib
import pytest
from unittest.mock import MagicMock, patch

# openai.OpenAI(api_key=...) validates eagerly at construction time (unlike
# anthropic.Anthropic, which only fails on an actual request) — set a dummy
# key before importing bot.analyzer_openai so collecting this file doesn't
# blow up when OPENAI_API_KEY isn't already set in the environment.
os.environ.setdefault("OPENAI_API_KEY", "test")

from bot.analyzer_openai import analyze_image_openai, analyze_product_name_openai

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


def _make_response(text: str, function_calls=None, response_id="resp_1"):
    """Build a fake Responses API response object.

    function_calls: list of (call_id, name, arguments_json_str) tuples.
    When provided, output_text is empty (mirrors a real function_call-only turn).
    """
    response = MagicMock()
    response.id = response_id
    if function_calls:
        response.output_text = ""
        items = []
        for call_id, name, arguments in function_calls:
            item = MagicMock()
            item.type = "function_call"
            item.call_id = call_id
            item.name = name
            item.arguments = arguments
            items.append(item)
        response.output = items
    else:
        response.output_text = text
        message_item = MagicMock()
        message_item.type = "message"
        response.output = [message_item]
    return response


@patch("bot.analyzer_openai.openai_client.responses.create")
@patch("bot.analyzer_openai._download_line_image")
def test_analyze_image_returns_brief_and_full_id(mock_download, mock_create):
    with open(FIXTURE_DIR / "sample_ingredients.jpg", "rb") as f:
        mock_download.return_value = f.read()

    full_response = _make_response(
        "🟢 低風險 — 測試產品\n\n💡 成分乾淨，無 EDC 疑慮。", response_id="resp_full"
    )
    brief_response = _make_response("🟢 低風險 — 測試產品（簡短版）", response_id="resp_brief")
    mock_create.side_effect = [full_response, brief_response]

    result = analyze_image_openai("msg_id_123")

    assert "brief" in result
    assert "full" in result
    assert "🟢" in result["brief"]
    # "full" must be the FULL response's id, not literal text.
    assert result["full"] == "resp_full"
    assert mock_create.call_count == 2


@patch("bot.analyzer_openai._download_line_image")
def test_analyze_image_handles_download_error(mock_download):
    mock_download.side_effect = Exception("Network error")
    result = analyze_image_openai("msg_id_456")
    assert "brief" in result
    assert "抱歉" in result["brief"]
    assert result["full"] is None


@patch("bot.analyzer_openai.tavily_client.search")
@patch("bot.analyzer_openai.openai_client.responses.create")
def test_analyze_product_name_no_tool_call(mock_create, mock_tavily):
    """Model answers directly without needing search."""
    brief_response = _make_response("🟢 低風險 — CeraVe PM", response_id="resp_brief")
    full_response = _make_response("完整分析：無 EDC 疑慮。", response_id="resp_full")
    mock_create.side_effect = [brief_response, full_response]

    result = analyze_product_name_openai("CeraVe PM 保濕乳")

    assert "brief" in result
    assert "full" in result
    assert result["full"] == "resp_full"
    mock_tavily.assert_not_called()


@patch("bot.analyzer_openai.tavily_client.search")
@patch("bot.analyzer_openai.openai_client.responses.create")
def test_analyze_product_name_with_tool_call(mock_create, mock_tavily):
    """Model calls search tool, then gives final answer."""
    tool_call_response = _make_response(
        "", function_calls=[("call_1", "search_web", '{"query": "CeraVe PM INCI ingredients"}')],
        response_id="resp_tool",
    )
    brief_response = _make_response("🟢 低風險 — CeraVe PM", response_id="resp_brief")
    full_response = _make_response("完整分析：乾淨配方。", response_id="resp_full")

    mock_create.side_effect = [tool_call_response, brief_response, full_response]
    mock_tavily.return_value = {"results": [{"content": "Water, Glycerin, Ceramide NP..."}]}

    result = analyze_product_name_openai("CeraVe PM 保濕乳")

    assert "🟢" in result["brief"]
    assert result["full"] == "resp_full"
    mock_tavily.assert_called_once()

    # Second create() call must chain off the tool-call response via
    # previous_response_id and send back function_call_output.
    second_call_kwargs = mock_create.call_args_list[1].kwargs
    assert second_call_kwargs["previous_response_id"] == "resp_tool"
    assert second_call_kwargs["input"][0]["type"] == "function_call_output"
    assert second_call_kwargs["input"][0]["call_id"] == "call_1"


@patch("bot.analyzer_openai.openai_client.responses.create")
def test_analyze_product_name_max_rounds_exhausted_returns_not_found(mock_create):
    """If every round keeps returning function_call (never a final message),
    the loop exhausts MAX_ROUNDS and falls back to NOT_FOUND."""
    tool_call_response = _make_response(
        "", function_calls=[("call_x", "search_web", '{"query": "unknown product INCI"}')],
        response_id="resp_tool",
    )
    mock_create.return_value = tool_call_response

    with patch("bot.analyzer_openai.tavily_client.search", return_value={"results": []}):
        result = analyze_product_name_openai("未知產品XYZ")

    assert "抱歉" in result["brief"]
    assert result["full"] is None


@patch("bot.analyzer_openai.tavily_client.search")
@patch("bot.analyzer_openai.openai_client.responses.create")
def test_analyze_product_name_irrelevant_input(mock_create, mock_tavily):
    """Irrelevant input returns guidance without Tavily search or full analysis."""
    response = _make_response(
        "NOT_RELEVANT:\n嗨！我是日常用品安全分析助手 🔬\n\n直接告訴我產品名稱就好。",
        response_id="resp_guidance",
    )
    mock_create.return_value = response

    result = analyze_product_name_openai("我漂亮嗎？")

    assert "日常用品安全分析助手" in result["brief"]
    assert "NOT_RELEVANT" not in result["brief"]
    # For NOT_RELEVANT, "full" is that same response's id (retrieve() would
    # just return the identical guidance text — mirrors Claude's behavior of
    # brief == full for this case).
    assert result["full"] == "resp_guidance"
    mock_tavily.assert_not_called()
    assert mock_create.call_count == 1
