"""SPCH-01: Snow speaks no hard-coded phrase. No allow-list, no exception.

Every ReplyDelta/ReplyFinal text must come from the LLM or the ack pool, so no such call
under src/snow may pass a string constant (empty included) or an f-string with words.
The scan walks every file, so modules added by later plans are covered automatically.
"""

import ast
import re
import tomllib

from snow.config.settings import repo_root

SPOKEN = {"ReplyDelta", "ReplyFinal"}
WORD = re.compile(r"\w")
IDENT = re.compile(r"^[a-z_]{1,24}$")
INSTRUCTION_KEYS = {"system_prompt", "ack_prompt"}


def _name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    return f.attr if isinstance(f, ast.Attribute) else None


def _is_literal_text(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        return any(
            isinstance(v, ast.Constant)
            and isinstance(v.value, str)
            and WORD.search(v.value)
            for v in node.values
        )
    return False


def violations(source: str, filename: str = "<src>") -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and _name(node) in SPOKEN):
            continue
        text = [k.value for k in node.keywords if k.arg == "text"]
        if not text and node.args:
            text = [node.args[0]]
        if any(_is_literal_text(t) for t in text):
            found.append(f"{filename}:{node.lineno} {_name(node)}")
    return found


def test_the_scanner_catches_literals_and_allows_variables() -> None:
    assert violations('ReplyFinal(text="Sir?")')
    assert violations('ReplyDelta(text="")')
    assert violations('ReplyDelta("hello")')
    assert violations('events.ReplyFinal(text=f"Sorry {x}")')
    assert not violations("ReplyFinal(text=reply)")
    assert not violations("ReplyDelta(text=ack.text)")
    assert not violations('ReplyFinal(emotion="neutral", reply_source="fallback")')
    assert not violations('ReplyDelta(text=f"{piece}")')


def test_no_spoken_text_in_src_is_a_literal() -> None:
    root = repo_root() / "src" / "snow"
    files = sorted(root.rglob("*.py"))
    assert files
    found = [
        v
        for path in files
        for v in violations(path.read_text(encoding="utf-8"), str(path))
    ]
    assert found == []


def test_persona_file_holds_only_instructions_and_identifiers() -> None:
    data = tomllib.loads(
        (repo_root() / "config" / "persona.toml").read_text(encoding="utf-8")
    )
    for key, value in data.items():
        if key in INSTRUCTION_KEYS:
            assert isinstance(value, str) and value
        elif isinstance(value, (int, float)):
            continue
        elif isinstance(value, str):
            assert IDENT.match(value), f"{key}: not a short identifier"
        else:
            assert isinstance(value, list), key
            assert all(isinstance(i, str) and IDENT.match(i) for i in value), key  # pyright: ignore[reportUnknownVariableType]


def test_instruction_prompts_are_read_only_by_their_builders() -> None:
    root = repo_root() / "src" / "snow"
    allowed = {
        "system_prompt": {"persona.py", "acks.py"},
        "ack_prompt": {"acks.py"},
    }
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for key, names in allowed.items():
            if re.search(rf"\.{key}\b", text) and path.name not in names:
                raise AssertionError(f"{path} reads {key}")
