#!/usr/bin/env python3
"""pr_body: assemble a PR description with proof, risk, and revert steps.

Fills the plugin's PR template (or the repo's own .github/PULL_REQUEST_TEMPLATE.md when
present) from files and flags you pass, so the body is built from evidence rather than typed
from memory. Prints to stdout; pipe into `gh pr create --body-file -`.
"""
import argparse, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE.parent.parent / "de-code-review" / "templates" / "PULL_REQUEST_TEMPLATE.md"


def read(p):
    return Path(p).read_text().rstrip() if p and Path(p).exists() else ""


def changed_files():
    try:
        base = subprocess.run(["git", "merge-base", "HEAD", "origin/main"], capture_output=True, text=True).stdout.strip() or "main"
        out = subprocess.run(["git", "diff", "--name-only", base], capture_output=True, text=True).stdout
        return [l for l in out.splitlines() if l.strip()]
    except Exception:
        return []


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--title", required=True)
    p.add_argument("--why", required=True, help="one paragraph: what and why, ticket link, goal beyond the ticket")
    p.add_argument("--testing-file", help="file with proof: de-verify evidence block, test output, dry-run bytes")
    p.add_argument("--testing", default="", help="inline proof text if no file")
    p.add_argument("--risk", required=True, choices=["Low", "Medium", "High"])
    p.add_argument("--risk-why", required=True, help="one line: what breaks downstream if wrong, which consumers")
    p.add_argument("--revert", required=True, help="exact steps: git revert <sha>; how data is restored or recomputed")
    p.add_argument("--checks", default="", help="comma list of checklist items already done (substring match)")
    p.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    a = p.parse_args()

    repo_t = Path(".github/PULL_REQUEST_TEMPLATE.md")
    template = read(repo_t if repo_t.exists() else a.template)
    testing = read(a.testing_file) or a.testing or "NO PROOF ATTACHED. Add de-verify output or test results before requesting review."
    files = changed_files()
    body = template if template else "## What and why\n\n## Testing\n\n## Risk\n\n## How to revert\n"

    def fill(section, text):
        nonlocal body
        marker = f"## {section}"
        if marker not in body:
            body += f"\n{marker}\n\n{text}\n"; return
        head, rest = body.split(marker, 1)
        nxt = rest.find("\n## ")
        tail = rest[nxt:] if nxt >= 0 else ""
        body = f"{head}{marker}\n\n{text}\n{tail}"

    fill("What and why", a.why + (f"\n\nFiles: {', '.join(files[:15])}{' ...' if len(files) > 15 else ''}" if files else ""))
    fill("Testing", testing)
    fill("Risk", f"**{a.risk}.** {a.risk_why}")
    fill("How to revert", a.revert)
    done = [c.strip().lower() for c in a.checks.split(",") if c.strip()]
    body = "\n".join((l.replace("- [ ]", "- [x]", 1) if any(d in l.lower() for d in done) else l) for l in body.splitlines())
    # strip template HTML comments that are instructions to the author
    import re
    body = re.sub(r"<!--.*?-->\n?", "", body, flags=re.S)
    print(f"# {a.title}\n\n{body.strip()}\n")
    if "NO PROOF ATTACHED" in testing:
        print("warning: no proof attached", file=sys.stderr); sys.exit(2)


if __name__ == "__main__":
    main()
