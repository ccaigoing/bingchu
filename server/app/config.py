"""路径与运行参数集中配置。

所有路径均以项目根 `yaodao/` 为基准推导，不写死绝对路径，
这样整个目录可以整体搬走而不需要改配置。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

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

# 定位辅助权重：类无关的通用分割（FastSAM-s，AGPL-3.0，官方 ultralytics 资产）。
# 它**不判病害类型**，只把画面切成一个个对象，用于把「泥水」从病灶候选里减掉。
# 缺这个文件不是错误：分割层会降级，定位回落到纯 HSV 路径。
SEGMENTER_WEIGHTS = MODELS_DIR / "FastSAM-s.pt"

# 分割在**缩放后**的图上跑（最长边）。管线本身不缩放，而 static/uploads/orig/
# 里真实存在 4096x3072 的上传图 —— 不先缩小的话，retina_masks 会把每个 mask
# 上采样回原尺寸，十几个 mask 就是几百 MB。缩到 640 后再把**最终并集**上采样一次。
SEGMENTER_IMGSZ = 640

# 分割层总开关。答辩/调试时可关掉，用于对比"有分割"与"无分割"的输出差异。
SEGMENTER_ENABLED = True

# 虫害闸门权重（IP102 的 YOLO11s，MIT）。
# ⚠️ 它只回答**一个是非题**："这张图里有没有虫"。
# 它给出的**虫种名不可采信** —— 实测同一张幼虫照换四种裁剪得到四个不同答案
# （flax budworm / asiatic rice borer / corn borer / rice leaf caterpillar），
# 所以系统只取它的布尔结论，报「虫害（未定种）」。详见 services/pest_gate.py。
# 缺这个文件不是错误：闸门降级，判型回落原有路径（「疑似病斑」）。
PEST_WEIGHTS = MODELS_DIR / "yolo11s-pest-ip102.pt"

# 闸门阈值。实测依据：
#     三张病害图   conf=0.25 → 0 框    conf=0.5 → 0 框   （病害图上安静）
#     剖茎幼虫照   conf=0.25 → 1 框 0.658
# 取 0.5 是在"别把病害图误判成虫害"上偏保守的一侧 —— 这条链路上误报的代价
# （污染 infectedAreaRatio / severityLevel / counts）远大于漏报。
PEST_GATE_CONF = 0.5

# 闸门总开关。答辩/调试时可关掉，用于对比"有闸门"与"无闸门"的输出差异。
PEST_GATE_ENABLED = True

# 上传校验
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB，对齐 huajian-xinsheng 的 multer 限制
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# 推理参数。
# 本机是 CPU 版 torch（未装 CUDA），imgsz 取 640 是速度与精度的平衡点；
# 后续若装上 CUDA torch，可提到 960/1280 换取小目标召回。
INFER_IMGSZ = 640
DEFAULT_CONF = 0.25
DEFAULT_IOU = 0.45


# ═══════════════════════════════════════════════════════════════
# 部署护栏 —— 本机开发时用不到，公网运行时时缺一条就出事
# ═══════════════════════════════════════════════════════════════
#
# 全部支持环境变量覆盖：改行为不用改代码、不用重新部署。
# systemd unit 里用 Environment= 设，见 deploy/yaodao.service。


def _env_int(name: str, default: int) -> int:
    """读一个整数环境变量。

    值不合法时**回落默认值并留一条 warning**，绝不抛异常 ——
    部署时一个手滑的 `export RATE_PER_MIN=abc` 不该让服务起不来。
    但也不能静默吞掉：那会让人对着"限流怎么没生效"查半天。
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("环境变量 %s=%r 不是整数，回落默认值 %d", name, raw, default)
        return default


# 允许跨域的来源，逗号分隔。**同源部署时保持为空**：
# nginx 把 /api 反代到同一个域名下，浏览器根本不发跨域请求，CORS 中间件
# 一次都不会被触发。空列表 = 不下发任何 CORS 头，这比原来的
# allow_origins=["*"] 收紧得多 —— 那条是阶段一本机开发时为了少配一样东西留的。
# 只有前后端分域部署时才需要设，例如：
#     CORS_ORIGINS=https://yaodao.example.com
CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
]

# 每 IP 限流。默认值是按"2 核 CPU 跑三个模型"这台机器算的：
# 单次识别实测 300–500ms，2 核满打满算约 4 次/秒 —— 但那是**独占**整机。
# 15 次/分钟够一个正常访客反复试几张图；300 次/天挡住脚本刷。
# 注意这两个数只在**单进程** uvicorn 下成立，见 services/guard.py 的说明。
RATE_PER_MIN = _env_int("RATE_PER_MIN", 15)
RATE_PER_DAY = _env_int("RATE_PER_DAY", 300)

# 同时允许几个推理在跑。**这一条比限流更关键**：
# 2 核机器上 N 个请求同时抢 CPU，单次推理会从 300ms 退化到十几秒，
# 在访客眼里就是"服务器挂了"。宁可让后来者排队等一会儿，
# 也不要所有人一起变慢 —— 排队有明确的上限（并发数×单次耗时），
# 争抢没有上限。
INFER_CONCURRENCY = _env_int("INFER_CONCURRENCY", 2)

# 上传图保留天数。**只删图片文件，不删识别记录** ——
# 记录表是答辩要看的东西，让它随时间凭空消失比图片 404 严重得多。
# 0 或负数 = 不清理。
UPLOAD_RETENTION_DAYS = _env_int("UPLOAD_RETENTION_DAYS", 30)

# 清理任务的扫描间隔（小时）。默认 6 小时：这个任务本身很轻（一次目录遍历），
# 但没必要频繁跑 —— 保留期是以天计的。
CLEANUP_INTERVAL_HOURS = _env_int("CLEANUP_INTERVAL_HOURS", 6)


def ensure_dirs() -> None:
    """建齐运行期需要的目录。幂等。"""
    for d in (MODELS_DIR, UPLOAD_ORIG_DIR, UPLOAD_ANNOTATED_DIR, DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)
