# 成都静载上位机程序

成都静载试验台上位机程序（PySide6），入口为 `main.py`，配置见 `app.ini`。

## 推送说明

- 本仓库由 `src.zip` 的文本文件快照推送而来；`__pycache__` 已排除。
- `runtime/push/config.json` 中的 IoT 口令已改为占位符 `YOUR_IOT_PASSWORD`，拉取后请在本地填回真实口令再运行，不要把真实口令提交进公开仓库。
- 以下二进制文件无法走文本快照通道，需手动上传到对应目录：
  - `runtime/db/bogie.db`
  - `runtime/pdf/abc.xlsx`
  - `runtime/res/icon/`（图标）
  - `runtime/res/image/`（图片）
