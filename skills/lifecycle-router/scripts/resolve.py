#!/usr/bin/env python3
"""lifecycle-router: decide which installed skill or agent handles a lifecycle capability.

Precedence (lower tier wins in auto mode):
  0 explicit override           (project .claude/de-product-lifecycle.json, then ~/.claude/de-product-lifecycle/config.json)
  1 project                     (.claude/skills, .claude/agents in the working directory)
  2 user, own files             (~/.claude/skills, ~/.claude/agents that are not ECC links)
  3 user, ECC daily links       (symlinks harness-trim made into the ECC library)
  4 other enabled plugins       (anything but this plugin)
  5 Claude Code built-ins       (named in lifecycle.json; assumed present, cannot be scanned)
  6 ECC library, not loaded     (shown as an option; needs `harness_trim.py add <name>`)
  7 this plugin's fallback flow

Modes: `ask` (default) prints the ranked options for the user to choose; `auto` names the pick.
The user's own tools always outrank this plugin's, without configuration.
"""
import argparse, json, os, re, sys, time
from pathlib import Path

HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent.parent.parent
CONTRACT = PLUGIN_ROOT / "lifecycle.json"
THIS_PLUGIN = "de-product-lifecycle"
ECC_LIB = HOME / "plugins" / "marketplaces" / "ecc"
USER_CFG = HOME / THIS_PLUGIN / "config.json"
DECISIONS = HOME / THIS_PLUGIN / "decisions.jsonl"
HARNESS_TRIM = PLUGIN_ROOT / "skills" / "harness-trim" / "scripts" / "harness_trim.py"
TIER_LABEL = {0: "override", 1: "project", 2: "user", 3: "ecc-daily", 4: "plugin", 5: "builtin", 6: "ecc-library, not loaded", 7: "fallback"}


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def frontmatter(path):
    try:
        t = Path(path).read_text(errors="ignore")
    except OSError:
        return {}
    if not t.startswith("---"):
        return {}
    body = t.split("---", 2)
    out, key = {}, None
    if len(body) >= 3:
        for line in body[1].splitlines():
            if line[:1] in (" ", "\t") and key:
                out[key] = (out[key] + " " + line.strip()).strip()
            elif ":" in line and not line.startswith("-"):
                k, v = line.split(":", 1)
                key, v = k.strip(), v.strip().strip('"').strip("'")
                out[key] = "" if v in (">-", ">", "|", "|-") else v
            else:
                key = None
    return out


def project_root():
    cwd = Path.cwd()
    for p in (cwd, *cwd.parents):
        if (p / ".git").exists() or (p / ".claude").is_dir():
            return p
    return cwd


def project_cfg():
    return load_json(project_root() / ".claude" / f"{THIS_PLUGIN}.json", {})


def mode():
    for cfg in (project_cfg(), load_json(USER_CFG, {})):
        if cfg.get("mode") in ("ask", "auto"):
            return cfg["mode"]
    return load_json(CONTRACT, {}).get("default_mode", "ask")


def overrides():
    o = dict(load_json(USER_CFG, {}).get("overrides", {}))
    o.update(project_cfg().get("overrides", {}))
    return o


def is_ecc_link(p):
    try:
        return p.is_symlink() and str(p.resolve()).startswith(str(ECC_LIB.resolve()))
    except OSError:
        return False


def add_entries(inv, skills_dir, agents_dir, tier, plugin=None, exclude=()):
    if skills_dir.is_dir():
        for d in sorted(skills_dir.iterdir()):
            f = d / "SKILL.md"
            if f.is_file() and d.name not in exclude:
                t = 3 if tier == 2 and is_ecc_link(d) else tier
                fm = frontmatter(f)
                inv.append({"type": "skill", "name": fm.get("name") or d.name, "tier": t, "plugin": plugin,
                            "path": str(f), "description": fm.get("description", "")})
    if agents_dir.is_dir():
        for f in sorted(agents_dir.glob("*.md")):
            if f.stem in exclude:
                continue
            t = 3 if tier == 2 and is_ecc_link(f) else tier
            fm = frontmatter(f)
            inv.append({"type": "agent", "name": fm.get("name") or f.stem, "tier": t, "plugin": plugin,
                        "path": str(f), "description": fm.get("description", "")})


def inventory():
    inv = []
    pr = project_root()
    add_entries(inv, pr / ".claude" / "skills", pr / ".claude" / "agents", 1)
    add_entries(inv, HOME / "skills", HOME / "agents", 2)
    enabled = {}
    for s in (HOME / "settings.json", pr / ".claude" / "settings.json", pr / ".claude" / "settings.local.json"):
        enabled.update(load_json(s, {}).get("enabledPlugins") or {})
    installed = load_json(HOME / "plugins" / "installed_plugins.json", {}).get("plugins", {})
    for pid, on in enabled.items():
        if not on or pid.split("@")[0] == THIS_PLUGIN:
            continue
        for rec in installed.get(pid, []):
            root = Path(rec.get("installPath", ""))
            add_entries(inv, root / "skills", root / "agents", 4, plugin=pid)
    # this plugin's own skills are fallbacks (tier 7), whether installed or run from a checkout
    own = PLUGIN_ROOT
    for rec in installed.get(f"{THIS_PLUGIN}@{THIS_PLUGIN}", []):
        if Path(rec.get("installPath", "")).is_dir():
            own = Path(rec["installPath"])
    add_entries(inv, own / "skills", own / "agents", 7, plugin=THIS_PLUGIN)
    if not enabled.get("ecc@ecc") and ECC_LIB.is_dir():
        loaded = {(e["type"], e["name"]) for e in inv if e["tier"] == 3}
        lib = []
        add_entries(lib, ECC_LIB / "skills", ECC_LIB / "agents", 6, plugin="ecc (library)")
        inv.extend(e for e in lib if (e["type"], e["name"]) not in loaded)
    return inv


def resolve(cap_name, task=""):
    contract = load_json(CONTRACT, {})
    cap = contract.get("capabilities", {}).get(cap_name)
    if not cap:
        sys.exit(f"unknown capability {cap_name!r}; run `capabilities`")
    inv = inventory()
    by_key = {}
    for e in inv:
        by_key.setdefault((e["type"], e["name"]), []).append(e)
    cands, seen = [], set()

    def push(e, why, score):
        k = (e["type"], e["name"], e["tier"])
        if k not in seen:
            seen.add(k); cands.append({**e, "why": why, "score": score})

    def norm(s):
        return " " + re.sub(r"[-_/]+", " ", s.lower()) + " "

    ov = overrides().get(cap_name)
    if ov and ":" in ov:
        t, n = ov.split(":", 1)
        for e in by_key.get((t, n), []):
            push({**e, "tier": 0}, "explicit override", 0)
        if not by_key.get((t, n)):
            cands.append({"type": t, "name": n, "tier": 0, "plugin": None, "path": "", "description": "",
                          "why": "override points at something not installed", "dangling": True, "score": 0})
    for kp in cap.get("known_providers", []):
        hits = by_key.get((kp["type"], kp["name"]), [])
        if hits:
            for e in hits:
                push(e, f"known provider ({kp.get('source', '?')})", 1)
        elif kp.get("source") == "builtin":
            cands.append({"type": kp["type"], "name": kp["name"], "tier": 5, "plugin": "claude-code", "path": "",
                          "description": "Claude Code built-in (assumed available; cannot be scanned)", "why": "known built-in"})
    kws = [norm(k).strip() for k in cap.get("keywords", [])]
    for e in inv:
        if e["tier"] == 7 and not (fb0 := cap.get("fallback")) or (e["tier"] == 7 and (e["type"], e["name"]) != (fb0["type"], fb0["name"])):
            continue  # this plugin's other skills never sneak in by keyword
        text = norm(e["name"] + " " + e["description"])
        hits = sum(1 for k in kws if f" {k} " in text or k in norm(e["name"]))
        need = 2 if e["tier"] == 6 else 1
        if hits >= need:
            push(e, f"description matches {hits} capability keyword(s)", 2)
    fb = cap.get("fallback")
    if fb:
        hits = [e for e in by_key.get((fb["type"], fb["name"]), []) if e["tier"] == 7]
        if hits:
            for e in hits:
                push(e, "this plugin's fallback" + (f": {fb['note']}" if fb.get("note") else ""), 3)
        else:
            cands.append({"type": fb["type"], "name": fb["name"], "tier": 7, "plugin": THIS_PLUGIN, "path": "",
                          "description": fb.get("note", ""), "why": "fallback, NOT BUILT YET" if fb.get("planned") else "fallback (missing from plugin?)",
                          "planned": bool(fb.get("planned")), "score": 3})
    cands.sort(key=lambda c: (c["tier"], c.get("score", 2), c["type"] != "skill", c["name"]))
    return cap, cands


def fmt_resolve(cap_name, cap, cands, m):
    out = [f"{cap_name}  (stage: {cap['stage']})  mode: {m}", f"  {cap['description']}"]
    loaded = [c for c in cands if c["tier"] <= 5 and not c.get("dangling")]
    lib = [c for c in cands if c["tier"] == 6]
    fbs = [c for c in cands if c["tier"] == 7]
    n = 0
    for c in loaded:
        n += 1
        out.append(f"  {n}. [{TIER_LABEL[c['tier']]}] {c['type']:5} {c['name']:<28} {c['why']}")
        if c["description"]:
            out.append(f"       {c['description'][:150]}")
    for c in lib[:3]:
        out.append(f"  L. [{TIER_LABEL[6]}] {c['type']:5} {c['name']:<28} load with: python3 -I {HARNESS_TRIM} add {c['name']} --pin")
        if c["description"]:
            out.append(f"       {c['description'][:150]}")
    for c in fbs:
        tag = "F. [fallback, not built yet]" if c.get("planned") else "F. [fallback]"
        out.append(f"  {tag} {c['type']:5} {c['name']:<28} {c['why']}")
    for c in cands:
        if c.get("dangling"):
            out.append(f"  !  override {c['type']}:{c['name']} is not installed; ignoring")
    if m == "auto":
        pick = (next((c for c in loaded if c.get("score", 2) <= 1), None)
                or next((c for c in loaded if c["tier"] <= 2), None)
                or next((c for c in fbs if not c.get("planned")), None))
        out.append(f"\nAUTO: use {pick['type']} {pick['name']} ({TIER_LABEL[pick['tier']]}); say so in one line." if pick
                   else "\nAUTO: nothing installed covers this and the fallback is not built; do it by hand and say so.")
    else:
        out.append("\nASK: show the user options 1..n (and L/F if relevant) in one compact list, let them pick, then record it with"
                   f" `resolve.py choose {cap_name} <type>:<name>`. Switch with `resolve.py mode auto`.")
    return "\n".join(out)


def cmd_capabilities(a):
    c = load_json(CONTRACT, {})
    for name, cap in c.get("capabilities", {}).items():
        fb = cap.get("fallback")
        fbs = f"fallback {fb['name']}{' (planned)' if fb and fb.get('planned') else ''}" if fb else "no fallback"
        print(f"{name:<20} {cap['stage']:<8} {fbs:<32} {cap['description'][:80]}")


def cmd_inventory(a):
    inv = inventory()
    if a.json:
        print(json.dumps(inv, indent=1)); return
    for t in sorted({e["tier"] for e in inv}):
        es = [e for e in inv if e["tier"] == t]
        print(f"[{TIER_LABEL[t]}] {len(es)}")
        if t == 6 and not a.all:
            print("   (ECC library; pass --all to list)"); continue
        for e in es:
            print(f"   {e['type']:5} {e['name']:<30} {e['description'][:90]}")


def cmd_resolve(a):
    m = mode()
    cap, cands = resolve(a.capability, a.task)
    if a.json:
        print(json.dumps({"capability": a.capability, "mode": m, "candidates": cands}, indent=1)); return
    print(fmt_resolve(a.capability, cap, cands, m))


def _write_cfg(update, project):
    path = project_root() / ".claude" / f"{THIS_PLUGIN}.json" if project else USER_CFG
    cfg = load_json(path, {}); update(cfg)
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(cfg, indent=1) + "\n")
    print(f"wrote {path}")


def cmd_mode(a):
    if not a.value:
        print(f"mode: {mode()}  (project config overrides user config; default from lifecycle.json)"); return
    _write_cfg(lambda c: c.__setitem__("mode", a.value), a.project)
    print(f"mode: {a.value}" + (" for this project" if a.project else " for this user"))


def cmd_override(a):
    def upd(c):
        o = c.setdefault("overrides", {})
        if a.remove:
            o.pop(a.capability, None)
        else:
            o[a.capability] = a.provider
    _write_cfg(upd, a.project)


def cmd_choose(a):
    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS, "a") as f:
        f.write(json.dumps({"ts": time.time(), "capability": a.capability, "provider": a.provider, "mode": mode(), "cwd": str(Path.cwd())}) + "\n")
    print(f"recorded {a.capability} -> {a.provider}")


def cmd_status(a):
    print(f"mode: {mode()}")
    o = overrides()
    print("overrides: " + (", ".join(f"{k}={v}" for k, v in o.items()) if o else "none"))
    rows = [json.loads(l) for l in DECISIONS.read_text().splitlines() if l.strip()] if DECISIONS.exists() else []
    if not rows:
        print("decisions: none recorded yet"); return
    from collections import Counter
    c = Counter((r["capability"], r["provider"]) for r in rows)
    print("decisions (capability -> provider: count):")
    for (cap, prov), n in c.most_common():
        print(f"  {cap:<20} {prov:<32} {n}")
    for cap in {r["capability"] for r in rows}:
        picks = Counter(r["provider"] for r in rows if r["capability"] == cap)
        prov, n = picks.most_common(1)[0]
        if n >= 3 and len(picks) == 1 and cap not in o:
            print(f"suggest: you always pick {prov} for {cap}; `resolve.py override {cap} {prov}` stops the question")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("capabilities"); s.set_defaults(fn=cmd_capabilities)
    s = sub.add_parser("inventory"); s.set_defaults(fn=cmd_inventory); s.add_argument("--json", action="store_true"); s.add_argument("--all", action="store_true")
    s = sub.add_parser("resolve"); s.set_defaults(fn=cmd_resolve); s.add_argument("capability"); s.add_argument("--task", default=""); s.add_argument("--json", action="store_true")
    s = sub.add_parser("mode"); s.set_defaults(fn=cmd_mode); s.add_argument("value", nargs="?", choices=["ask", "auto"]); s.add_argument("--project", action="store_true")
    s = sub.add_parser("override"); s.set_defaults(fn=cmd_override); s.add_argument("capability"); s.add_argument("provider", nargs="?", default=""); s.add_argument("--remove", action="store_true"); s.add_argument("--project", action="store_true")
    s = sub.add_parser("choose"); s.set_defaults(fn=cmd_choose); s.add_argument("capability"); s.add_argument("provider")
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    a = p.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
