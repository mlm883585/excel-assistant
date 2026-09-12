"""Archive only version-controlled sources, never local configuration or caches."""
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

MANIFEST = "source-files.json"
PRIVATE_NAMES = {"model.json", "answer.json", "credentials.json"}
PRIVATE_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".sqlite", ".sqlite3", ".db"}


def source_files(root: Path) -> list[Path]:
    root = root.resolve()
    try:
        top = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL).decode().strip()
    except (OSError, subprocess.CalledProcessError):
        top = ""
    if top and Path(top).resolve() == root:
        raw = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
        names = [name.decode("utf-8") for name in raw.split(b"\0") if name]
    elif (root / MANIFEST).is_file():
        names = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    else:
        raise ValueError("无法确定源码清单：请使用 Git 克隆，或解压随交付包提供的 corresponding-source.zip")

    if not isinstance(names, list) or not names:
        raise ValueError("源码清单必须是非空文件列表")
    files = []
    for name in names:
        if not isinstance(name, str) or "\\" in name or ":" in name:
            raise ValueError("源码清单包含非法路径")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("源码清单包含越界路径")
        path = root.joinpath(*relative.parts)
        if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
            raise ValueError(f"源码文件缺失或位于项目外：{name}")
        lower = path.name.lower()
        if (lower.startswith(".env") and lower not in {".env.example", ".env.template"}) or lower in PRIVATE_NAMES or path.suffix.lower() in PRIVATE_SUFFIXES:
            raise ValueError(f"源码清单包含禁止归档的配置或凭据文件：{name}")
        files.append(path)
    return sorted(set(files))


def write_source_archive(root: Path, target: Path) -> None:
    root = root.resolve()
    files = source_files(root)
    names = [p.relative_to(root).as_posix() for p in files if p.name != MANIFEST]
    temporary = target.with_suffix(".tmp.zip")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                archive.write(root / name, name)
            # Enables rebuilding the corresponding source without a .git directory.
            archive.writestr(MANIFEST, json.dumps(names, ensure_ascii=False, indent=2))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
