"""工作流作业记录的 SQLite 存储层 (bogie.db 内的 TblFlowJob 表).

一行 = 一次作业 (一个工单), 完整的工作流日志数组 / 结果数据 / summary /
空簧曲线等复杂对象整体以 JSON 文本存入对应列, 不拆行表:
- 结构化字段 (id/时间/状态/类型/用户) 是真列, 可直接按日期、状态查询;
- summary、air_curve 单列存放: 所有读写更新只指向该列, 不再靠
  "扫描日志流取最后一条" 推导现行值;
- logs 列存完整条目数组 (与内存中 workflow.logs 同构), 每次按整块覆盖
  写入, 单事务完成, 不会出现追加流的半行/交错.

连接策略与 dialog_user / view_login 一致: 每次操作开一个短连接,
不跨线程共用; 开启 WAL + busy_timeout, 读写互不长时间阻塞.
时间一律本地时间字符串 "YYYY-MM-DD HH:MM:SS".
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

TABLE = "TblFlowJob"

STATE_IDLE = "待执行"
STATE_RUNNING = "执行中"
STATE_DONE = "完成"
STATE_ERROR = "故障"
STATE_STOPPED = "停止"
FINAL_STATES = (STATE_DONE, STATE_ERROR, STATE_STOPPED)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    name TEXT,
    type TEXT,
    user TEXT,
    state TEXT,
    cur_node TEXT,
    meta TEXT,
    data TEXT,
    summary TEXT,
    air_curve TEXT,
    logs TEXT,
    emis_uploaded INTEGER NOT NULL DEFAULT 0,
    emis_at TEXT
)
"""

_COLUMNS = (
    "id", "created_at", "started_at", "finished_at", "name", "type", "user",
    "state", "cur_node", "meta", "data", "summary", "air_curve", "logs",
    "emis_uploaded", "emis_at",
)
_JSON_COLUMNS = ("meta", "data", "summary", "air_curve", "logs")


def local_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_time(value: Any) -> str:
    """把 ISO 时间 (可带 T 分隔) 归一为 "YYYY-MM-DD HH:MM:SS"; 解析不了原样返回."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _loads(text: Any, default: Any) -> Any:
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def ensure_schema(db_path: str | Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute(_SCHEMA)
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_flowjob_created ON {TABLE}(created_at)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_flowjob_state ON {TABLE}(state)")


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    job = {key: row[key] for key in row.keys()}
    job["meta"] = _loads(job.get("meta"), {})
    job["data"] = _loads(job.get("data"), {})
    job["summary"] = _loads(job.get("summary"), {})
    job["air_curve"] = _loads(job.get("air_curve"), {})
    job["logs"] = _loads(job.get("logs"), [])
    job["emis_uploaded"] = bool(job.get("emis_uploaded"))
    return job


def create_job(
    db_path: str | Path,
    *,
    job_id: str,
    created_at: str,
    name: str,
    job_type: str,
    user: str,
    meta: dict[str, Any] | None,
) -> None:
    """创建工单时建行: state=待执行, started_at/finished_at 为空.

    已存在同 id 的行时不覆盖 (INSERT OR IGNORE), 保证重建/重复调用安全.
    """
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            f"INSERT OR IGNORE INTO {TABLE} "
            "(id, created_at, name, type, user, state, meta, logs) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                normalize_time(created_at) or local_now(),
                name,
                job_type,
                user,
                STATE_IDLE,
                _dumps(meta or {}),
                _dumps([]),
            ),
        )


def upsert_snapshot(
    db_path: str | Path,
    *,
    job_id: str,
    created_at: str,
    name: str,
    job_type: str,
    user: str,
    state: str,
    cur_node: str | None,
    meta: dict[str, Any] | None,
    data: Any,
    summary: Any,
    air_curve: Any,
    logs: list[dict[str, Any]] | None,
    started_at: str | None,
    finished_at: str | None,
    finished_at_clear: bool = False,
) -> None:
    """把一次作业的当前完整快照整块写入对应行 (不存在则先建行).

    由工作流运行期在每个落盘时机调用: 所有 JSON 列均按内存现状整块覆盖,
    单事务提交; summary/air_curve 由调用方从日志现状推导后传入.
    started_at/finished_at 传 None 表示保持库中现值 (COALESCE), 避免后写的
    批量更新把已经记录的开始/结束时间冲掉. finished_at_clear=True 时强制
    把 finished_at 置空 (同一任务重新开始试验时用, 旧的结束时间不再有效).
    """
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            f"INSERT OR IGNORE INTO {TABLE} "
            "(id, created_at, name, type, user, state, meta, logs) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                normalize_time(created_at) or local_now(),
                name,
                job_type,
                user,
                STATE_IDLE,
                _dumps(meta or {}),
                _dumps([]),
            ),
        )
        conn.execute(
            f"UPDATE {TABLE} SET name=?, type=?, user=?, state=?, cur_node=?, "
            "meta=?, data=?, summary=?, air_curve=?, logs=?, "
            "started_at=COALESCE(?, started_at), "
            "finished_at=CASE WHEN ? THEN NULL ELSE COALESCE(?, finished_at) END "
            "WHERE id=?",
            (
                name,
                job_type,
                user,
                state,
                cur_node,
                _dumps(meta or {}),
                _dumps(data),
                _dumps(summary),
                _dumps(air_curve),
                _dumps(logs or []),
                normalize_time(started_at) if started_at else None,
                1 if finished_at_clear else 0,
                normalize_time(finished_at) if finished_at else None,
                job_id,
            ),
        )


def get_job(db_path: str | Path, job_id: str) -> dict[str, Any] | None:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(f"SELECT * FROM {TABLE} WHERE id=?", (job_id,)).fetchone()
    return _row_to_job(row) if row is not None else None


def list_jobs(
    db_path: str | Path,
    *,
    on_date: str | None = None,
    require_summary: bool = False,
) -> list[dict[str, Any]]:
    """列出作业, 新的在前. on_date 为 "YYYY-MM-DD" 时只取当天创建的."""
    ensure_schema(db_path)
    clauses: list[str] = []
    params: list[Any] = []
    if on_date:
        clauses.append("date(created_at) = date(?)")
        params.append(on_date)
    if require_summary:
        clauses.append("summary IS NOT NULL AND summary <> '' AND summary <> '{}'")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM {TABLE}{where} ORDER BY created_at DESC, rowid DESC", params
        ).fetchall()
    return [_row_to_job(row) for row in rows]


def delete_job(db_path: str | Path, job_id: str) -> bool:
    """删除一行作业 (任何状态均可; 是否允许删、删前确认由调用方负责)."""
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        cursor = conn.execute(f"DELETE FROM {TABLE} WHERE id=?", (job_id,))
        return cursor.rowcount > 0


def amend_job(
    db_path: str | Path,
    job_id: str,
    *,
    summary: dict[str, Any],
    meta: dict[str, Any],
    entries: list[dict[str, Any]],
) -> bool:
    """补录: 单事务内整块更新 summary/meta 两列, 并把审计条目并入 logs 数组."""
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(f"SELECT logs FROM {TABLE} WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return False
        logs = _loads(row["logs"], [])
        if not isinstance(logs, list):
            logs = []
        logs.extend(entries)
        conn.execute(
            f"UPDATE {TABLE} SET summary=?, meta=?, logs=? WHERE id=?",
            (_dumps(summary), _dumps(meta), _dumps(logs), job_id),
        )
        return True


def mark_emis_uploaded(
    db_path: str | Path,
    job_id: str,
    *,
    entry: dict[str, Any],
    at: str | None = None,
) -> bool:
    """记录 EMIS 上传成功: 置标志与时间, 并把上传条目并入 logs 数组."""
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(f"SELECT logs FROM {TABLE} WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return False
        logs = _loads(row["logs"], [])
        if not isinstance(logs, list):
            logs = []
        logs.append(entry)
        conn.execute(
            f"UPDATE {TABLE} SET emis_uploaded=1, emis_at=?, logs=? WHERE id=?",
            (normalize_time(at) or local_now(), _dumps(logs), job_id),
        )
        return True


def is_completed(job: dict[str, Any] | None) -> bool:
    """完成口径: state=完成 且 summary 非空 (无结果的完成不算已完成作业)."""
    if not job:
        return False
    return job.get("state") == STATE_DONE and bool(job.get("summary"))
