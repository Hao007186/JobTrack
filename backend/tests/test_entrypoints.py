import os
import subprocess
import sys

import pytest

from tests.conftest import BACKEND_DIR


@pytest.mark.parametrize(
    "module",
    [
        "app.main",
        "app.seeds.reference",
        "app.seeds.demo",
        "app.jobs.maintenance",
        "app.jobs.check_prices",
    ],
)
def test_entrypoint_registers_all_tables(module: str) -> None:
    # 每個指令都是獨立行程；只 import 入口時，外鍵指向的表也必須已註冊，否則寫入時才會出錯
    code = f"import {module}\nfrom app.db.base import Base\nBase.metadata.sorted_tables\n"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
