"""CI denetimleri icin ortak yardimcilar (yalnizca standart kutuphane)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_HOSTS = {"alig.tech", "www.alig.tech", "staging.alig.tech"}
SKIP_DIRS = {".git", "dist", "__pycache__", "node_modules"}
TEXT_SUFFIXES = {".html", ".css", ".js", ".json", ".md", ".py", ".txt", ".svg", ".xml",
                 ".yml", ".yaml", ".service", ".timer", ".conf", ".example", ".sh", ".toml", ".ini", ""}


def read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


def iter_files(root, suffixes=None, skip_dirs=SKIP_DIRS):
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.relative_to(root).parts):
            continue
        if suffixes is not None and path.suffix.lower() not in suffixes:
            continue
        yield path


def rel(path, root):
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return str(path)
