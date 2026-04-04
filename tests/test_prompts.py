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

from bot.prompts import SYSTEM_PROMPT

def test_system_prompt_includes_clothing_category():
    """類別C 定義存在於 prompt 中"""
    assert "類別C" in SYSTEM_PROMPT
    assert "衣物" in SYSTEM_PROMPT

def test_system_prompt_clothing_edc_chemicals():
    """衣物 EDC 化學品關鍵字都存在"""
    assert "PFAS" in SYSTEM_PROMPT or "全氟" in SYSTEM_PROMPT
    assert "甲醛" in SYSTEM_PROMPT
    assert "偶氮" in SYSTEM_PROMPT
    assert "鄰苯二甲酸酯" in SYSTEM_PROMPT or "Phthalates" in SYSTEM_PROMPT

def test_system_prompt_clothing_in_relevance_scope():
    """相關性判斷區塊包含衣物"""
    assert "衣物" in SYSTEM_PROMPT

def test_system_prompt_clothing_brief_format():
    """BRIEF 輸出格式包含類別C"""
    assert "類別C" in SYSTEM_PROMPT

def test_help_message_mentions_clothing():
    """HELP_MESSAGE 包含衣物查詢說明"""
    assert "衣物" in HELP_MESSAGE or "服裝" in HELP_MESSAGE or "材質" in HELP_MESSAGE
