import os
from unittest.mock import MagicMock, patch

# See tests/test_analyzer_openai.py — openai.OpenAI(api_key=...) validates
# eagerly, so bot.state_openai (which imports bot.analyzer_openai) needs a
# dummy key present regardless of test collection order.
os.environ.setdefault("OPENAI_API_KEY", "test")

from bot.state_openai import save_full_analysis, get_full_analysis, clear_analysis


def test_get_missing_returns_none_without_calling_api():
    with patch("bot.state_openai.analyzer_openai.openai_client.responses.retrieve") as mock_retrieve:
        assert get_full_analysis("nonexistent_user") is None
        mock_retrieve.assert_not_called()


def test_save_then_get_retrieves_by_id_not_cached_text():
    save_full_analysis("user_123", "resp_abc")
    fake_response = MagicMock()
    fake_response.output_text = "完整分析全文"
    with patch(
        "bot.state_openai.analyzer_openai.openai_client.responses.retrieve",
        return_value=fake_response,
    ) as mock_retrieve:
        result = get_full_analysis("user_123")
    assert result == "完整分析全文"
    mock_retrieve.assert_called_once_with("resp_abc")
    clear_analysis("user_123")


def test_save_none_id_returns_none_on_get():
    """NOT_FOUND case: analyzer returns full=None, nothing to retrieve later."""
    save_full_analysis("user_notfound", None)
    with patch("bot.state_openai.analyzer_openai.openai_client.responses.retrieve") as mock_retrieve:
        assert get_full_analysis("user_notfound") is None
        mock_retrieve.assert_not_called()
    clear_analysis("user_notfound")


def test_overwrite():
    save_full_analysis("user_123", "resp_old")
    save_full_analysis("user_123", "resp_new")
    fake_response = MagicMock()
    fake_response.output_text = "new text"
    with patch(
        "bot.state_openai.analyzer_openai.openai_client.responses.retrieve",
        return_value=fake_response,
    ) as mock_retrieve:
        get_full_analysis("user_123")
    mock_retrieve.assert_called_once_with("resp_new")
    clear_analysis("user_123")


def test_clear():
    save_full_analysis("user_abc", "resp_xyz")
    clear_analysis("user_abc")
    assert get_full_analysis("user_abc") is None
