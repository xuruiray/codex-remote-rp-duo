#!/usr/bin/env python3
"""Check repository-local Markdown and HTML links without querying private URLs."""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
HTML_LINK = re.compile(r'<(?:a|img)\b[^>]*?\b(?:href|src)=["\']([^"\']+)["\']', re.I)


def main():
    files = sorted({*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md"), *(ROOT / ".github").rglob("*.md")})
    failures = []
    checked = 0
    for document in files:
        text = document.read_text(encoding="utf-8")
        for raw in [*MARKDOWN_LINK.findall(text), *HTML_LINK.findall(text)]:
            target = raw.strip().split(' "', 1)[0].strip("<>")
            url = urlsplit(target)
            if url.scheme or url.netloc or not url.path:
                continue
            checked += 1
            path = (document.parent / unquote(url.path)).resolve()
            if not path.is_relative_to(ROOT) or not path.exists():
                failures.append(f"{document.relative_to(ROOT)}: {target}")
    if failures:
        raise SystemExit("Invalid local documentation links:\n" + "\n".join(failures))
    print(f"Checked {checked} local links in {len(files)} Markdown files.")


if __name__ == "__main__":
    main()
