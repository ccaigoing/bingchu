"""SQLite 连接与初始化。

对齐参照项目 huajian-xinsheng 的 `db.ts::initDB()`，但有一处**必要差异**：
这里开 `PRAGMA journal_mode=WAL`。

原因很具体：阶段二 2.5 会有三个后台协程（传感器漂移每 2s 写库、预警评估每 7s、
喷洒任务推进）与 API 读请求并发跑。SQLite 默认的 rollback journal 模式下，
写入会独占整个库，读请求直接撞 `database is locked`。WAL 让读不阻塞写、
写不阻塞读 —— 这不是优化，是这个架构能不能跑起来的前提。

其余约定：
- `row_factory = sqlite3.Row` —— 让查询结果能按列名取值，再经路由层转成
  驼峰 JSON。**不引 ORM**：表不多、查询不复杂，ORM 只会让"这一列哪来的"变难查。
- `foreign_keys=ON` 必须显式开 —— SQLite 默认**不**强制外键，这条很容易漏。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import DB_PATH, ensure_dirs

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    # WAL 是持久化设置（写进库文件头），只需设一次，但每次设也无害。
    conn.execute("PRAGMA journal_mode=WAL")
    # 外键默认关闭，必须每次连接都开 —— 它是**连接级**设置。
    conn.execute("PRAGMA foreign_keys=ON")
    # WAL 下 NORMAL 是安全与速度的平衡点：崩溃不丢库，最多丢最近若干次提交。
    conn.execute("PRAGMA synchronous=NORMAL")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """开一个配好的连接。调用方负责关。"""
    path = db_path or DB_PATH
    ensure_dirs()
    conn = sqlite3.connect(str(path), timeout=10.0)
    _configure(conn)
    return conn


@contextmanager
def get_conn(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """连接上下文：正常退出提交，出异常回滚，无论如何都关。"""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params: tuple = (), db_path: Path | None = None) -> list[dict]:
    """只读查询的快捷方式，直接返回 dict 列表。

    给路由层用：省掉每个端点都写一遍 with/commit/close。
    写操作请走 `get_conn()`，那样才有明确的事务边界。
    """
    with get_conn(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def query_one(sql: str, params: tuple = (), db_path: Path | None = None) -> dict | None:
    rows = query(sql, params, db_path)
    return rows[0] if rows else None


def init_db(db_path: Path | None = None, *, drop: bool = False) -> Path:
    """建表。幂等（DDL 全是 `IF NOT EXISTS`）。

    `drop=True` 时先删掉库文件 —— 重建用。**只在 seed 流程里用**，
    正常运行路径上绝不能删库。
    """
    path = db_path or DB_PATH
    ensure_dirs()

    if drop:
        # WAL 模式下还有 -wal / -shm 两个附属文件，一起清掉，
        # 否则残留的 WAL 会在新库上被重放，行为诡异。
        for suffix in ("", "-wal", "-shm"):
            f = Path(str(path) + suffix)
            if f.exists():
                f.unlink()

    ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_conn(path) as conn:
        conn.executescript(ddl)
    return path


def table_counts(db_path: Path | None = None) -> dict[str, int]:
    """每张表的行数。给 seed 完的核对与 /api/health 用。"""
    path = db_path or DB_PATH
    with get_conn(path) as conn:
        names = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        return {
            n: conn.execute(f'SELECT COUNT(*) AS c FROM "{n}"').fetchone()["c"]
            for n in names
        }
