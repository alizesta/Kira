#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

SOURCE = Path("ProjectKira_2026-11-11_17-34_IRST.zip")
OUTPUT = Path("dist/ProjectKira_261111_1734.zip")
NOTES = Path("dist/release-notes.md")
SUMS = Path("dist/SHA256SUMS.txt")
IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv", "env", "__MACOSX"}
IGNORED_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".bak", ".swp", ".sqlite", ".sqlite3", ".db"}

def find_changelog(names):
    found = [n for n in names if PurePosixPath(n).name.lower().startswith(("changelog", "change_log", "changes"))]
    if not found:
        return None
    return sorted(found, key=lambda n: (len(PurePosixPath(n).parts), 0 if PurePosixPath(n).name.lower() in {"changelog.md", "changelog.txt"} else 1, n.lower()))[0]

def read_archive(path):
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError("ZIP integrity check failed: " + bad)
        files = {}
        for info in z.infolist():
            if info.is_dir():
                continue
            p = PurePosixPath(info.filename)
            parts = {x.lower() for x in p.parts}
            if parts.intersection(IGNORED_DIRS) or p.suffix.lower() in IGNORED_SUFFIXES:
                continue
            files[p.as_posix()] = z.read(info)
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        change_path = find_changelog(names)
        change_bytes = z.read(change_path) if change_path else None
        return files, change_path, change_bytes

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", type=Path, default=SOURCE)
    ap.add_argument("--previous-dir", type=Path, default=Path("dist/previous"))
    args = ap.parse_args()
    if not args.archive.is_file():
        raise FileNotFoundError("Uploaded ZIP not found: " + str(args.archive))

    current, changelog_path, changelog_bytes = read_archive(args.archive)
    changelog = (changelog_bytes or b"# Ai1 ChangeLog\n\n").decode("utf-8", errors="replace")
    previous_candidates = sorted(args.previous_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True) if args.previous_dir.exists() else []
    previous_path = previous_candidates[0] if previous_candidates else None
    previous = read_archive(previous_path)[0] if previous_path else {}

    if previous_path:
        old_hash = {p: hashlib.sha256(v).hexdigest() for p, v in previous.items() if not PurePosixPath(p).name.lower().startswith(("changelog", "change_log", "changes"))}
        new_hash = {p: hashlib.sha256(v).hexdigest() for p, v in current.items() if not PurePosixPath(p).name.lower().startswith(("changelog", "change_log", "changes"))}
        added = sorted(set(new_hash) - set(old_hash))
        removed = sorted(set(old_hash) - set(new_hash))
        modified = sorted(p for p in set(old_hash) & set(new_hash) if old_hash[p] != new_hash[p])
        delta = added + modified + removed
        basename_counts = Counter(PurePosixPath(p).name.lower() for p in delta)
        lower_log = changelog.lower().replace("\\", "/")
        def covered(path):
            base = PurePosixPath(path).name.lower()
            return path.lower() in lower_log or (len(base) >= 6 and basename_counts[base] == 1 and base in lower_log)
        added = [p for p in added if not covered(p)]
        modified = [p for p in modified if not covered(p)]
        removed = [p for p in removed if not covered(p)]
    else:
        added, modified, removed = [], [], []

    sections = []
    if added:
        sections += ["**افزوده‌شده:**"] + [f"- {p}" for p in added[:100]] + [""]
    if modified:
        sections += ["**تغییریافته:**"] + [f"- {p}" for p in modified[:100]] + [""]
    if removed:
        sections += ["**حذف‌شده:**"] + [f"- {p}" for p in removed[:100]] + [""]
    supplement = ""
    if sections:
        supplement = "## تکمیل خودکار ChangeLog\n\n"
        supplement += "مقایسه با آخرین آرشیو منتشرشده (" + (previous_path.name if previous_path else "ناموجود") + ") انجام شد؛ موارد زیر در متن قبلی ChangeLog ثبت نشده بودند:\n\n"
        supplement += "\n".join(sections).rstrip() + "\n"
        lines = changelog.splitlines()
        insert_at = 1 if lines and lines[0].lstrip().startswith("#") else 0
        while insert_at < len(lines) and not lines[insert_at].strip():
            insert_at += 1
        lines[insert_at:insert_at] = ["", supplement.rstrip(), ""]
        changelog = "\n".join(lines).rstrip() + "\n"

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    new_changelog_path = changelog_path or "CHANGELOG.md"
    with zipfile.ZipFile(args.archive) as src, zipfile.ZipFile(OUTPUT, "w") as dst:
        replaced = False
        for info in src.infolist():
            data = src.read(info.filename)
            if changelog_path and info.filename == changelog_path:
                data = changelog.encode("utf-8")
                replaced = True
            dst.writestr(info, data)
        if not replaced:
            dst.writestr(new_changelog_path, changelog.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(OUTPUT) as check:
        bad = check.testzip()
        if bad:
            raise RuntimeError("Repacked ZIP integrity check failed: " + bad)

    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    SUMS.write_text(digest + "  " + OUTPUT.name + "\n", encoding="utf-8")
    release_notes = supplement.strip() if supplement else changelog[:8000].strip()
    if not release_notes:
        release_notes = "Ai1 source archive update."
    NOTES.write_text("# Ai1 Update 261111_1734\n\n" + release_notes + "\n", encoding="utf-8")
    print({
        "source": str(args.archive),
        "source_size": args.archive.stat().st_size,
        "release_asset": str(OUTPUT),
        "release_size": OUTPUT.stat().st_size,
        "sha256": digest,
        "changelog": new_changelog_path,
        "previous_archive": str(previous_path) if previous_path else None,
        "unlisted_file_changes": {"added": len(added), "modified": len(modified), "removed": len(removed)},
    })

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise
