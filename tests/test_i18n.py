import ast
import dataclasses
import json
import pickle
import re
from pathlib import Path
from string import Formatter

from ytletolto.download_queue import ItemEvent, event_payload
from ytletolto.downloader import Status
from ytletolto.i18n import TEXT, Message, exception_message, message_payload


def test_parameterized_messages_survive_worker_transport_and_event_serialization():
    message = Message(TEXT.UNEXPECTED_ERROR, error="file {name}.mp4")
    assert message == "Unexpected error: file {name}.mp4"
    event = pickle.loads(pickle.dumps(ItemEvent(1, Status(message))))
    payload = json.loads(json.dumps(message_payload(event_payload(event))))
    assert payload["text"] == {"message": "UNEXPECTED_ERROR", "params": {"error": "file {name}.mp4"}}
    assert dataclasses.asdict(event.event)["text"] == message
    assert exception_message(ValueError(message)) is message


def test_titles_and_paths_are_not_mistaken_for_translatable_messages():
    data = {"title": "Kész", "files": ["C:/Videó/{name}.mp4"]}
    assert message_payload(data) == data


def test_shared_catalogs_have_matching_keys_and_parameters():
    locales = Path(__file__).resolve().parents[1] / "ytletolto" / "web" / "locales"
    en = json.loads((locales / "en.json").read_text(encoding="utf-8"))
    hu = json.loads((locales / "hu.json").read_text(encoding="utf-8"))
    assert en.keys() == hu.keys() == vars(TEXT).keys()
    for key, english in en.items():
        forms = english.values() if isinstance(english, dict) else [english]
        expected = {name for _, name, _, _ in Formatter().parse(hu[key]) if name is not None}
        for form in forms:
            assert {name for _, name, _, _ in Formatter().parse(form) if name is not None} == expected, key


def test_nested_messages_keep_keys_separate_from_user_data():
    message = Message(TEXT.START_TIME_BEYOND_VIDEO, title=Message(TEXT.THE_VIDEO))
    assert message_payload(message) == {
        "message": "START_TIME_BEYOND_VIDEO", "params": {"title": {"message": "THE_VIDEO", "params": {}}},
    }


def test_production_text_references_exist_in_shared_catalog():
    package = Path(__file__).resolve().parents[1] / "ytletolto"
    keys = set(vars(TEXT))
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "TEXT":
                assert node.attr in keys, (path, node.attr)
    javascript = (package / "web" / "app.js").read_text(encoding="utf-8")
    assert set(re.findall(r"\bTEXT\.([A-Z_0-9]+)", javascript)) <= keys
    html = (package / "web" / "index.html").read_text(encoding="utf-8")
    assert set(re.findall(r'data-i18n(?:-[a-z-]+)?="([A-Z_0-9]+)"', html)) <= keys
