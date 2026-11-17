"""Translatable messages with parameters kept separate from user data.

Messages render as English strings inside the download engine. The UI receives
the catalog key and parameters so it can change language during a download.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


DEFAULT_LANGUAGE = "en"
_ENGLISH = json.loads((Path(__file__).parent / "web" / "locales" / f"{DEFAULT_LANGUAGE}.json").read_text(encoding="utf-8"))
TEXT = SimpleNamespace(**{key: key for key in _ENGLISH})


class Message(str):
    def __new__(cls, key: str, **params):
        if isinstance(key, Message):
            key = key.key
        template = _ENGLISH.get(key, key)
        if isinstance(template, dict):
            template = template["one" if params.get("count") == 1 else "other"]
        value = super().__new__(cls, template.format(**params))
        value.key = key
        value.template = template
        value.params = params
        return value

    def __reduce__(self):
        return _restore_message, (self.key, self.params)


def _restore_message(key, params):
    return Message(key, **params)


def exception_message(error: Exception) -> str:
    if error.args and isinstance(error.args[0], Message):
        return error.args[0]
    return str(error)


def message_payload(value):
    """Convert only explicitly marked messages; titles, URLs and paths stay data."""
    if isinstance(value, Message):
        return {"message": value.key, "params": message_payload(value.params)}
    if isinstance(value, dict):
        return {key: message_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [message_payload(item) for item in value]
    return value
