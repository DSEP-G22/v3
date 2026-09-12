"""Fail if an em dash, en dash or horizontal bar reaches the tree. Ported from v2.

Usage: python scripts/check_no_em_dashes.py [--fix] [--root DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".md", ".yaml", ".yml", ".json",
            ".txt", ".html", ".sql", ".toml", ".mjs"}
SKIP = {"node_modules", ".venv", "__pycache__", ".git", "dist", "build", ".next", "coverage",
        ".ruff_cache", ".pytest_cache"}
# Built with chr() so this file passes its own check.
BANNED = {chr(0x2014): ", ", chr(0x2013): " to ", chr(0x2015): ", "}


def files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUFFIXES and not SKIP.intersection(p.parts):
            yield p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args()
    root = Path(args.root).resolve()
    hits = 0
    for p in files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if args.fix:
            new = text
            for ch, rep in BANNED.items():
                new = new.replace(ch, rep)
            if new != text:
                p.write_text(new, encoding="utf-8")
                hits += 1
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if any(ch in line for ch in BANNED):
                print(f"{p.relative_to(root)}:{n}: {line.strip()}")
                hits += 1
    if args.fix:
        print(f"rewrote {hits} file(s)")
        return 0
    print(f"{hits} banned dash line(s)" if hits else "clean")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
