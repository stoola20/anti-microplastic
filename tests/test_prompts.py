import re

from bot.prompts import HELP_MESSAGE, DETAIL_TRIGGERS

def test_help_message_exists_and_is_nonempty():
    assert isinstance(HELP_MESSAGE, str)
    assert len(HELP_MESSAGE) > 10

def test_help_message_contains_key_instructions():
    assert "拍" in HELP_MESSAGE or "照片" in HELP_MESSAGE
    assert "產品名稱" in HELP_MESSAGE or "文字" in HELP_MESSAGE
    assert "詳細" in HELP_MESSAGE

def test_detail_triggers_unchanged():
    assert "詳細" in DETAIL_TRIGGERS
    assert "詳細分析" in DETAIL_TRIGGERS

def test_help_message_contains_no_markdown():
    assert "**" not in HELP_MESSAGE
    assert "__" not in HELP_MESSAGE
    assert not re.search(r"^#{1,6} ", HELP_MESSAGE, re.MULTILINE)
    assert "```" not in HELP_MESSAGE
