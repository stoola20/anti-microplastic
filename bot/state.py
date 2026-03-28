from typing import Dict, Optional

_store: Dict[str, str] = {}

def save_full_analysis(user_id: str, analysis: str) -> None:
    _store[user_id] = analysis

def get_full_analysis(user_id: str) -> Optional[str]:
    return _store.get(user_id)

def clear_analysis(user_id: str) -> None:
    _store.pop(user_id, None)
