"""CLI of /skill-map: `scan` lists stale unit fragments (skills, hooks, mods, plugins), `render` writes and opens the HTML map, `verdict` records a
verifier's check of one savings hint."""
import argparse
import hashlib
import json
import sys
import time
import webbrowser
from pathlib import Path

import cost
import graph
import layout
import verdicts
from units import Unit, find_units

CLAUDE_DIR = Path.home() / ".claude"
TEMPLATE = Path(__file__).with_name("template.html")
BROKEN_LWT = "broken"
NO_FRAGMENT = "no fragment, run scan"
CHANGED = "changed since the map was drawn"
STALE_TEXTS = {NO_FRAGMENT, CHANGED}


def run_cli(argv: list[str]) -> int:
    args = parse_args(argv)
    root, cache = Path(args.root), Path(args.cache) if args.cache else Path(args.root) / "cache" / "skill-map"
    if args.command == "scan":
        return run_scan(root, cache, args.full)
    if args.command == "verdict":
        return run_verdict(cache, args.rest)
    return run_render(root, cache, not args.no_open)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="skillmap")
    parser.add_argument("command", choices=["scan", "render", "verdict"])
    parser.add_argument("rest", nargs="*", help="verdict: <key> ok | <key> wrong <reason>")
    parser.add_argument("--root", default=str(CLAUDE_DIR))
    parser.add_argument("--cache", default="")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    return parser.parse_args(argv)


def run_scan(root: Path, cache: Path, full: bool) -> int:
    """Each stale line hands its agent the file digest and the scan time as `lwt`, so an edit during extraction stays stale.
    A unit with no files (a hook that runs a tool) has nothing to read and never shows."""
    scanned = time.time_ns()
    units = find_units(root)
    delete_removed_fragments(cache, units)
    stale = [u for u in units.values() if u.files and (full or is_stale(root, cache, u))]
    for unit in stale:
        files = ",".join(p.relative_to(unit.folder).as_posix() for p in unit.files)
        print(f"{unit.name}\t{build_lwt(unit)}@{scanned}\t{files}\t{unit.kind}\t{unit.folder.as_posix()}")
    if not stale:
        print("none")
    return 0


def delete_removed_fragments(cache: Path, units: dict[str, Unit]) -> None:
    for path in (cache / "skills").glob("*.json"):
        if path.stem not in units:
            path.unlink()


def is_stale(root: Path, cache: Path, unit: Unit) -> bool:
    """An agent type file newer than the scan time changed after extraction began, whenever the fragment was written."""
    data = load_fragment(root, cache, unit)
    if data is None:
        return True
    digest, scanned = split_lwt(data)
    return digest != build_lwt(unit) or any(p.stat().st_mtime_ns > scanned for p in find_agent_files(root, data))


def load_fragment(root: Path, cache: Path, unit: Unit) -> dict | None:
    """A fragment with no `lwt` key, written after every file it reads, gets the current `lwt`: no agent needed."""
    data = read_fragment(cache, unit.name)
    if data is None or "lwt" in data:
        return data
    path = get_fragment_path(cache, unit.name)
    written = path.stat().st_mtime_ns
    if all(p.stat().st_mtime_ns <= written for p in unit.files + find_agent_files(root, data)):
        data["lwt"] = f"{build_lwt(unit)}@{written}"
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


def split_lwt(data: dict) -> tuple[str, int]:
    """`lwt` is `<md digest>@<scan time ns>`; one with no scan time counts as scanned before every file."""
    digest, _, scanned = str(data.get("lwt")).partition("@")
    return digest, int(scanned) if scanned.isdigit() else -1


def read_fragment(cache: Path, name: str) -> dict | None:
    try:
        data = json.loads(get_fragment_path(cache, name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def get_fragment_path(cache: Path, name: str) -> Path:
    return cache / "skills" / f"{name}.json"


def build_lwt(unit: Unit) -> str:
    digest = hashlib.sha1()
    for path in unit.files:
        stat = path.stat()
        digest.update(f"{path.relative_to(unit.folder).as_posix()}|{stat.st_mtime_ns}|{stat.st_size}\n".encode())
    return digest.hexdigest()


def find_agent_files(root: Path, data: dict) -> list[Path]:
    """Agent type files feed a fragment's agent loads but sit outside the skill folder."""
    agents = data.get("agents") if isinstance(data.get("agents"), list) else []
    types = {a.get("type") for a in agents if isinstance(a, dict) and isinstance(a.get("type"), str)}
    return [p for p in (root / "agents" / f"{t}.md" for t in sorted(types)) if p.is_file()]


def run_render(root: Path, cache: Path, open_page: bool) -> int:
    units = find_units(root)
    fragments, problems = load_fragments(root, cache, units)
    data = graph.build_graph(root, units, fragments)
    problems += data["problems"]
    clear_lwt(cache, fragments, {skill for skill, _ in problems})
    # rule: stale skill is no page fix: /skill-map re-reads it before render; only CLI prints it.
    data["problems"] = [build_problem(skill, text) for skill, text in problems if text not in STALE_TEXTS]
    missing = data.pop("missing")
    data["problems"] += missing
    cost.apply_cost(data)
    unchecked = verdicts.apply_verdicts(cache, data["nodes"])
    layout.apply_layout(data)
    page = cache / "skill-map.html"
    page.write_text(build_page(data), encoding="utf-8")
    if open_page:
        webbrowser.open(page.resolve().as_uri())
    print_report(page, unchecked, problems, missing)
    return 1 if problems else 0


def print_report(page: Path, unchecked: list[tuple[str, str, str]], problems: list[tuple[str, str]],
                 missing: list[dict]) -> None:
    """`missing:` lines name a target that is gone; a re-read cannot fix them, so they never set the exit code."""
    print(page)
    for key, skill, prompt in unchecked:
        print(f"unchecked hint: {key}\t{skill}\t{prompt}")
    for skill, text in problems:
        print(f"problem: {skill}: {text}")
    for m in missing:
        print(f"missing: {m['skill']}: {m['text']}")


def run_verdict(cache: Path, rest: list[str]) -> int:
    if len(rest) < 2 or rest[1] not in (verdicts.OK, verdicts.WRONG) or (rest[1] == verdicts.WRONG) == (len(rest) == 2):
        print("usage: verdict <key> ok | verdict <key> wrong <reason>")
        return 2
    verdicts.record_verdict(cache, rest[0], rest[1], " ".join(rest[2:]))
    return 0


def build_problem(skill: str, text: str) -> dict:
    """The prompt tells an AI what to repair: a wrong ref sits in the skill's own md; any other problem clears on a re-read."""
    if text.startswith("unknown "):
        _, kind, ref = text.split(" ", 2)
        prompt = (f"Skill `{skill}` (~/.claude/skills/{skill}/) names {kind} `{ref}`, which does not exist. Fix that name in "
                  f"its md files so it points at an existing {'file' if kind == 'md' else 'skill'}, then run /skill-map.")
    else:
        prompt = f"Run /skill-map: the map data of skill `{skill}` is malformed ({text}); the run reads the skill again."
    return {"skill": skill, "text": text, "prompt": prompt}


def load_fragments(root: Path, cache: Path, units: dict[str, Unit]) -> tuple[dict[str, dict], list[tuple[str, str]]]:
    cache.mkdir(parents=True, exist_ok=True)
    fragments, problems = {}, []
    for unit in (u for u in units.values() if u.files):
        data = load_fragment(root, cache, unit)
        if data is None:
            problems.append((unit.name, NO_FRAGMENT))
            continue
        if split_lwt(data)[0] != build_lwt(unit):
            problems.append((unit.name, CHANGED))
        fragments[unit.name] = data
    return fragments, problems


def clear_lwt(cache: Path, fragments: dict[str, dict], broken: set[str]) -> None:
    """A fragment with a problem gets `lwt` `broken`, never a missing one, so scan hands it to an agent, not a fresh stamp."""
    for name in broken & fragments.keys():
        if fragments[name].get("lwt") != BROKEN_LWT:
            fragments[name]["lwt"] = BROKEN_LWT
            get_fragment_path(cache, name).write_text(json.dumps(fragments[name], indent=1), encoding="utf-8")


def build_page(data: dict) -> str:
    payload = json.dumps(data).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/", payload)


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
