"""W8 D4/D5：凍結 MVP 與備份可執行版本。

freeze ：掃描程式檔（src、test_interface、tests、docs 與根目錄設定檔），寫 docs/integration/mvp_manifest.json
         （版本名、時間、git commit、套件版本、每個檔案的 sha256、整體 tree 雜湊、模板雜湊）。
verify ：重算雜湊，與清單比對；有改動／新增／缺少的檔案就列出並回傳 1。
backup ：把目前程式檔（加 manifest；--with-data 再加 data/samples 模板）打成 zip。

指令（專案根目錄）：
    python -m src.control.release freeze --version mvp-v1
    python -m src.control.release verify
    python -m src.control.release backup --version mvp-v1 --with-data
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.control.util import atomic_write_json

ROOT = Path(__file__).resolve().parents[2]
CODE_DIRS = ("src", "test_interface", "tests", "docs")
EXCLUDE_DIRS = frozenset({
    ".git", "data", "logs", "exports", "reports", "__pycache__", ".pytest_cache",
    ".venv", "venv", "env", "models", "datasets", ".vscode", ".idea", "htmlcov",
})
CODE_EXTS = frozenset({".py", ".ps1", ".ini", ".txt", ".md", ".toml", ".cfg"})
PACKAGES = ("torch", "opencv-python", "numpy", "fastapi", "pydantic", "mss", "pyautogui", "pytest", "uvicorn")
MANIFEST_PATH = Path("docs/integration/mvp_manifest.json")
TEMPLATE_DIR = Path("data/samples")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_files(root: Path, dirs: Sequence[str] = CODE_DIRS) -> list[Path]:
    root = Path(root)
    found: set[Path] = {p for p in root.iterdir() if p.is_file() and p.suffix.lower() in CODE_EXTS}
    for name in dirs:
        base = root / name
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in CODE_EXTS:
                continue
            if any(part in EXCLUDE_DIRS for part in p.relative_to(root).parts):
                continue
            found.add(p)
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


def file_digests(root: Path, files: Sequence[Path]) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in files}


def tree_sha256(digests: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(digests):
        digest.update(f"{path}\0{digests[path]}\n".encode("utf-8"))
    return digest.hexdigest()


def _git(root: Path, *args: str, run: Callable[..., Any]) -> str | None:
    try:
        return run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def package_versions(
    names: Sequence[str] = PACKAGES, version_fn: Callable[[str], str] = metadata.version
) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in names:
        try:
            out[name] = version_fn(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


def templates_sha256(root: Path) -> str | None:
    folder = Path(root) / TEMPLATE_DIR
    if not folder.is_dir():
        return None
    return tree_sha256({p.name: sha256_file(p) for p in sorted(folder.glob("*.png"))})


def build_manifest(
    root: Path,
    *,
    version: str,
    now: datetime | None = None,
    git_run: Callable[..., Any] = subprocess.run,
    version_fn: Callable[[str], str] = metadata.version,
) -> dict[str, Any]:
    root = Path(root)
    digests = file_digests(root, collect_files(root))
    status = _git(root, "status", "--porcelain", run=git_run)
    return {
        "version": version,
        "created_at": (now or datetime.now(timezone.utc)).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_commit": _git(root, "rev-parse", "HEAD", run=git_run),
        "git_dirty": None if status is None else bool(status),
        "packages": package_versions(version_fn=version_fn),
        "templates_sha256": templates_sha256(root),
        "file_count": len(digests),
        "tree_sha256": tree_sha256(digests),
        "files": digests,
    }


def verify_manifest(root: Path, manifest: Mapping[str, Any]) -> list[str]:
    """回傳問題清單；空清單代表目前程式與凍結清單完全一致。"""
    root = Path(root)
    current = file_digests(root, collect_files(root))
    frozen = dict(manifest.get("files", {}))

    problems = [f"改動：{p}" for p in sorted(frozen) if p in current and current[p] != frozen[p]]
    problems += [f"缺少：{p}" for p in sorted(frozen) if p not in current]
    problems += [f"新增：{p}" for p in sorted(current) if p not in frozen]
    return problems


def make_backup(root: Path, out_zip: Path, manifest: Mapping[str, Any], *, with_data: bool = False) -> int:
    """打包目前程式檔 + manifest（+ 模板）；回傳放進 zip 的檔案數。"""
    import json

    root, out_zip = Path(root), Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in collect_files(root):
            zf.write(p, p.relative_to(root).as_posix())
            count += 1
        zf.writestr("mvp_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        count += 1
        folder = root / TEMPLATE_DIR
        if with_data and folder.is_dir():
            for p in sorted(folder.glob("*.png")):
                zf.write(p, p.relative_to(root).as_posix())
                count += 1
    return count


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="凍結 MVP 與備份")
    parser.add_argument("command", choices=("freeze", "verify", "backup"))
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--version", default="mvp-v1")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--out", default=None, help="backup 的 zip 路徑（預設 exports/<version>.zip）")
    parser.add_argument("--with-data", action="store_true", help="backup 時一併放入 data/samples 模板")
    args = parser.parse_args(argv)

    root = Path(args.root)
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path

    if args.command == "freeze":
        manifest = build_manifest(root, version=args.version)
        atomic_write_json(manifest_path, manifest)
        print(f"已凍結 {manifest['version']}：{manifest['file_count']} 個檔案，tree={manifest['tree_sha256'][:16]}…")
        print(f"git commit={manifest['git_commit']} dirty={manifest['git_dirty']}")
        print(f"清單：{manifest_path}")
        return 0

    if args.command == "verify":
        import json

        try:
            frozen = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"❌ 讀不到凍結清單 {manifest_path}：{exc}（請先 freeze）")
            return 1
        problems = verify_manifest(root, frozen)
        if problems:
            print(f"❌ 與凍結版 {frozen.get('version')} 不一致：{len(problems)} 項")
            for p in problems[:50]:
                print("  -", p)
            return 1
        print(f"✅ 與凍結版 {frozen.get('version')} 完全一致（{frozen.get('file_count')} 個檔案）")
        return 0

    manifest = build_manifest(root, version=args.version)
    out = Path(args.out) if args.out else Path("exports") / f"{args.version}.zip"
    if not out.is_absolute():
        out = root / out
    count = make_backup(root, out, manifest, with_data=args.with_data)
    print(f"✅ 已備份 {count} 個檔案：{out}")
    if not args.with_data:
        print("（沒有包含 data/samples 模板；視覺要用的話請加 --with-data）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())