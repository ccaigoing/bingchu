"""路径与运行参数集中配置。

所有路径均以项目根 `yaodao/` 为基准推导，不写死绝对路径，
这样整个目录可以整体搬走而不需要改配置。
"""

from __future__ import annotations

from pathlib import Path

# server/app/config.py  →  上溯三级到 yaodao/
ROOT = Path(__file__).resolve().parents[2]

MODELS_DIR = ROOT / "models"
STATIC_DIR = ROOT / "server" / "static"
UPLOAD_ORIG_DIR = STATIC_DIR / "uploads" / "orig"
UPLOAD_ANNOTATED_DIR = STATIC_DIR / "uploads" / "annotated"
DATA_DIR = ROOT / "server" / "data"
DB_PATH = DATA_DIR / "yaodao.db"

# 检测权重。方案里"之后换权重 = 改一行路径"指的就是这里。
DEFAULT_WEIGHTS = MODELS_DIR / "jktk_x.pt"

# 上传校验
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB，对齐 huajian-xinsheng 的 multer 限制
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# 推理参数。
# 本机是 CPU 版 torch（未装 CUDA），imgsz 取 640 是速度与精度的平衡点；
# 后续若装上 CUDA torch，可提到 960/1280 换取小目标召回。
INFER_IMGSZ = 640
DEFAULT_CONF = 0.25
DEFAULT_IOU = 0.45


def ensure_dirs() -> None:
    """建齐运行期需要的目录。幂等。"""
    for d in (MODELS_DIR, UPLOAD_ORIG_DIR, UPLOAD_ANNOTATED_DIR, DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)
