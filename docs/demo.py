"""Builds the README demo map from a made-up skill set, so no real skill shows.

Usage: python docs/demo.py <work folder>
Writes <work folder>/cache/skill-map.html. Take the picture with a headless browser, e.g.
msedge --headless --window-size=1600,900 --screenshot=docs/demo.png <work folder>/cache/skill-map.html
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/skill-map/scripts"))
import skillmap  # noqa: E402

SKILLS = {
    "release": "release skill " * 300,
    "review": "review skill " * 500,
    "ship-pr": "ship skill " * 200,
    "style-guide": "style rules " * 900,
}
FILES = {
    "skills/release/reference/checklist.md": "check " * 400,
    "skills/review/reference/angles.md": "angle " * 700,
    "reference/commit-rules.md": "rule " * 300,
    "agents/review-finder.md": "finder " * 50,
}


def fragment(skill: str, **fields) -> dict:
    return {"skill": skill, "kind": "command", "summary": "", "args": [], "loads": [], "calls": [], "agents": [], **fields}


FRAGMENTS = [
    fragment("release", summary="tags, builds and publishes a version",
             args=[{"id": "hotfix", "label": "hotfix", "note": "skips review"}],
             loads=[{"md": "style-guide", "when": "always"},
                    {"md": "reference/checklist.md", "when": "before tag"},
                    {"md": "~/.claude/reference/commit-rules.md", "when": "commit"}],
             calls=[{"skill": "review", "callArgs": "branch", "when": "not hotfix"},
                    {"skill": "tool:git", "when": "tag"}],
             agents=[{"id": "checker", "type": "", "model": "sonnet", "effort": "medium", "count": "3",
                      "items": "1", "when": "build", "loads": [{"md": "reference/checklist.md"}]}]),
    fragment("review", summary="finds bugs in a diff, one finder per angle",
             args=[{"id": "branch", "label": "branch", "note": "whole branch"}],
             loads=[{"md": "style-guide", "when": "always"}, {"md": "reference/angles.md", "when": "step 1"}],
             calls=[{"skill": "builtin:code-review", "when": "second opinion"}],
             agents=[{"id": "finder", "type": "review-finder", "model": "opus", "effort": "high", "count": "4",
                      "items": "1", "loads": [{"md": "reference/angles.md"}]}]),
    fragment("ship-pr", summary="commits, pushes and opens a pull request",
             loads=[{"md": "~/.claude/reference/commit-rules.md", "when": "commit"}],
             calls=[{"skill": "review", "when": "before push"}, {"skill": "tool:gh", "when": "open PR"}]),
    fragment("style-guide", kind="shared", summary="code style rules every skill loads"),
]


def build(work: Path) -> Path:
    root, cache = work / "claude", work / "cache"
    for name, text in SKILLS.items():
        write(root / "skills" / name / "SKILL.md", text)
    for path, text in FILES.items():
        write(root / path, text)
    for data in FRAGMENTS:
        write(cache / "skills" / f"{data['skill']}.json", json.dumps(data))
    stamp(root, cache)
    render = ["render", "--root", str(root), "--cache", str(cache), "--no-open"]
    for line in capture(render).splitlines():  # acts as the verifier agents: every demo hint is ok
        if line.startswith("unchecked hint: "):
            capture(["verdict", line.removeprefix("unchecked hint: ").split("\t")[0], "ok", "--cache", str(cache)])
    capture(render)
    return cache / "skill-map.html"


def capture(argv: list[str]) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        skillmap.run_cli(argv)
    return out.getvalue()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def stamp(root: Path, cache: Path) -> None:
    """Acts as the extract agents: copies each stale unit's `lwt` from `scan` into its fragment."""
    for line in capture(["scan", "--root", str(root), "--cache", str(cache)]).splitlines():
        name, lwt = (line.split("\t") + [""])[:2]
        path = cache / "skills" / f"{name}.json"
        if path.is_file():
            path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "lwt": lwt}), encoding="utf-8")


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
