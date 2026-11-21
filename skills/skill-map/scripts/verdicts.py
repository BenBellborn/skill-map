"""Verifier verdicts on savings hints: a hint shows on the page only after an agent confirmed it against the skill's md."""
import hashlib
import json
from pathlib import Path

OK = "ok"
WRONG = "wrong"


def apply_verdicts(cache: Path, nodes: list[dict]) -> list[tuple[str, str, str]]:
    """Keeps only hints with verdict `ok`; returns each hint no verifier checked yet as (key, skill, prompt)."""
    verdicts = read_verdicts(cache)
    made: dict[str, tuple[str, str, str]] = {}
    for owner, holder in find_hint_holders(nodes):
        for hint in holder["hints"]:
            hint["key"] = build_key(hint["prompt"])
            made[hint["key"]] = (hint["key"], owner, hint["prompt"])
        holder["hints"] = [h for h in holder["hints"] if verdicts.get(h["key"]) == OK]
    # rule: verdict of hint no longer made goes; changed numbers give new prompt, new key, new check.
    write_verdicts(cache, {key: text for key, text in verdicts.items() if key in made})
    return [line for key, line in made.items() if key not in verdicts]


def find_hint_holders(nodes: list[dict]) -> list[tuple[str, dict]]:
    """Each node and its OwnMd lines, with the skill that owns them."""
    return [(node["id"].split(":")[1], holder) for node in nodes for holder in [node, *node["mds"]]]


def record_verdict(cache: Path, key: str, verdict: str, reason: str) -> None:
    verdicts = read_verdicts(cache)
    verdicts[key] = OK if verdict == OK else f"{WRONG}: {reason}"
    write_verdicts(cache, verdicts)


def build_key(prompt: str) -> str:
    return hashlib.sha1(prompt.encode()).hexdigest()[:12]


def read_verdicts(cache: Path) -> dict[str, str]:
    try:
        data = json.loads((cache / "verdicts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}


def write_verdicts(cache: Path, verdicts: dict[str, str]) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "verdicts.json").write_text(json.dumps(verdicts, indent=1), encoding="utf-8")
