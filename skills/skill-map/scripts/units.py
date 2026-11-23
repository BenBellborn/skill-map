"""Finds the map's sources: skill folders, hook commands from settings.json, mods and enabled plugins."""
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

SKIPPED_DIRS = {"synced"}
SKIPPED_MD = {"SPEC.md"}  # rebuild spec: /spec writes it, no skill loads it
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".sh", ".json", ".md"}
SKIPPED_PARTS = {"node_modules", "types", "docs", "__pycache__"}
SKIPPED_NAMES = {"tsconfig.json", "package.json", "package-lock.json"}  # build config: names no md, skill or tool
PLUGIN_META_DIR = ".claude-plugin"
HOOK_SCRIPT = re.compile(r"~/\.claude/(hooks/[\w./-]+\.(?:py|sh|js|ts))")
HOOK_TOOL = re.compile(r"command -v ([\w.-]+)")
MCP_SERVER = re.compile(r"mcp__((?:[A-Za-z0-9-]|_(?!_))+)__")
# claude.ai connectors and plugin servers have no entry in an MCP config file the map reads
CONNECTOR_PREFIXES = ("claude_ai_", "plugin_")


@dataclass
class Unit:
    """One source an agent reads into a fragment; a unit with no files (a hook that runs a tool) is drawn bare."""
    name: str
    kind: str
    folder: Path
    files: list[Path]
    label: str = ""
    events: list[str] = field(default_factory=list)
    mcp: list[str] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)  # (problem text, repair prompt): a target that is gone
    plugin: str = ""  # plugin unit that ships this skill; empty for a skill in ~/.claude/skills

    @property
    def node_id(self) -> str:
        return f"skill:{self.name}" if self.kind == "skill" else f"{self.kind}:{self.name.split('-', 1)[1]}"


def find_units(root: Path) -> dict[str, Unit]:
    units = {name: Unit(name, "skill", folder, find_md_files(folder)) for name, folder in find_skills(root).items()}
    for unit in find_hook_units(root) + find_mod_units(root) + find_plugin_units(root):
        units[unit.name] = unit
    return units


def find_skills(root: Path) -> dict[str, Path]:
    folders = sorted(p.parent for p in (root / "skills").glob("*/SKILL.md"))
    return {f.name: f for f in folders if not f.name.startswith(".") and f.name not in SKIPPED_DIRS}


def find_md_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*.md")
                  if p.name not in SKIPPED_MD and not any(part.startswith(".") for part in p.relative_to(folder).parts))


def find_hook_units(root: Path) -> list[Unit]:
    """One unit per hook script or tool; the same command under several events stays one card."""
    units: dict[str, Unit] = {}
    hooks = read_json(root / "settings.json").get("hooks")
    for event, groups in hooks.items() if isinstance(hooks, dict) else []:
        for group in groups if isinstance(groups, list) else []:
            matcher = str(group.get("matcher", ""))
            for hook in group.get("hooks", []):
                add_hook(units, root, event, matcher, str(hook.get("command", "")))
    return list(units.values())


def add_hook(units: dict[str, Unit], root: Path, event: str, matcher: str, command: str) -> None:
    script = HOOK_SCRIPT.search(command)
    if script:
        path = root / script.group(1)
        short, label, folder, files = path.stem, path.name, path.parent, [path] if path.is_file() else []
        gone = "" if files else f"missing script ~/.claude/{script.group(1)}"
    else:
        tool = HOOK_TOOL.search(command)
        tool_name = tool.group(1) if tool else (command.split() or [""])[0]
        short = tool.group(1) if tool else " ".join(command.split()[:2])
        label, folder, files = short, root / "hooks", []
        gone = "" if shutil.which(tool_name) else f"missing tool {tool_name}"
    name = f"hook-{re.sub(r'[^A-Za-z0-9_.-]+', '-', short)}"
    unit = units.setdefault(name, Unit(name, "hook", folder, files, label))
    if gone and not unit.missing:
        unit.missing.append((gone, f"Hook `{label}` in ~/.claude/settings.json runs `{gone.split(' ', 2)[2]}`, which does not "
                                   "exist, so the hook never does anything. Remove that hook from settings.json, or restore "
                                   "the file or install the tool, then run /skill-map."))
    if event not in unit.events:
        unit.events.append(event)
    unit.mcp += [s for s in MCP_SERVER.findall(matcher) if s not in unit.mcp]


def find_mod_units(root: Path) -> list[Unit]:
    folders = sorted(p.parent.parent for p in (root / "mods").glob(f"*/{PLUGIN_META_DIR}/plugin.json"))
    units = [Unit(f"mod-{f.name}", "mod", f, find_code_files(f), f.name) for f in folders]
    for unit in units:
        modules = read_json(unit.folder / "hooks" / "hooks.json").get("modules")
        for module in modules if isinstance(modules, list) else []:
            if not (unit.folder / "hooks" / str(module)).is_file():
                unit.missing.append((f"missing module {module}",
                                     f"Mod `{unit.label}` (~/.claude/mods/{unit.label}/) lists module `{module}` in "
                                     "hooks/hooks.json, which does not exist, so the mod never loads it. Fix the list or "
                                     "restore the file, then run /skill-map."))
    return units


def find_plugin_units(root: Path) -> list[Unit]:
    """Enabled plugins only; each is read at the install path the plugin list names. Each `skills/<name>/SKILL.md` of
    a plugin is its own skill unit `<plugin>:<name>`, the name a user types after `/`; the plugin unit keeps the rest."""
    enabled = read_json(root / "settings.json").get("enabledPlugins")
    installed = read_json(root / "plugins" / "installed_plugins.json").get("plugins")
    if not (isinstance(enabled, dict) and isinstance(installed, dict)):
        return []
    units = []
    for key in sorted(k for k, on in enabled.items() if on is True):
        installs, short = installed.get(key), key.split("@", 1)[0]
        first = installs[0] if isinstance(installs, list) and installs and isinstance(installs[0], dict) else {}
        folder = Path(str(first.get("installPath", "")))
        if first and folder.is_dir():
            units += build_plugin_units(folder, short)
            continue
        unit = Unit(f"plugin-{short}", "plugin", root / "plugins", [], short)
        unit.missing.append(("not installed", f"Plugin `{key}` is enabled in ~/.claude/settings.json but not installed, so "
                                              "it never runs. Install it, or remove it from enabledPlugins, then run /skill-map."))
        units.append(unit)
    return units


def build_plugin_units(folder: Path, short: str) -> list[Unit]:
    skills = sorted(p.parent for p in (folder / "skills").glob("*/SKILL.md"))
    files = [p for p in find_code_files(folder) if not any(s in p.parents for s in skills)]
    plugin = Unit(f"plugin-{short}", "plugin", folder, files, short)
    return [plugin] + [Unit(f"{short}:{s.name}", "skill", s, find_md_files(s), plugin=plugin.name) for s in skills]


def find_mcp_servers(root: Path) -> set[str]:
    """Servers of the user config file next to the root (user and project scope) and of each plugin's `.mcp.json`."""
    config = read_json(root.parent / ".claude.json")
    scopes = [config] + [p for p in (config.get("projects") or {}).values() if isinstance(p, dict)]
    servers = {name for scope in scopes if isinstance(scope.get("mcpServers"), dict) for name in scope["mcpServers"]}
    for unit in (u for u in find_plugin_units(root) if u.kind == "plugin"):
        data = read_json(unit.folder / ".mcp.json")
        servers |= set(data.get("mcpServers", data) if isinstance(data.get("mcpServers", data), dict) else {})
    return servers


def is_known_mcp_server(server: str, servers: set[str]) -> bool:
    return server in servers or server.startswith(CONNECTOR_PREFIXES)


def find_code_files(folder: Path) -> list[Path]:
    """Source and manifest files; tests, type stubs, docs and hidden folders (the plugin manifest folder aside) are skipped."""
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix in CODE_SUFFIXES and is_code_path(p.relative_to(folder)))


def is_code_path(rel: Path) -> bool:
    if any(part in SKIPPED_PARTS or (part.startswith(".") and part != PLUGIN_META_DIR) for part in rel.parts[:-1]):
        return False
    return not (rel.name.startswith("test_") or ".test." in rel.name or rel.name in SKIPPED_NAMES)


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
