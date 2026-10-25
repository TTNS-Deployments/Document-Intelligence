"""Repository checks run by `make check` and CI.

* every tracked JSON file parses;
* every relative link in every tracked Markdown file points to an existing file (and, for links into Markdown
  files, to an existing heading);
* no build output, virtual environments, caches or local data are committed;
* the content rules: no references to other solutions, and none of the words listed in FORBIDDEN.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = [r"call[\s-]?cent(er|re)", r"callcenter", r"\bcalls\b", r"\bagents?\b", r"Call-Center-Analysis"]
SKIP_CONTENT = ("/vendor/", "qa/check_repo.py")
BINARY = {".png", ".pdf", ".jpg", ".pfb", ".ttf", ".gz", ".xlsx", ".zip"}
NOT_COMMITTED = (r"(^|/)__pycache__/", r"(^|/)\.venv/", r"^build/", r"(^|/)\.localdata/", r"\.pyc$", r"(^|/)staticfiles/",
                 r"(^|/)\.env$")


def tracked() -> list[str]:
    return subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()


def slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    out, seen = set(), {}
    in_code = False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        m = re.match(r"^#{1,6}\s+(.*)", line)
        if m:
            s = slug(m[1])
            n = seen.get(s, 0)
            out.add(s if n == 0 else f"{s}-{n}")
            seen[s] = n + 1
    return out


def main() -> int:
    errors = []
    files = tracked()
    for name in files:
        if any(re.search(p, name) for p in NOT_COMMITTED):
            errors.append(f"{name}: should not be committed")
        path = ROOT / name
        if not path.is_file():
            continue
        if name.endswith(".json"):
            try:
                json.loads(path.read_text())
            except ValueError as exc:
                errors.append(f"{name}: invalid JSON ({exc})")
        if path.suffix.lower() not in BINARY and not any(s in f"/{name}" for s in SKIP_CONTENT):
            text = path.read_text(errors="ignore")
            for pattern in FORBIDDEN:
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    line = text.count("\n", 0, m.start()) + 1
                    errors.append(f"{name}:{line}: forbidden wording {m[0]!r}")
        if name.endswith(".md"):
            in_code = False
            for i, line in enumerate(path.read_text().splitlines(), 1):
                if line.startswith("```"):
                    in_code = not in_code
                if in_code:
                    continue
                for target in re.findall(r"\]\(([^)\s]+)\)", line):
                    if re.match(r"^[a-z]+:", target) or target.startswith("mailto:"):
                        continue
                    file_part, _, anchor = target.partition("#")
                    dest = (path.parent / file_part).resolve() if file_part else path
                    if not dest.exists():
                        errors.append(f"{name}:{i}: broken link {target}")
                    elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                        errors.append(f"{name}:{i}: missing anchor #{anchor} in {dest.relative_to(ROOT)}")
    for e in errors:
        print(e)
    print(f"{len(files)} files checked, {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
