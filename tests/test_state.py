from bot.state import save_full_analysis, get_full_analysis, clear_analysis

def test_save_and_get():
    save_full_analysis("user_123", "full analysis text")
    assert get_full_analysis("user_123") == "full analysis text"

def test_get_missing_returns_none():
    assert get_full_analysis("nonexistent_user") is None

def test_overwrite():
    save_full_analysis("user_123", "old")
    save_full_analysis("user_123", "new")
    assert get_full_analysis("user_123") == "new"

def test_clear():
    save_full_analysis("user_abc", "data")
    clear_analysis("user_abc")
    assert get_full_analysis("user_abc") is None
