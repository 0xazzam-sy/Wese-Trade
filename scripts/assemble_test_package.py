#!/usr/bin/env python3
"""Assemble the PERSONAL WINDOWS TEST PACKAGE (offline, outside GitHub).

    python scripts/assemble_test_package.py --binaries <validated windows-test-binaries dir>
        --seed <make_test_seed.py output dir> --out <output dir>

* Verifies every Windows binary against the SHA256SUMS produced by the Windows CI job that
  validated them (so the archive holds exactly the validated files).
* Adds the seed database, the Arabic guides, VERSION.txt and TEST-ACCOUNTS-AR.txt (the only
  place the generated passwords are written).
* Produces WeseTrade-Windows-Test/, WeseTrade-Windows-Test-v1.0.0.zip (installer, guides,
  accounts) and WeseTrade-Windows-Test-v1.0.0-Portable.zip (optional portable copy).
No passwords are printed. Nothing here is committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "packaging" / "windows-test"
FROZEN = "wese-trade-forward-4.2-a03e20f1d4"
NAME = "WeseTrade-Windows-Test"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_windows_text(path: Path, text: str) -> None:
    """UTF-8 with BOM and CRLF: opens correctly in Notepad on every Windows 10/11."""
    body = text.replace("\r\n", "\n").replace("\n", "\r\n")
    path.write_bytes("﻿".encode() + body.encode("utf-8"))


def verify_binaries(binaries: Path) -> tuple[dict[str, str], int]:
    sums = {}
    for line in (binaries / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.lstrip("*")
        if name != "SHA256SUMS.txt":  # a checksum file cannot list itself
            sums[name] = digest
    for name, digest in sums.items():
        actual = sha256(binaries / name)
        if actual != digest:
            raise SystemExit(f"checksum mismatch: {name}")
    return sums, len(sums)


def verify_seed(db: Path) -> None:
    conn = sqlite3.connect(db)
    try:
        users = conn.execute("SELECT username, role FROM users ORDER BY id").fetchall()
        runs = conn.execute("SELECT count(*) FROM forward_test_runs").fetchone()[0]
        signals = conn.execute("SELECT count(*) FROM forward_test_signals").fetchone()[
            0
        ]
    finally:
        conn.close()
    expected = [
        ("admin_test", "admin"),
        ("analyst_test", "analyst"),
        ("viewer_test", "viewer"),
    ]
    if users != expected or runs or signals:
        raise SystemExit("seed database is not a clean test database")


def accounts_text(creds: list[dict[str, str]]) -> str:
    by_role = {c["role"]: c for c in creds}
    titles = (
        ("admin", "حساب المدير (Admin)"),
        ("analyst", "حساب المحلل (Analyst)"),
        ("viewer", "حساب المشاهد (Viewer)"),
    )
    lines = [
        "Wese Trade 1.0.0 — حسابات الاختبار المحلية",
        "==========================================",
        "",
        "هذه الحسابات مخصصة لنسخة الاختبار المحلية فقط.",
        "لا تستخدم كلمات المرور هذه في أي مكان آخر، ولا تشاركها.",
        "قبل أول تسجيل دخول شغّل الملف Setup-Test-Accounts.cmd مرة واحدة (راجع README-AR.txt).",
        "انتبه: الأحرف الكبيرة والصغيرة مختلفة في كلمة المرور. انسخها كما هي.",
        "",
    ]
    for role, title in titles:
        c = by_role[role]
        lines += [
            f"{title}:",
            f"اسم المستخدم: {c['username']}",
            f"كلمة المرور: {c['password']}",
            "",
        ]
    lines += [
        "الصلاحيات:",
        "- المدير: كل شيء، بما في ذلك إدارة المستخدمين وأزرار التحكم في الاختبار المباشر.",
        "- المحلل: التحليل والإشارات وعرض صفحة الاختبار المباشر، بدون إدارة المستخدمين.",
        "- المشاهد: عرض فقط، بدون أي إجراءات إدارية.",
        "",
        "يمكن للمدير تغيير كلمات المرور من: الإعدادات ← المستخدمون.",
    ]
    return "\n".join(lines) + "\n"


def version_text(info: dict[str, str], assembled: str) -> str:
    return "\n".join(
        [
            "Application:",
            "Wese Trade 1.0.0 TEST BUILD",
            "",
            "Platform:",
            "Windows x64 (Windows 10/11)",
            "",
            "Strategy:",
            FROZEN,
            "",
            "Fingerprint:",
            "4.2-a03e20f",
            "",
            "Market provider:",
            "OKX Public Market Data",
            "",
            "Auto trading:",
            "Disabled",
            "",
            "Build date:",
            f"{info['built_at_utc']} (Windows binaries, GitHub Actions run {info['run']})",
            f"{assembled} (test package assembled)",
            "",
            "Git commit:",
            info["source_commit"],
            "",
            "Code signing:",
            "Unsigned test build (Windows SmartScreen will warn; see TROUBLESHOOTING-AR.txt)",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binaries", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    sums, count = verify_binaries(args.binaries)
    info = dict(
        line.split("=", 1)
        for line in (args.binaries / "BUILD-INFO.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    seed_db = args.seed / "TestData" / "wese_trade.db"
    verify_seed(seed_db)
    creds = json.loads((args.seed / "credentials.json").read_text(encoding="utf-8"))

    pkg = args.out / NAME
    if pkg.exists():
        raise SystemExit(f"{pkg} already exists")
    pkg.mkdir(parents=True)
    shutil.copy2(args.binaries / "WeseTrade-Setup.exe", pkg / "WeseTrade-Setup.exe")
    shutil.copytree(args.binaries / "Portable", pkg / "Portable")
    shutil.copy2(
        args.binaries / "Setup-Test-Accounts.cmd", pkg / "Setup-Test-Accounts.cmd"
    )
    (pkg / "TestData").mkdir()
    shutil.copy2(seed_db, pkg / "TestData" / "wese_trade.db")
    (pkg / "SHA256SUMS.txt").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(sums.items())),
        encoding="utf-8",
    )

    assembled = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_windows_text(
        pkg / "README-AR.txt", (TEMPLATES / "README-AR.txt").read_text("utf-8")
    )
    write_windows_text(
        pkg / "TROUBLESHOOTING-AR.txt",
        (TEMPLATES / "TROUBLESHOOTING-AR.txt").read_text("utf-8"),
    )
    write_windows_text(pkg / "VERSION.txt", version_text(info, assembled))
    write_windows_text(pkg / "TEST-ACCOUNTS-AR.txt", accounts_text(creds))

    # re-verify the copied binaries inside the package
    for name, digest in sums.items():
        if sha256(pkg / name) != digest:
            raise SystemExit(f"copy mismatch: {name}")

    # Two archives (the full package exceeds the 30 MiB delivery limit): the main one with
    # the installer (recommended) and an optional one with the portable copy. Extracting
    # both into the same place recreates exactly WeseTrade-Windows-Test/.
    archives = {
        args.out / f"{NAME}-v1.0.0.zip": lambda rel: (
            not rel.startswith(f"{NAME}/Portable/")
        ),
        args.out / f"{NAME}-v1.0.0-Portable.zip": lambda rel: rel.startswith(
            f"{NAME}/Portable/"
        ),
    }
    for archive, include in archives.items():
        with zipfile.ZipFile(
            archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as zf:
            for path in sorted(pkg.rglob("*")):
                rel = path.relative_to(args.out).as_posix()
                if path.is_file() and include(rel):
                    zf.write(path, rel)
        print(f"{archive.name}: {archive.stat().st_size / 2**20:.1f} MiB")
    files = sum(1 for p in pkg.rglob("*") if p.is_file())
    print(
        f"package OK: {files} files, {count} binaries verified against the Windows CI checksums"
    )


if __name__ == "__main__":
    main()
