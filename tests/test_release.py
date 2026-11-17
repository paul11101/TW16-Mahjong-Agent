"""W8 D4/D5 凍結與備份工具測試（暫存資料夾，不碰真正的專案檔案）。

執行方式（專案根目錄）：
    python -m tests.test_release
或
    python -m pytest tests/test_release.py -v
"""

import json
import zipfile
from importlib import metadata

from src.control.release import (
    build_manifest,
    collect_files,
    main,
    make_backup,
    package_versions,
    verify_manifest,
)
from tests._runner import run_module


def _no_git(*args, **kwargs):
    raise OSError("沒有 git")


def _no_pkg(name):
    raise metadata.PackageNotFoundError(name)


def _project(root):
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test_a(): pass\n", encoding="utf-8")
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    (root / "main.py").write_text("x = 1\n", encoding="utf-8")
    # 這些不應該被收進來
    (root / "src" / "__pycache__").mkdir()
    (root / "src" / "__pycache__" / "a.py").write_text("junk", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "x.py").write_text("junk", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "g.txt").write_text("junk", encoding="utf-8")
    (root / "src" / "model.bin").write_bytes(b"\0")


def _manifest(root):
    return build_manifest(root, version="t1", git_run=_no_git, version_fn=_no_pkg)


def test_collect_files_excludes_junk(tmp_path):
    _project(tmp_path)
    names = [p.relative_to(tmp_path).as_posix() for p in collect_files(tmp_path)]

    assert names == ["README.md", "main.py", "src/a.py", "tests/test_a.py"]


def test_manifest_is_stable_and_tolerates_missing_git_and_packages(tmp_path):
    _project(tmp_path)
    first, second = _manifest(tmp_path), _manifest(tmp_path)

    assert first["tree_sha256"] == second["tree_sha256"]
    assert first["file_count"] == 4 and first["version"] == "t1"
    assert first["git_commit"] is None and first["git_dirty"] is None
    assert all(v is None for v in first["packages"].values())
    assert first["templates_sha256"] is None


def test_verify_detects_changed_added_missing(tmp_path):
    _project(tmp_path)
    manifest = _manifest(tmp_path)
    assert verify_manifest(tmp_path, manifest) == []

    (tmp_path / "src" / "a.py").write_text("print('changed')\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("new\n", encoding="utf-8")
    (tmp_path / "main.py").unlink()

    assert verify_manifest(tmp_path, manifest) == ["改動：src/a.py", "缺少：main.py", "新增：src/b.py"]


def test_package_versions():
    assert package_versions(("x", "y"), version_fn=lambda n: "1.0" if n == "x" else (_ for _ in ()).throw(
        metadata.PackageNotFoundError(n))) == {"x": "1.0", "y": None}


def test_backup_contains_code_manifest_and_optional_templates(tmp_path):
    _project(tmp_path)
    (tmp_path / "data" / "samples").mkdir()
    (tmp_path / "data" / "samples" / "0.png").write_bytes(b"png")
    manifest = _manifest(tmp_path)

    plain = tmp_path / "exports" / "plain.zip"
    assert make_backup(tmp_path, plain, manifest) == 5
    with zipfile.ZipFile(plain) as zf:
        names = set(zf.namelist())
    assert {"src/a.py", "tests/test_a.py", "README.md", "main.py", "mvp_manifest.json"} == names

    full = tmp_path / "exports" / "full.zip"
    assert make_backup(tmp_path, full, manifest, with_data=True) == 6
    with zipfile.ZipFile(full) as zf:
        assert "data/samples/0.png" in zf.namelist()
        assert json.loads(zf.read("mvp_manifest.json"))["version"] == "t1"


def test_cli_freeze_verify_backup(tmp_path):
    _project(tmp_path)
    root = str(tmp_path)

    assert main(["verify", "--root", root]) == 1  # 還沒凍結
    assert main(["freeze", "--root", root, "--version", "v9"]) == 0
    saved = json.loads((tmp_path / "docs" / "integration" / "mvp_manifest.json").read_text(encoding="utf-8"))
    assert saved["version"] == "v9"

    # 清單本身在 docs/ 底下，副檔名是 .json，不會被算進程式檔
    assert main(["verify", "--root", root]) == 0

    (tmp_path / "src" / "a.py").write_text("changed\n", encoding="utf-8")
    assert main(["verify", "--root", root]) == 1

    assert main(["backup", "--root", root, "--version", "v9"]) == 0
    assert (tmp_path / "exports" / "v9.zip").exists()


if __name__ == "__main__":
    run_module(globals(), "test_release")