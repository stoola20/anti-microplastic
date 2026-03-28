import pathlib
import pytest
from unittest.mock import MagicMock, patch
from bot.analyzer import analyze_image

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"

@pytest.fixture
def mock_claude_response():
    mock = MagicMock()
    mock.stop_reason = "end_turn"
    content_block = MagicMock()
    content_block.type = "text"
    content_block.text = "🟢 低風險 — 測試產品\n\nParfum / Fragrance  ✅ 無\nParabens            ✅ 無\nMIT / Triclosan     ✅ 無\nBPA / Benzophenone  ✅ 無\n\n💡 成分乾淨，無 EDC 疑慮。\n回覆「詳細」查看完整建議。"
    mock.content = [content_block]
    return mock

@patch("bot.analyzer.anthropic_client.messages.create")
@patch("bot.analyzer.requests.get")
def test_analyze_image_returns_brief_and_full(mock_get, mock_claude, mock_claude_response):
    # Mock LINE image download
    with open(FIXTURE_DIR / "sample_ingredients.jpg", "rb") as f:
        mock_get.return_value.content = f.read()
    mock_claude.return_value = mock_claude_response

    result = analyze_image("msg_id_123")

    assert "brief" in result
    assert "full" in result
    assert "🟢" in result["brief"]

@patch("bot.analyzer.anthropic_client.messages.create")
@patch("bot.analyzer.requests.get")
def test_analyze_image_handles_download_error(mock_get, mock_claude, mock_claude_response):
    mock_get.side_effect = Exception("Network error")
    result = analyze_image("msg_id_456")
    assert "brief" in result
    assert "抱歉" in result["brief"]

from bot.analyzer import analyze_product_name

@patch("bot.analyzer.tavily_client.search")
@patch("bot.analyzer.anthropic_client.messages.create")
def test_analyze_product_name_no_tool_call(mock_claude, mock_tavily, mock_claude_response):
    """Claude answers directly without needing search."""
    mock_claude.return_value = mock_claude_response
    result = analyze_product_name("CeraVe PM 保濕乳")
    assert "brief" in result
    assert "full" in result
    mock_tavily.assert_not_called()

@patch("bot.analyzer.tavily_client.search")
@patch("bot.analyzer.anthropic_client.messages.create")
def test_analyze_product_name_with_tool_call(mock_claude, mock_tavily):
    """Claude calls search tool, then gives final answer."""
    # First call: tool_use
    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "tool_abc"
    tool_block.input = {"query": "CeraVe PM INCI ingredients"}
    tool_response.content = [tool_block]

    # Second call: end_turn
    final_response = MagicMock()
    final_response.stop_reason = "end_turn"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "🟢 低風險 — CeraVe PM\n\nParfum / Fragrance  ✅ 無\nParabens            ✅ 無\nMIT / Triclosan     ✅ 無\nBPA / Benzophenone  ✅ 無\n\n💡 乾淨配方。\n回覆「詳細」查看完整建議。"
    final_response.content = [text_block]

    mock_claude.side_effect = [tool_response, final_response, final_response]
    mock_tavily.return_value = {"results": [{"content": "Water, Glycerin, Ceramide NP..."}]}

    result = analyze_product_name("CeraVe PM 保濕乳")
    assert "🟢" in result["brief"]
    assert mock_tavily.called

@patch("bot.analyzer.anthropic_client.messages.create")
def test_analyze_product_name_max_rounds_fallback(mock_claude):
    """Returns fallback message if loop exhausts MAX_ROUNDS."""
    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "tool_xyz"
    tool_block.input = {"query": "unknown product INCI"}
    tool_response.content = [tool_block]

    with patch("bot.analyzer.tavily_client.search", return_value={"results": []}):
        mock_claude.return_value = tool_response
        result = analyze_product_name("未知產品XYZ")
    assert "抱歉" in result["brief"]


from bot.analyzer import _strip_markdown

def test_strip_markdown_removes_bold_asterisks():
    assert _strip_markdown("**粗體** text") == "粗體 text"

def test_strip_markdown_removes_bold_underscores():
    assert _strip_markdown("__bold__ text") == "bold text"

def test_strip_markdown_removes_fenced_code_block():
    text = "before\n```python\nsome code\n```\nafter"
    result = _strip_markdown(text)
    assert "```" not in result
    assert "before" in result
    assert "after" in result

def test_strip_markdown_removes_heading():
    assert _strip_markdown("## 標題\ncontent") == "標題\ncontent"
    assert _strip_markdown("### 小標\ncontent") == "小標\ncontent"

def test_strip_markdown_preserves_single_asterisk():
    """Single-asterisk italic must NOT be stripped — too broad."""
    assert _strip_markdown("*italic*") == "*italic*"

def test_strip_markdown_preserves_underscores_in_inci():
    """INCI ingredient names may contain underscores — must not be corrupted."""
    assert _strip_markdown("CI_77891") == "CI_77891"

def test_strip_markdown_no_op_on_clean_text():
    clean = "🟢 低風險 — CeraVe PM\n\n✅ 無 Parfum\n💡 成分乾淨。"
    assert _strip_markdown(clean) == clean


@patch("bot.analyzer.tavily_client.search")
@patch("bot.analyzer.anthropic_client.messages.create")
def test_analyze_product_name_irrelevant_input(mock_claude, mock_tavily):
    """Irrelevant input returns guidance without Tavily search or full analysis."""
    response = MagicMock()
    response.stop_reason = "end_turn"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "NOT_RELEVANT:\n嗨！我是日常用品安全分析助手 🔬\n\n我可以幫你檢查：\n📋 保養品、化妝品、清潔用品 — 是否含有干擾荷爾蒙的成分\n🍽️ 保鮮盒、紙杯、餐具、鍋具 — 是否會釋放有害物質到食物中\n\n直接告訴我產品名稱就好，例如「露得清洗面乳」或「PP保鮮盒」，也可以拍成分表照片給我！"
    response.content = [text_block]
    mock_claude.return_value = response

    result = analyze_product_name("我漂亮嗎？")

    assert "日常用品安全分析助手" in result["brief"]
    assert "NOT_RELEVANT" not in result["brief"]
    assert result["brief"] == result["full"]
    mock_tavily.assert_not_called()
    assert mock_claude.call_count == 1


@patch("bot.analyzer.tavily_client.search")
@patch("bot.analyzer.anthropic_client.messages.create")
def test_full_analysis_populated_after_tool_call(mock_claude, mock_tavily):
    """Full analysis must be complete even when brief required a tool-use round."""
    # Round 1 (brief): tool_use
    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "tool_abc"
    tool_block.input = {"query": "CeraVe PM INCI ingredients"}
    tool_response.content = [tool_block]

    # Round 2 (brief): end_turn
    brief_end = MagicMock()
    brief_end.stop_reason = "end_turn"
    brief_block = MagicMock()
    brief_block.type = "text"
    brief_block.text = "🟢 低風險 — CeraVe PM\n\n✅ 無 Parfum\n💡 乾淨。\n回覆「詳細」查看完整建議。"
    brief_end.content = [brief_block]

    # Round 3 (full): end_turn
    full_text = "完整分析：Ceramide NP 神經醯胺，皮膚屏障修復成分，無 EDC 疑慮。"
    full_end = MagicMock()
    full_end.stop_reason = "end_turn"
    full_block = MagicMock()
    full_block.type = "text"
    full_block.text = full_text
    full_end.content = [full_block]

    mock_claude.side_effect = [tool_response, brief_end, full_end]
    mock_tavily.return_value = {"results": [{"content": "Ceramide NP, Niacinamide, Hyaluronic Acid"}]}

    result = analyze_product_name("CeraVe PM 保濕乳")

    assert result["full"] == full_text
    assert mock_claude.call_count == 3
