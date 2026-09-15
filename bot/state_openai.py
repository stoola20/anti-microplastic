from typing import Dict, Optional

from bot import analyzer_openai

# user_id -> response id of the FULL analysis (not the text itself).
# The actual text lives server-side on OpenAI and is fetched back via
# responses.retrieve() — see get_full_analysis() below.
_store: Dict[str, Optional[str]] = {}


def save_full_analysis(user_id: str, response_id: Optional[str]) -> None:
    _store[user_id] = response_id


def get_full_analysis(user_id: str) -> Optional[str]:
    response_id = _store.get(user_id)
    if response_id is None:
        return None
    response = analyzer_openai.openai_client.responses.retrieve(response_id)
    return response.output_text


def clear_analysis(user_id: str) -> None:
    _store.pop(user_id, None)
