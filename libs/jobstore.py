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
    uploaded TEXT NOT NULL DEFAULT ''
)
"""

_COLUMNS = (
    "id", "created_at", "started_at", "finished_at", "name", "type", "user",
    "state", "cur_node", "meta", "data", "summary", "air_curve", "logs",
    "uploaded",
)

# 上传状态字符串: emis#yyyymmdd@isdp#yyyymmdd, 每目标一段, 只记最后一笔.
# 新目标直接加一段即可, 不用改表结构; 段内 # 后为上传日期 (精确到日).
UPLOAD_TARGETS = ("emis", "isdp")
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
        _migrate_upload_status(conn)


def _migrate_upload_status(conn: sqlite3.Connection) -> None:
    """uploaded 字段迁移 (一次性, 幂等): 旧库补列、旧值转字符串、删旧列.

    旧值口径: emis_uploaded=1 -> emis#<emis_at 日期>; 0 -> 空 (未传).
    转换只写 uploaded 仍为空的行, 已迁移的值不会被重复转换冲掉.
    """
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({TABLE})")}
    if "uploaded" not in cols:
        conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN uploaded TEXT NOT NULL DEFAULT ''")
    if "emis_uploaded" in cols:
        has_emis_at = "emis_at" in cols
        for row in conn.execute(
            f"SELECT id, emis_uploaded, {'emis_at' if has_emis_at else 'NULL'}, uploaded FROM {TABLE}"
        ):
            if row[3]:
                continue
            if row[1]:
                # 旧 emis_at 取日期部分; 没有/解析不出则日期留空 (只记传过)
                digits = "".join(ch for ch in str(row[2] or "")[:10] if ch.isdigit())
                date = digits if len(digits) == 8 else ""
                conn.execute(
                    f"UPDATE {TABLE} SET uploaded=? WHERE id=?",
                    (f"emis#{date}", row[0]),
                )
        for old_col in ("emis_uploaded", "emis_at"):
            if old_col in cols:
                try:
                    conn.execute(f"ALTER TABLE {TABLE} DROP COLUMN {old_col}")
                except Exception:
                    # 极旧 SQLite 不支持 DROP COLUMN: 旧列留着无害, 代码不再读写
                    pass


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    job = {key: row[key] for key in row.keys()}
    job["meta"] = _loads(job.get("meta"), {})
    job["data"] = _loads(job.get("data"), {})
    job["summary"] = _loads(job.get("summary"), {})
    job["air_curve"] = _loads(job.get("air_curve"), {})
    job["logs"] = _loads(job.get("logs"), [])
    job["uploaded"] = str(job.get("uploaded") or "")
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
    data: dict[str, Any] | None = None,
) -> None:
    """创建工单时建行: state=待执行, started_at/finished_at 为空.

    data 为工单的初始数据快照 (含按 bogies.json 定型的结果数据模板),
    创建即落库, 保证未开始的工单也能查到完整的结果数据结构.
    已存在同 id 的行时不覆盖 (INSERT OR IGNORE), 保证重建/重复调用安全.
    """
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            f"INSERT OR IGNORE INTO {TABLE} "
            "(id, created_at, name, type, user, state, meta, data, logs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                normalize_time(created_at) or local_now(),
                name,
                job_type,
                user,
                STATE_IDLE,
                _dumps(meta or {}),
                _dumps(data or {}),
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
    name: str | None = None,
) -> bool:
    """补录: 单事务内整块更新 summary/meta 两列, 并把审计条目并入 logs 数组.

    name 非空时一并更新作业名 (meta 里的车号/编号改了, 工单名跟着变).
    """
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(f"SELECT logs FROM {TABLE} WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return False
        logs = _loads(row["logs"], [])
        if not isinstance(logs, list):
            logs = []
        logs.extend(entries)
        if name:
            conn.execute(
                f"UPDATE {TABLE} SET summary=?, meta=?, logs=?, name=? WHERE id=?",
                (_dumps(summary), _dumps(meta), _dumps(logs), name, job_id),
            )
        else:
            conn.execute(
                f"UPDATE {TABLE} SET summary=?, meta=?, logs=? WHERE id=?",
                (_dumps(summary), _dumps(meta), _dumps(logs), job_id),
            )
        return True


def _upload_date(at: str | None) -> str:
    """归一为 yyyymmdd; at 为空或解析不出取今天."""
    text = normalize_time(at) if at else ""
    digits = "".join(ch for ch in text[:10] if ch.isdigit())
    if len(digits) == 8:
        return digits
    return datetime.now().strftime("%Y%m%d")


def parse_uploaded(value: object) -> dict[str, str]:
    """解析 uploaded 字符串 -> {目标: 日期}; 容忍空值/旧 0/1/残段, 重段取后者."""
    if value is None:
        return {}
    if isinstance(value, (int, float)):
        # 旧 0/1 值: 1 视为传过 emis (日期未知), 0 视为未传
        return {"emis": ""} if value else {}
    result: dict[str, str] = {}
    for seg in str(value).split("@"):
        seg = seg.strip()
        if not seg:
            continue
        if "#" in seg:
            target, date = seg.split("#", 1)
        else:
            target, date = seg, ""
        target = target.strip().lower()
        if target:
            result[target] = date.strip()
    return result


def format_uploaded(status: dict[str, str]) -> str:
    """{目标: 日期} -> uploaded 字符串; 已知目标在前, 其余按首次出现顺序."""
    ordered = [t for t in UPLOAD_TARGETS if t in status]
    ordered += [t for t in status if t not in UPLOAD_TARGETS]
    return "@".join(f"{t}#{status[t]}" for t in ordered)


def upload_status_text(value: object, targets: tuple[str, ...] = UPLOAD_TARGETS) -> str:
    """展示用: 未传EMIS | 已传ISDP. 已知目标逐个报, 额外目标只报已传."""
    status = parse_uploaded(value)
    parts = [f"{'已传' if t in status else '未传'}{t.upper()}" for t in targets]
    parts += [f"已传{t.upper()}" for t in status if t not in targets]
    return " | ".join(parts)


def upload_all_done(value: object, targets: tuple[str, ...] = UPLOAD_TARGETS) -> bool:
    """已知目标是否都已上传."""
    status = parse_uploaded(value)
    return bool(targets) and all(t in status for t in targets)


def mark_uploaded(
    db_path: str | Path,
    job_id: str,
    *,
    target: str,
    entry: dict[str, Any],
    at: str | None = None,
) -> bool:
    """记录一次上传成功: 替换该目标的段 (只记最后一笔), 并把条目并入 logs 数组."""
    ensure_schema(db_path)
    target = target.strip().lower()
    if not target:
        return False
    with _connect(db_path) as conn:
        row = conn.execute(f"SELECT uploaded, logs FROM {TABLE} WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return False
        status = parse_uploaded(row["uploaded"])
        status[target] = _upload_date(at)
        logs = _loads(row["logs"], [])
        if not isinstance(logs, list):
            logs = []
        logs.append(entry)
        conn.execute(
            f"UPDATE {TABLE} SET uploaded=?, logs=? WHERE id=?",
            (format_uploaded(status), _dumps(logs), job_id),
        )
        return True


def is_completed(job: dict[str, Any] | None) -> bool:
    """完成口径: state=完成 且 summary 非空 (无结果的完成不算已完成作业)."""
    if not job:
        return False
    return job.get("state") == STATE_DONE and bool(job.get("summary"))
