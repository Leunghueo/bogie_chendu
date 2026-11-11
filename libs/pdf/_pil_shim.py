"""
Pillow 最小替身 (仅服务于 openpyxl 插图)。

背景: 打包 (PyInstaller) 环境里没有 Pillow 时, openpyxl 的
openpyxl.drawing.image 在构造 Image 时直接抛
ImportError("You must install Pillow to fetch image objects"),
导致报告里的图片 (模板 CRH 标志、气压曲线页) 全部丢失;
而内嵌解释器又用不了系统 Python 的 Pillow (版本/ABI 不匹配),
往包里塞真 Pillow 体积又过大。

实测 openpyxl (3.0.x 与 3.1.x 的 drawing/image.py 实现一致) 对
PIL 的使用面只有三处:
  1. 模块导入时 `from PIL import Image` 绑定成功与否;
  2. Image.__init__: PIL.Image.open(路径) 取 .size / .format 后 .close();
  3. Image._data(): 再次 open 后, 对 png/jpeg/gif 直接读 .fp 原样字节。
本模块在真 Pillow 缺失时把一个同名替身注册进 sys.modules,
只做文件头尺寸解析 (PNG/JPEG/GIF) 与原始字节透传, 不做任何
图像解码/编码; 真 Pillow 存在时 ensure_pil() 直接返回、不做任何事。
"""
from __future__ import annotations

import builtins
import io
import logging
import struct
import sys
import types
from pathlib import Path

logger = logging.getLogger(__name__)


class Image:
    """占位类: openpyxl 用 isinstance(x, PIL.Image.Image) 判断入参类型。"""


class _ShimImage(Image):
    """PIL.Image.open() 返回值的替身: 只暴露 openpyxl 用到的属性。"""

    def __init__(self, fp, format_name: str, size: tuple[int, int]) -> None:
        self.fp = fp
        self.format = format_name
        self.size = size
        self.width, self.height = size

    def close(self) -> None:
        try:
            if self.fp is not None:
                self.fp.close()
        except Exception:
            pass

    def verify(self) -> None:
        # PIL 的 verify 会校验文件完整性; 替身不做解码, 空实现即可。
        return None

    def save(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise NotImplementedError(
            "内置 Pillow 替身不支持图像转码 (仅支持 png/jpeg/gif 原样插入)"
        )


def _read_header(fp, count: int = 65536) -> bytes:
    fp.seek(0)
    data = fp.read(count)
    fp.seek(0)
    return data


def _parse_jpeg_size(data: bytes) -> tuple[int, int] | None:
    # JPEG 段结构: FF <marker> [<len:2> payload]; SOF0/1/2 的 payload 为
    # precision(1) + height(2) + width(2)。无长度的独立标记: D8/D9/01/D0-D7。
    pos = 2  # 跳过 SOI (FFD8)
    sof_markers = {0xC0, 0xC1, 0xC2}
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        seg_len = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        if marker in sof_markers:
            if pos + 9 <= len(data):
                height, width = struct.unpack(">HH", data[pos + 5 : pos + 9])
                return width, height
            return None
        if seg_len < 2:
            return None
        pos += 2 + seg_len
    return None


def _sniff(data: bytes) -> tuple[str, tuple[int, int]] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "PNG", (width, height)
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return "GIF", (width, height)
    if data.startswith(b"\xff\xd8"):
        size = _parse_jpeg_size(data)
        if size is not None:
            return "JPEG", size
    return None


def open(fp, mode: str = "r"):  # noqa: A002 - 与 PIL.Image.open 同名同签名
    """打开图片文件, 返回带 size/format/fp 的替身对象。

    入参可为路径 (str/Path) 或二进制文件对象 (openpyxl 读带图模板时会传流)。
    """
    if isinstance(fp, (str, Path)):
        stream = builtins.open(fp, "rb")
        close_on_error = True
    else:
        # 传入的是流 (openpyxl 读带图模板时如此): 先整表复制到私有 BytesIO。
        # openpyxl 的 Image._data() 读完会 close 掉 img.fp, 若直接透传
        # 调用方的流, 同一张图第二次取数据 (如重复保存) 就会撞上已关闭的流;
        # 私有副本关掉无妨, 原流保持可重读。
        try:
            fp.seek(0)
        except Exception:
            pass
        stream = io.BytesIO(fp.read())
        close_on_error = True
    try:
        sniffed = _sniff(_read_header(stream))
        if sniffed is None:
            raise ValueError("内置 Pillow 替身仅支持 PNG/JPEG/GIF 格式的图片")
        format_name, size = sniffed
        return _ShimImage(stream, format_name, size)
    except Exception:
        if close_on_error:
            try:
                stream.close()
            except Exception:
                pass
        raise


def _patch_openpyxl(image_mod: types.ModuleType) -> None:
    """修补可能已被导入的 openpyxl.drawing.image 的 PILImage 绑定。

    该模块在导入时把 PIL.Image 绑定为模块全局变量, 若当时 PIL 缺失会
    绑成 False, 之后即使 sys.modules 里有了 PIL 也不会自动恢复。
    """
    oxl_image = sys.modules.get("openpyxl.drawing.image")
    if oxl_image is not None and not getattr(oxl_image, "PILImage", None):
        oxl_image.PILImage = image_mod


def ensure_pil() -> bool:
    """真 Pillow 缺失时注册替身; 返回是否启用了替身。幂等。"""
    existing = sys.modules.get("PIL.Image")
    if existing is not None and getattr(existing, "_is_pil_shim", False):
        _patch_openpyxl(existing)
        return True

    try:
        from PIL import Image as _real_image  # noqa: F401

        return False
    except ImportError:
        pass

    pil_pkg = types.ModuleType("PIL")
    pil_pkg.__path__ = []  # 标记为包, 兼容 `from PIL import Image`
    image_mod = types.ModuleType("PIL.Image")
    image_mod.Image = Image
    image_mod.open = open
    image_mod._is_pil_shim = True
    pil_pkg.Image = image_mod
    sys.modules["PIL"] = pil_pkg
    sys.modules["PIL.Image"] = image_mod
    _patch_openpyxl(image_mod)
    logger.warning("未检测到 Pillow, 已启用内置最小替身 (仅供 openpyxl 插图)")
    return True
