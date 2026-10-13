"""讓測試檔可以用 `python -m tests.test_xxx` 直接執行（不用 pytest）。

自動收集該檔案自己定義的 test_* 函式、需要 tmp_path 的會給一個暫存資料夾，
最後印出「實際」通過的數量（不再手寫 N 項）。

用法（放在測試檔最下面）：
    if __name__ == "__main__":
        run_module(globals(), "test_xxx")
"""

from __future__ import annotations

import inspect
import tempfile
from pathlib import Path
from typing import Any


def run_module(namespace: dict[str, Any], title: str) -> int:
    module_name = namespace.get("__name__")
    tests = [
        (name, fn)
        for name, fn in namespace.items()
        if name.startswith("test_") and inspect.isfunction(fn) and fn.__module__ == module_name
    ]

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for name, fn in tests:
            params = list(inspect.signature(fn).parameters)
            try:
                if not params:
                    fn()
                elif params == ["tmp_path"]:
                    folder = base / name
                    folder.mkdir()
                    fn(folder)
                else:
                    raise TypeError(f"{name} 只支援沒有參數或只有 tmp_path：{params}")
            except BaseException:
                print(f"❌ {title}：{name} 失敗")
                raise
            print(f"  ok  {name}")

    print(f"✅ {title}：{len(tests)} 項測試全部通過")
    return len(tests)