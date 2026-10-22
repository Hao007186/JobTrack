from alembic import command

from tests.conftest import BACKEND_DIR, alembic_config


def test_alembic_ini_is_ascii() -> None:
    # alembic 用系統 locale 讀 ini，繁中 Windows（cp950）讀不了 UTF-8 中文
    # Linux CI 是 UTF-8 不會重現，所以用這個測試擋住
    (BACKEND_DIR / "alembic.ini").read_bytes().decode("ascii")


def test_upgrade_then_downgrade(test_database_url: str) -> None:
    cfg = alembic_config(test_database_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
