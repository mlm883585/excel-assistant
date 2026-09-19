"""Stage an intranet update release: zip the portable package and write latest.json.

Usage:
    python scripts/stage_update.py --version 0.2.0 --notes-file release-notes.md --out build/update-release

Produces, in ``--out``:
    ExcelAssistant-<version>-win64.zip   (the portable package, top folder ``ExcelAssistant``)
    latest.json                          (version manifest the app polls)
    manifest.sha256.json / corresponding-source.zip   (audit copies, when present)
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def parse_version(value):
    parts = value.split("-", 1)[0].split(".")
    if len(parts) < 2 or not all(p.isdigit() for p in parts):
        raise argparse.ArgumentTypeError(f"版本号须为 semver，如 0.2.0，收到：{value}")
    return value


def main():
    parser = argparse.ArgumentParser(description="打包并生成内网更新发布物")
    parser.add_argument("--version", required=True, type=parse_version)
    parser.add_argument("--notes-file", default=None, help="纯文本更新说明文件")
    parser.add_argument("--out", default=str(ROOT / "build" / "update-release"))
    args = parser.parse_args()

    package = ROOT / "build" / "ExcelAssistant"
    if not (package / "ExcelAssistant.exe").exists():
        raise SystemExit("未找到 build/ExcelAssistant；请先运行 scripts/build.py")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    archive_base = f"ExcelAssistant-{args.version}-win64"
    archive = out / (archive_base + ".zip")
    archive.unlink(missing_ok=True)
    # 顶层保留 "ExcelAssistant" 文件夹，解压即得完整便携目录。
    shutil.make_archive(str(out / archive_base), "zip", root_dir=str(package.parent), base_dir=package.name)

    digest = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()

    notes = ""
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8").strip()

    manifest = {
        "name": "ExcelAssistant",
        "version": args.version,
        "channel": "stable",
        "published_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "notes": notes,
        "asset": {"url": archive.name, "sha256": digest, "size_bytes": archive.stat().st_size},
    }
    (out / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    for name in ("manifest.sha256.json", "corresponding-source.zip"):
        src = package / name
        if src.exists():
            shutil.copy2(src, out / name)

    print(f"更新包：{archive}")
    print(f"版本清单：{out / 'latest.json'}")
    print(f"SHA-256：{digest}")
    print("将 latest.json 与 zip 一并放入 nginx root 指向的目录即可发布。")


if __name__ == "__main__":
    main()
