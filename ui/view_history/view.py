from __future__ import annotations

import copy
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from _runtime import get_runtime
from libs import jobstore
from libs.wf.base import utc_now

logger = logging.getLogger(__name__)

# 作业记录自 bogie.db 的 TblFlowJob 表读取 (一行一次作业, 见 libs/jobstore.py):
# summary / meta / air_curve 都是行上的独立字段, 不再扫描日志文件推导.

_RESULT_KEYS = ["测量值", "最小值", "最大值", "单位", "结论"]
_RESULT_HEADERS = ["项目", "测量值", "最小值", "最大值", "单位", "结论"]

_LOG_LIST_HEADERS = ["日期", "类型", "名称", "ID", "上传EMIS"]

def _summary_rows(job: dict[str, Any] | None) -> list[dict[str, Any]]:
    """把作业的 summary 字段展开为结果表格行.

    summary 形如 {"1位轮重": {"测量值": 300, "最小值": 250, ...}, ...};
    "打印"为 False 的数据项不展示 (与导出报告、结果对话框保持一致).
    """
    results: list[dict[str, Any]] = []
    summary = (job or {}).get("summary")
    if not isinstance(summary, dict):
        return results
    for item_name, item_data in summary.items():
        if not isinstance(item_data, dict):
            continue
        if not item_data.get("打印", False):
            continue
        row: dict[str, Any] = {"项目": item_name}
        for key in _RESULT_KEYS:
            row[key] = item_data.get(key, "-")
        results.append(row)
    return results


def _job_result_data(job: dict[str, Any] | None) -> dict[str, Any]:
    """作业的完整结果数据 = summary 字段本身."""
    summary = (job or {}).get("summary")
    return summary if isinstance(summary, dict) else {}


def _job_meta(job: dict[str, Any] | None) -> dict[str, Any]:
    """作业的 meta 字段; 缺"工作流名称"时用作业名兜底注入 (表格列展示用)."""
    meta = dict((job or {}).get("meta") or {})
    if "工作流名称" not in meta and (job or {}).get("name"):
        meta["工作流名称"] = str(job["name"])
    return meta


def _job_air_curves(job: dict[str, Any] | None) -> dict[str, Any]:
    """作业的空簧气压曲线 = air_curve 字段; 无曲线时返回 {}."""
    curves = (job or {}).get("air_curve")
    return curves if isinstance(curves, dict) else {}


def _decimal_digits(item: dict[str, Any], default: int = 2) -> int:
    """取数据项配置的小数位数(item["小数"]); 缺失或非法时回退到默认 2 位."""
    raw = item.get("小数")
    try:
        digits = int(raw)
    except (TypeError, ValueError):
        return default
    return digits if digits >= 0 else default


def _format_decimal(value: Any, digits: int) -> Any:
    """按指定小数位格式化数值; 非数值(如 '-'、空串)原样返回."""
    if isinstance(value, bool):
        return value
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return value


def _default_printer() -> str:
    """查询 CUPS 默认打印机名(lpstat -d); 未配置/查询失败时返回空串."""
    import shutil
    import subprocess

    if shutil.which("lpstat") is None:
        return ""
    try:
        proc = subprocess.run(
            ["lpstat", "-d"], capture_output=True, text=True, timeout=10
        )
    except Exception:  # noqa: BLE001
        return ""
    if proc.returncode != 0:
        return ""
    # 输出形如 "system default destination: XXX" / "系统默认目标：XXX"
    text = (proc.stdout or "").strip()
    for sep in (":", "："):
        if sep in text:
            return text.split(sep, 1)[1].strip()
    return ""


def _print_pdf(path: Path) -> None:
    """把 PDF 送到系统默认打印机(跨平台), 失败时抛 RuntimeError.

    Linux(银河麒麟 V10 / Ubuntu 等)走 CUPS: 依次尝试 lp / lpr 命令,
    依赖系统已安装 cups-client 并在 CUPS 中设置了默认打印机;
    Windows 走 ShellExecute 的 "print" 谓词(由 PDF 关联程序静默打印).
    """
    import shutil
    import subprocess
    import sys

    if not path.exists():
        raise RuntimeError(f"报告文件不存在: {path}")

    if sys.platform == "win32":
        os.startfile(str(path), "print")  # noqa: S606  # Windows 打印谓词
        return

    # Linux: CUPS 命令行, lp 优先, 缺失则回退 lpr
    command = next((name for name in ("lp", "lpr") if shutil.which(name)), None)
    if command is None:
        raise RuntimeError(
            "未找到打印命令 lp/lpr, 请先安装 CUPS 客户端(cups-client / cups)并配置默认打印机"
        )

    try:
        proc = subprocess.run(
            [command, str(path)], capture_output=True, text=True, timeout=60
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("打印超时, 请检查打印机状态与 CUPS 服务(cups.service)")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            f"{command} 打印失败({proc.returncode}): {detail or '未知错误, 请检查默认打印机是否配置'}"
        )


def _open_folder(folder: Path) -> None:
    """使用系统文件管理器打开文件夹(跨平台)."""
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            os.startfile(str(folder))  # noqa: S606  # Windows 资源管理器
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception:
        logger.exception("failed to open folder: %s", folder)


class Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.runtime = get_runtime()
        self._all_logs: list[dict[str, str]] = []
        self._jobs_by_id: dict[str, dict[str, Any]] = {}
        self._build_ui()
        self._refresh_logs()

    def _job_db_path(self) -> Path:
        return Path(self.runtime["paths"]["db"])

    def _current_job(self) -> dict[str, Any] | None:
        selected = self.log_table.selectedItems()
        if not selected:
            return None
        job_id = self._job_id_at_row(selected[0].row())
        return self._jobs_by_id.get(job_id)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # 顶部搜索框区域
        root.addWidget(self._build_search_bar())

        # 中部与底部的分割器
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.addWidget(self._build_log_list_panel())
        splitter.addWidget(self._build_result_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([240, 480])
        root.addWidget(splitter, 1)

    def _build_search_bar(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("historySearchBar")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        label = QLabel("日期:", panel)
        layout.addWidget(label)

        self.date_input = QLineEdit(panel)
        self.date_input.setPlaceholderText("例如 2026-09-27 或 20260927")
        self.date_input.setClearButtonEnabled(True)
        self.date_input.returnPressed.connect(self._on_search)
        layout.addWidget(self.date_input, 1)

        self.search_button = QPushButton("搜索", panel)
        self.search_button.setCursor(Qt.PointingHandCursor)
        self.search_button.clicked.connect(self._on_search)
        layout.addWidget(self.search_button)

        self.refresh_button = QPushButton("刷新", panel)
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self._refresh_logs)
        layout.addWidget(self.refresh_button)

        return panel

    def _build_log_list_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("historyLogListPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("搜索结果列表", panel)
        title.setObjectName("cardTitle")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        self.log_table = QTableWidget(0, len(_LOG_LIST_HEADERS), panel)
        self.log_table.setHorizontalHeaderLabels(_LOG_LIST_HEADERS)
        self.log_table.horizontalHeader().setStretchLastSection(True)
        self.log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.itemSelectionChanged.connect(self._on_log_selected)
        layout.addWidget(self.log_table, 1)

        # 导出报告 / 上传EMIS 按钮(位于搜索结果列表与日志结果列表之间)
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(6)

        self.export_button = QPushButton("导出报告", panel)
        self.export_button.setCursor(Qt.PointingHandCursor)
        self.export_button.clicked.connect(self._on_export)
        button_row.addWidget(self.export_button)

        self.upload_emis_button = QPushButton("上传EMIS", panel)
        self.upload_emis_button.setCursor(Qt.PointingHandCursor)
        self.upload_emis_button.clicked.connect(self._on_upload_emis)
        button_row.addWidget(self.upload_emis_button)

        self.amend_button = QPushButton("补录数据", panel)
        self.amend_button.setCursor(Qt.PointingHandCursor)
        self.amend_button.clicked.connect(self._on_amend_data)
        button_row.addWidget(self.amend_button)

        self.print_button = QPushButton("打印", panel)
        self.print_button.setCursor(Qt.PointingHandCursor)
        self.print_button.clicked.connect(self._on_print)
        button_row.addWidget(self.print_button)

        button_row.addStretch()
        layout.addLayout(button_row)

        return panel

    def _build_result_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("historyResultPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("所选日志结果列表", panel)
        title.setObjectName("cardTitle")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        self.result_table = QTableWidget(0, len(_RESULT_HEADERS), panel)
        self.result_table.setHorizontalHeaderLabels(_RESULT_HEADERS)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.verticalHeader().setVisible(False)
        layout.addWidget(self.result_table, 1)

        return panel

    def _refresh_logs(self) -> None:
        """从作业库加载全部有 summary 结果的作业记录."""
        self._all_logs.clear()
        self._jobs_by_id = {}
        try:
            jobs = jobstore.list_jobs(self._job_db_path(), require_summary=True)
        except Exception:
            logger.exception("加载作业记录失败")
            jobs = []
        for job in jobs:
            job_id = str(job.get("id") or "")
            if not job_id:
                continue
            self._jobs_by_id[job_id] = job
            meta = job.get("meta") or {}
            created = str(job.get("created_at") or "")
            self._all_logs.append(
                {
                    "job_id": job_id,
                    "date": created,
                    "date_raw": created.replace("-", "").replace(":", "").replace(" ", ""),
                    "type": str(job.get("type") or meta.get("流程") or ""),
                    "name": str(job.get("name") or ""),
                    "id": job_id[:8],
                    "emis_uploaded": bool(job.get("emis_uploaded")),
                }
            )
        self._on_search()

    def _on_search(self) -> None:
        """根据日期搜索框内容过滤日志列表."""
        keyword = self.date_input.text().strip()
        filtered = self._all_logs
        if keyword:
            # 支持模糊匹配: 只要日期字符串中包含关键字即可
            filtered = [log for log in self._all_logs if keyword in log.get("date", "") or keyword in log.get("date_raw", "")]
        self._render_log_table(filtered)

    def _render_log_table(self, logs: list[dict[str, str]]) -> None:
        self.log_table.setRowCount(0)
        for row_index, log_info in enumerate(logs):
            self.log_table.insertRow(row_index)
            emis_status = "已上传" if log_info.get("emis_uploaded") else "未上传"
            values = [
                log_info.get("date", ""),
                log_info.get("type", ""),
                log_info.get("name", ""),
                log_info.get("id", ""),
                emis_status,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col_index == 0:
                    # 作业 id 不单独展示, 存入首列的数据角色供后续取用
                    item.setData(Qt.ItemDataRole.UserRole, log_info.get("job_id", ""))
                if col_index == 4:
                    # 上传状态列居中显示, 已上传用绿色加粗
                    if log_info.get("emis_uploaded"):
                        item.setForeground(Qt.GlobalColor.darkGreen)
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                self.log_table.setItem(row_index, col_index, item)
        # 自动调整列宽
        self.log_table.resizeColumnsToContents()
        self.result_table.setRowCount(0)

    def _job_id_at_row(self, row: int) -> str:
        """从表格行中取出对应的作业 id (存储在首列的 UserRole 中)."""
        item = self.log_table.item(row, 0)
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _on_log_selected(self) -> None:
        """用户选中某行作业后, 显示该作业 summary 字段的结果."""
        job = self._current_job()
        if job is None:
            self.result_table.setRowCount(0)
            return
        self._render_result_table(_summary_rows(job))

    def _render_result_table(self, results: list[dict[str, Any]]) -> None:
        self.result_table.setRowCount(0)
        for row_index, result in enumerate(results):
            self.result_table.insertRow(row_index)
            values = [
                result.get("项目", ""),
                str(result.get("测量值", "-")),
                str(result.get("最小值", "-")),
                str(result.get("最大值", "-")),
                str(result.get("单位", "-")),
                str(result.get("结论", "-")),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.result_table.setItem(row_index, col_index, item)
        self.result_table.resizeColumnsToContents()

    def _build_report_pdf(self, job: dict[str, Any]) -> Path:
        """将选中作业的 summary 数据填充 PDF 模板, 导出到 report.path 并返回 PDF 路径.

        失败时抛出异常, 由调用方统一提示.
        """
        result_data = _job_result_data(job)
        if not result_data:
            raise ValueError("该作业中没有 summary 结果数据")
        meta = _job_meta(job)

        # 填充 PDF 模板单元格
        maps: dict[str, Any] = {}
        pdf_row = 6  # 模板数据区起始行(表头在第5行)
        for name, item in result_data.items():
            if not isinstance(item, dict):
                continue
            # "打印"为 False 的数据项不填充 (未配置该字段时同样视为不打印)
            if not item.get("打印", False):
                continue
            digits = _decimal_digits(item)          # 小数位, 未配置按 2 位
            maps[f"B{pdf_row}"] = pdf_row - 5       # 序号
            maps[f"C{pdf_row}"] = name              # 名称
            maps[f"D{pdf_row}"] = _format_decimal(item.get("测量值", "-"), digits)   # 测量值
            maps[f"F{pdf_row}"] = item.get("最小值", "-")   # 最小值
            maps[f"G{pdf_row}"] = item.get("最大值", "-")   # 最大值
            maps[f"H{pdf_row}"] = item.get("单位", "-")     # 单位
            maps[f"I{pdf_row}"] = item.get("结论", "-")     # 结果
            pdf_row += 1

        maps["C3"] = meta.get("车型", "")
        maps["E3"] = meta.get("位号", "")
        maps["H3"] = meta.get("车号", "")
        maps["C4"] = meta.get("用户", "")
        maps["E4"] = meta.get("互检员", "")
        maps["H4"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 导出到 app.ini 配置的 report.path 目录, 文件名: 日期_作业id前8位.pdf
        pdf_handler = self.runtime["pdf_report"]
        pdf_handler.load_template()
        pdf_handler.set_cells(maps)
        created = str(job.get("created_at") or "")
        try:
            date_part = datetime.strptime(created, "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d-%H%M%S")
        except ValueError:
            date_part = "unknown-time"
        output_name = f"{date_part}_{str(job.get('id') or '')[:8]}.pdf"
        return Path(pdf_handler.export_pdf(output_name))

    def _on_export(self) -> None:
        """导出报告: 将选中作业的 summary 数据填充 PDF 模板, 导出到 report.path"""
        from PySide6.QtWidgets import QMessageBox

        selected = self.log_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请先在搜索结果列表中选择一条作业记录")
            return
        job = self._current_job()
        if job is None:
            return

        try:
            output_path = self._build_report_pdf(job)
        except Exception as exc:
            logger.exception("failed to export pdf report: %s", job.get("id"))
            QMessageBox.critical(self, "导出失败", f"导出报告失败:\n{exc}")
            return
        QMessageBox.information(self, "导出成功", f"报告已导出到:\n{output_path}")
        # 直接打开报告文件夹
        _open_folder(Path(output_path).parent)

    def _on_print(self) -> None:
        """打印: 生成当前所选作业的报告 PDF, 并用默认打印机直接打印."""
        from PySide6.QtWidgets import QMessageBox

        selected = self.log_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请先在搜索结果列表中选择一条作业记录")
            return
        job = self._current_job()
        if job is None:
            return

        try:
            output_path = self._build_report_pdf(job)
            printer = _default_printer()
            _print_pdf(output_path)
        except Exception as exc:
            logger.exception("failed to print pdf report: %s", job.get("id"))
            QMessageBox.critical(self, "打印失败", f"打印报告失败:\n{exc}")
            return
        logger.info("报告已发送到默认打印机: %s", output_path)
        target = f"打印机: {printer}\n" if printer else ""
        QMessageBox.information(
            self, "已打印", f"报告已发送到默认打印机:\n{target}{output_path}"
        )

    def _on_amend_data(self) -> None:
        """补录数据: 打开所选作业的结果对话框, 允许用户修改后回写作业库.

        回写方式为整块更新该作业行的 summary 与 meta 字段 (单事务),
        同时把补录条目并入 logs 数组留痕; 现行值只认字段, 不靠追加推导。
        """
        from PySide6.QtWidgets import QDialog, QMessageBox

        from ui.dialog_result.view import ResultDialog

        selected = self.log_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请先在搜索结果列表中选择一条作业记录")
            return
        job = self._current_job()
        if job is None:
            return

        result_data = copy.deepcopy(_job_result_data(job))
        if not result_data:
            QMessageBox.warning(self, "提示", "该作业中没有 summary 结果数据, 无法补录")
            return
        meta = _job_meta(job)

        # 与历史列表/导出报告保持一致: 只展示"打印"为真的数据项,
        # 未展示的数据项在回写时原样保留(写回的是完整的 result_data)
        items = [
            (name, item)
            for name, item in result_data.items()
            if isinstance(item, dict) and item.get("打印", False)
        ]
        if not items:
            # 老数据可能缺少"打印"标记, 兜底为全部数据项, 避免无法补录
            items = [
                (name, item) for name, item in result_data.items() if isinstance(item, dict)
            ]
        if not items:
            QMessageBox.warning(self, "提示", "该作业中没有可编辑的结果数据")
            return

        dialog = ResultDialog(
            items,
            self,
            result_store=result_data,
            checker=str(meta.get("互检员") or ""),
        )
        dialog.setWindowTitle("补录数据")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        meta["互检员"] = dialog.checker
        job_id = str(job.get("id") or "")
        try:
            ok = jobstore.amend_job(
                self._job_db_path(),
                job_id,
                summary=result_data,
                meta=meta,
                entries=[
                    {
                        "消息源": "补录",
                        "event": "summary",
                        "timestamp": utc_now(),
                        "state": "完成",
                        "extra": result_data,
                    },
                    {
                        "消息源": "补录",
                        "event": "meta_update",
                        "timestamp": utc_now(),
                        "state": "完成",
                        "meta": meta,
                    },
                ],
            )
            if not ok:
                raise RuntimeError("作业记录不存在")
        except Exception:
            logger.exception("补录数据写入作业库失败: %s", job_id)
            QMessageBox.critical(self, "补录失败", "补录数据写入作业库失败, 详情见当天日志")
            return

        # 刷新列表, 并重新展示补录后的结果
        self._refresh_logs()
        refreshed = self._jobs_by_id.get(job_id)
        self._render_result_table(_summary_rows(refreshed))
        logger.info("补录数据成功: %s", job_id)
        QMessageBox.information(self, "补录成功", "数据已补录并保存")

    def _on_upload_emis(self) -> None:
        """上传当前选中作业的 summary 数据到 EMIS.

        数据完全来自作业库行, 不依赖运行中的 workflow.
        试验时间: 起始取作业创建时间, 结束取作业完成时间.
        """
        from PySide6.QtWidgets import QMessageBox
        from libs.push.all import PushConfigError, emis

        selected = self.log_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请先在搜索结果列表中选择一条作业记录")
            return
        job = self._current_job()
        if job is None:
            return
        job_id = str(job.get("id") or "")

        result_data = _job_result_data(job)
        if not result_data:
            QMessageBox.warning(self, "提示", "该作业中没有 summary 结果数据, 无法上传")
            return
        meta = _job_meta(job)
        # 空簧保压曲线 (无 air_curve 时为 {}, 上传时 khbyLine1/2 为空)
        air_curves = _job_air_curves(job)

        check_start = str(job.get("created_at") or "") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        check_end = str(job.get("finished_at") or "") or check_start

        try:
            emis(
                summary=result_data,
                meta=meta,
                check_start=check_start,
                check_end=check_end,
                air_curves=air_curves or None,
            )
            # 在作业行上置 EMIS 已上传标志, 并把上传条目并入 logs 留痕
            try:
                jobstore.mark_emis_uploaded(
                    self._job_db_path(),
                    job_id,
                    entry={
                        "消息源": "emis",
                        "event": "upload",
                        "timestamp": utc_now(),
                        "state": "完成",
                    },
                )
            except Exception:
                logger.exception("写入 EMIS 上传记录到作业库失败: %s", job_id)
            # 刷新列表, 让当前行的"上传EMIS"列即时显示为"已上传"
            self._refresh_logs()
            logger.info("上传 EMIS 成功: %s", job_id)
            QMessageBox.information(self, "上传成功", "数据成功上传EMIS")
        except PushConfigError as exc:
            # 配置问题(文件缺失/JSON 非法), 与网络上报失败区分开
            logger.exception("上传 EMIS 失败(推送配置错误), 作业: %s", job_id)
            QMessageBox.critical(
                self,
                "推送配置错误",
                f"{exc}\n\n该错误已记录到当天日志",
            )
        except RuntimeError as exc:
            logger.exception("上传 EMIS 失败, 作业: %s", job_id)
            message = str(exc)
            # S_REFUSED 属于"调用成功但数据不被接受", 用警示而非错误样式
            if "S_REFUSED" in message:
                QMessageBox.warning(
                    self,
                    "上传被拒绝",
                    f"EMIS 返回 S_REFUSED：\n接口调用成功, 数据或操作不被接受\n\n"
                    f"{message}\n\n该错误已记录到当天日志",
                )
            else:
                QMessageBox.critical(
                    self, "上传失败", f"{message}\n\n该错误已记录到当天日志"
                )
