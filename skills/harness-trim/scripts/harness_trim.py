#!/usr/bin/env python3
"""harness-trim: load only the ECC skills and agents you actually use.

ECC (ecc@ecc) ships 400+ skills and 70+ agents; every description is injected into
every Claude Code session (~35k tokens). Claude Code cannot hide individual plugin
components, so this script:

  * keeps the ECC plugin installed but DISABLED (its marketplace clone is the library),
  * symlinks a small DAILY set of ECC skills/agents into ~/.claude/skills and ~/.claude/agents,
  * picks that set from baseline.json + pins + anything your transcripts show you invoked
    at least N times in the last D days, minus bans and name collisions,
  * can flip back to LIBRARY mode (plugin enabled, links removed) in one command.

Only symlinks that resolve inside the ECC marketplace directory are ever touched.
"""
import argparse, json, os, re, shutil, subprocess, sys, time
from collections import Counter
from pathlib import Path

HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
LIB = HOME / "plugins" / "marketplaces" / "ecc"
SKILLS_DIR, AGENTS_DIR = HOME / "skills", HOME / "agents"
STATE_DIR = HOME / "harness-trim"
STATE, CONFIG = STATE_DIR / "state.json", STATE_DIR / "config.json"
PLUGIN_ID = "ecc@ecc"
HERE = Path(__file__).resolve().parent
BASELINE = HERE.parent / "baseline.json"

SKILL_RE = re.compile(r'"name"\s*:\s*"Skill"\s*,\s*"input"\s*:\s*\{[^{}]*?"skill"\s*:\s*"([^"]+)"')
CMD_RE = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
AGENT_RE = re.compile(r'"subagent_type"\s*:\s*"([^"]+)"')
FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def norm(name):
    return name.split(":", 1)[1] if name.startswith("ecc:") else name


def lib_skills():
    return {p.name for p in (LIB / "skills").iterdir() if (p / "SKILL.md").is_file()} if (LIB / "skills").is_dir() else set()


def lib_agents():
    return {p.stem for p in (LIB / "agents").glob("*.md")} if (LIB / "agents").is_dir() else set()


def frontmatter(path):
    m = FM_RE.match(Path(path).read_text(errors="ignore"))
    out = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def est_tokens(path):
    fm = frontmatter(path)
    return (len(fm.get("name", "")) + len(fm.get("description", "")) + 12) // 4


def scan_usage(days):
    cutoff = time.time() - days * 86400
    skills, agents = Counter(), Counter()
    for f in (HOME / "projects").glob("*/*.jsonl"):
        try:
            if f.stat().st_mtime < cutoff:
                continue
            with open(f, errors="ignore") as fh:
                for line in fh:
                    if '"Skill"' in line or "command-name" in line:
                        for m in SKILL_RE.finditer(line):
                            skills[norm(m.group(1))] += 1
                        for m in CMD_RE.finditer(line):
                            skills[norm(m.group(1))] += 1
                    if "subagent_type" in line:
                        for m in AGENT_RE.finditer(line):
                            agents[norm(m.group(1))] += 1
        except OSError:
            continue
    return skills, agents


def managed(link, root):
    """True if `link` is a symlink that resolves inside the ECC library."""
    try:
        return link.is_symlink() and str(link.resolve()).startswith(str(root.resolve()))
    except OSError:
        return False


def plugin_enabled():
    s = load_json(HOME / "settings.json", {})
    return bool((s.get("enabledPlugins") or {}).get(PLUGIN_ID))


def claude(*args):
    exe = shutil.which("claude")
    if not exe:
        print(f"  ! claude CLI not on PATH; run manually: claude {' '.join(args)}")
        return False
    r = subprocess.run([exe, *args], capture_output=True, text=True)
    if r.returncode:
        print(f"  ! claude {' '.join(args)} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.returncode == 0


def decide(days, min_uses):
    base, cfg = load_json(BASELINE, {}), load_json(CONFIG, {})
    used_s, used_a = scan_usage(days)
    ls, la = lib_skills(), lib_agents()
    plugin_skill_names = {p.name for p in (HERE.parent.parent).iterdir() if p.is_dir()}  # this plugin's own skills
    bans = set(base.get("collisions", [])) | set(cfg.get("ban", [])) | plugin_skill_names
    keep_s = (set(base.get("skills", [])) | set(cfg.get("pin", []))
              | {s for s, c in used_s.items() if c >= min_uses}) & ls
    keep_s -= bans
    keep_a = (set(base.get("agents", [])) | set(cfg.get("pin_agents", []))
              | {a for a, c in used_a.items() if c >= min_uses}) & la
    keep_a -= set(cfg.get("ban_agents", []))
    return keep_s, keep_a, used_s, used_a, ls, la, bans


def link_set(dir_, names, src_fn, dst_fn):
    dir_.mkdir(parents=True, exist_ok=True)
    added, removed, skipped = [], [], []
    for p in dir_.iterdir():
        if managed(p, LIB) and dst_fn(p) not in names:
            p.unlink(); removed.append(dst_fn(p))
    for n in sorted(names):
        dst, src = dir_ / (n if dir_ == SKILLS_DIR else f"{n}.md"), src_fn(n)
        if dst.exists() or dst.is_symlink():
            if managed(dst, LIB):
                continue
            skipped.append(n); continue  # user's own file with this name: never overwrite
        dst.symlink_to(src); added.append(n)
    return added, removed, skipped


def cmd_report(a):
    keep_s, keep_a, used_s, used_a, ls, la, bans = decide(a.days, a.min_uses)
    full = sum(est_tokens(LIB / "skills" / s / "SKILL.md") for s in ls) + sum(est_tokens(LIB / "agents" / f"{x}.md") for x in la)
    kept = sum(est_tokens(LIB / "skills" / s / "SKILL.md") for s in keep_s) + sum(est_tokens(LIB / "agents" / f"{x}.md") for x in keep_a)
    st = load_json(STATE, {})
    print(f"ECC library: {LIB}  ({len(ls)} skills, {len(la)} agents)")
    print(f"Mode: {'library (plugin enabled)' if plugin_enabled() else 'daily (plugin disabled)'}; last apply: {st.get('last_apply_iso', 'never')}")
    print(f"\nUsage in last {a.days} days (ECC items only):")
    rows = [(s, c) for s, c in used_s.most_common() if s in ls] + [(f"agent:{x}", c) for x, c in used_a.most_common() if x in la]
    print("  " + ("\n  ".join(f"{c:>4}  {n}" for n, c in rows) if rows else "none recorded"))
    print(f"\nDaily set would be {len(keep_s)} skills + {len(keep_a)} agents  (~{kept:,} always-on tokens vs ~{full:,} for the full plugin)")
    print("  skills: " + ", ".join(sorted(keep_s)))
    print("  agents: " + ", ".join(sorted(keep_a)))
    stale = [s for s in used_s if s in ls and s in bans]
    if stale:
        print("  banned/colliding but used: " + ", ".join(stale))


def cmd_apply(a):
    st = load_json(STATE, {})
    if a.if_stale is not None:
        if not st or st.get("mode") != "daily":
            return  # never auto-trim before the user opted in, or while they chose library mode
        if time.time() - st.get("last_apply", 0) < a.if_stale * 86400:
            return
    if not (LIB / "skills").is_dir():
        sys.exit(f"ECC library not found at {LIB}. Install ecc@ecc first (it may stay disabled).")
    keep_s, keep_a, *_ = decide(a.days, a.min_uses)
    add_s, rm_s, skip_s = link_set(SKILLS_DIR, keep_s, lambda n: LIB / "skills" / n, lambda p: p.name)
    add_a, rm_a, skip_a = link_set(AGENTS_DIR, keep_a, lambda n: LIB / "agents" / f"{n}.md", lambda p: p.stem)
    disabled = False
    if plugin_enabled() and a.if_stale is None:
        disabled = claude("plugin", "disable", PLUGIN_ID)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"mode": "daily", "last_apply": time.time(),
                                 "last_apply_iso": time.strftime("%Y-%m-%d %H:%M"),
                                 "skills": sorted(keep_s), "agents": sorted(keep_a)}, indent=1))
    changed = add_s or rm_s or add_a or rm_a or disabled
    if a.quiet and not changed:
        return
    print(f"harness-trim: daily mode, {len(keep_s)} skills + {len(keep_a)} agents linked"
          f"{'; ecc@ecc disabled' if disabled else ''}")
    for label, items in (("+ skills", add_s), ("- skills", rm_s), ("+ agents", add_a), ("- agents", rm_a)):
        if items:
            print(f"  {label}: {', '.join(items)}")
    for label, items in (("skipped (your own skill has this name)", skip_s), ("skipped agents", skip_a)):
        if items:
            print(f"  {label}: {', '.join(items)}")
    if not a.quiet:
        print("  Restart Claude Code (or start a new session) to pick up the change.")


def cmd_library(a):
    _, rm_s, _ = link_set(SKILLS_DIR, set(), None, lambda p: p.name)
    _, rm_a, _ = link_set(AGENTS_DIR, set(), None, lambda p: p.stem)
    ok = claude("plugin", "enable", PLUGIN_ID)
    st = load_json(STATE, {}); st.update({"mode": "library", "last_apply": time.time(),
                                          "last_apply_iso": time.strftime("%Y-%m-%d %H:%M")})
    STATE_DIR.mkdir(parents=True, exist_ok=True); STATE.write_text(json.dumps(st, indent=1))
    print(f"harness-trim: library mode. Removed {len(rm_s)} skill links, {len(rm_a)} agent links"
          f"{'; ecc@ecc enabled' if ok else ''}. Run `apply` to go back to daily mode.")


def cmd_add(a):
    ls, la = lib_skills(), lib_agents()
    SKILLS_DIR.mkdir(parents=True, exist_ok=True); AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    for n in a.names:
        if n in ls:
            dst = SKILLS_DIR / n
            if not dst.exists() and not dst.is_symlink():
                dst.symlink_to(LIB / "skills" / n); print(f"  linked skill {n}")
            else:
                print(f"  skill {n} already present")
        elif n in la:
            dst = AGENTS_DIR / f"{n}.md"
            if not dst.exists() and not dst.is_symlink():
                dst.symlink_to(LIB / "agents" / f"{n}.md"); print(f"  linked agent {n}")
            else:
                print(f"  agent {n} already present")
        else:
            print(f"  ! {n} not found in the ECC library")
    if a.pin:
        _edit_cfg("pin", [n for n in a.names if n in ls]); _edit_cfg("pin_agents", [n for n in a.names if n in la])
    print("  (links added for now; next `apply` drops anything not pinned, in the baseline, or used enough)")


def _edit_cfg(key, names, remove=False):
    cfg = load_json(CONFIG, {})
    cur = set(cfg.get(key, []))
    cur = cur - set(names) if remove else cur | set(names)
    cfg[key] = sorted(cur)
    STATE_DIR.mkdir(parents=True, exist_ok=True); CONFIG.write_text(json.dumps(cfg, indent=1))
    print(f"  {key}: {', '.join(cfg[key]) or '(empty)'}")


def cmd_pin(a):
    la = lib_agents()
    _edit_cfg("pin", [n for n in a.names if n not in la], remove=a.remove)
    if any(n in la for n in a.names):
        _edit_cfg("pin_agents", [n for n in a.names if n in la], remove=a.remove)


def cmd_ban(a):
    la = lib_agents()
    _edit_cfg("ban", [n for n in a.names if n not in la], remove=a.remove)
    if any(n in la for n in a.names):
        _edit_cfg("ban_agents", [n for n in a.names if n in la], remove=a.remove)


def main():
    base = load_json(BASELINE, {})
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("report", cmd_report), ("apply", cmd_apply)):
        s = sub.add_parser(name); s.set_defaults(fn=fn)
        s.add_argument("--days", type=int, default=base.get("usage_window_days", 30))
        s.add_argument("--min-uses", type=int, default=base.get("min_uses_to_add", 2))
        if name == "apply":
            s.add_argument("--if-stale", type=int, metavar="DAYS", help="only re-apply if the last apply is older than DAYS and mode is daily (for hooks)")
            s.add_argument("--quiet", action="store_true")
    s = sub.add_parser("library", help="re-enable the full ECC plugin and remove daily links"); s.set_defaults(fn=cmd_library)
    s = sub.add_parser("add", help="link one or more library skills/agents right now"); s.set_defaults(fn=cmd_add)
    s.add_argument("names", nargs="+"); s.add_argument("--pin", action="store_true", help="also keep them across future applies")
    for name, fn in (("pin", cmd_pin), ("ban", cmd_ban)):
        s = sub.add_parser(name); s.set_defaults(fn=fn); s.add_argument("names", nargs="+"); s.add_argument("--remove", action="store_true")
    a = p.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
