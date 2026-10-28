from __future__ import annotations

import configparser
import logging
import sys
from pathlib import Path


BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent

for import_path in (BASE_DIR, BASE_DIR / "libs"):
    text = str(import_path)
    if text not in sys.path:
        sys.path.insert(0, text)

from PySide6.QtWidgets import QApplication, QDialog

from _runtime import get_runtime, update_runtime
from logger import configure_application_logging
from ui.theme import apply_theme
from ui.registry import load_ui_registry
from ui.view_frame.view import Window as MainFrame
from ui.view_login.view import Window as LoginWindow


configure_application_logging(BASE_DIR)
logger = logging.getLogger(__name__)


def _load_runtime() -> dict[str, object]:
    import broker as broker_lib
    import plc as plc_lib
    import vsp as vsp_lib
    import wf as wf_lib
    from broker import create_broker
    from plc import load_pt
    from vsp import load_vsp
    import pdf as pdf_lib
    import push.iot as iot_lib

    _rt = get_runtime()
    broker = create_broker()
    sim=_rt['sim']=='true'
    if _rt["config"].getboolean("plc", "used"):
        plc_table = load_pt(str(_rt["paths"]["plc_config"]),sim=sim)
        plc_table.broker = broker
        plc_table.start_polling()

    if _rt["config"].getboolean("vsp", "used"):
        vsp_table = load_vsp(str(_rt["paths"]["vsp_config"]),sim=sim)
        vsp_table.broker = broker
        vsp_table.start()

    workflow = None
    ui_registry = load_ui_registry()

    # 初始化 PDF 报告生成器
    pdf_report = pdf_lib.PdfReport(
        template_path=str(_rt["paths"]["report_template"]),
        output_dir=str(_rt["paths"]["report_path"])
    )

    # 初始化 IoT 周期推送 (开关: app.ini [iot] enable_iot, 间隔: push/config.json iot.interval)
    iot_pusher = None
    if _rt["config"].getboolean("iot", "enable_iot", fallback=True):
        iot_pusher = iot_lib.create_iot_pusher()
        if iot_pusher is not None:
            iot_pusher.start()
    else:
        logger.info("IoT 推送未启用 (app.ini [iot] enable_iot = false)")

    runtime = update_runtime(
        broker_lib=broker_lib,

        plc_lib = plc_lib if _rt["config"].getboolean("plc", "used") else None,
        plc = plc_table if _rt["config"].getboolean("plc", "used") else None,

        vsp_lib=vsp_lib if _rt["config"].getboolean("vsp", "used") else None,
        vsp=vsp_table  if _rt["config"].getboolean("vsp", "used") else None,

        wf_lib=wf_lib,
        pdf_lib=pdf_lib,
        broker=broker,
        wf=workflow,
        ui_registry=ui_registry,
        pdf_report=pdf_report,
        iot_pusher=iot_pusher,
    )
    return runtime


def main() -> int:
    runtime = _load_runtime()
    logger.info(f"============ 程序启动 ============")
    logger.info(f"初始化运行时")

    def _handle_exception(exc_type, exc_value, exc_traceback) -> None:
        logger.exception("未知异常", exc_info=(exc_type, exc_value, exc_traceback))
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = _handle_exception

    app = QApplication(sys.argv)
    cleanup_done = False

    def _stop_pollers() -> None:
        nonlocal cleanup_done
        if cleanup_done:
            return
        cleanup_done = True

        workflow = runtime.get("wf")
        if workflow is not None:
            try:
                workflow.stop()
            except Exception:
                logger.exception("stop workflow failed")

        plc = runtime.get("plc")
        if plc is not None:
            cancel_pending_actions = getattr(plc, "cancel_pending_actions", None)
            if callable(cancel_pending_actions):
                try:
                    cancel_pending_actions()
                except Exception:
                    logger.exception("cancel plc actions failed")
            logger.info(f"关闭PLC轮询")
            try:
                plc.stop_polling()
            except Exception:
                logger.exception("stop plc polling failed")

        vsp = runtime.get("vsp")
        if vsp is not None:
            logger.info(f"关闭VSP轮询")
            try:
                vsp.stop()
            except Exception:
                logger.exception("stop vsp polling failed")

        broker = runtime.get("broker")
        if broker is not None:
            try:
                broker.clear()
            except Exception:
                logger.exception("clear broker failed")

        iot_pusher = runtime.get("iot_pusher")
        if iot_pusher is not None:
            try:
                iot_pusher.stop()
            except Exception:
                logger.exception("stop iot pusher failed")
        logger.info(f"============ 程序退出 ============")

    app.aboutToQuit.connect(_stop_pollers)
    apply_theme(app, runtime["theme"])
    try:
        login_window = LoginWindow()
        if login_window.exec() != QDialog.Accepted:
            logger.info(f"取消登录")
            return 0

        ui_registry = runtime["ui_registry"]
        main_window = MainFrame(
            menus=ui_registry["menus"],
            views=ui_registry["views"],
            default_view_id=ui_registry["default_view_id"],
            title=ui_registry["window_title"],
            current_user=login_window.username,
        )
        main_window.show()
        return app.exec()
    finally:
        _stop_pollers()


if __name__ == "__main__":
    sys.exit(main())
