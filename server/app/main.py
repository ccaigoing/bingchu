
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import CORS_ORIGINS, DEFAULT_WEIGHTS, STATIC_DIR, ensure_dirs
from .db import init_db
from .routers import (
    alert,
    catalog,
    detect,
    effect,
    monitor,
    overview,
    spray,
    visualize,
)
from .services.cleanup import cleanup_loop
from .services.detector import Detector
from .services.guard import client_ip, limiter
from .services.pest_gate import PestGate
from .services.segmenter import Segmenter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动即预热模型，避免首个请求承担冷启动代价。"""
    ensure_dirs()
    # 建表（CREATE TABLE IF NOT EXISTS，不删数据）。
    # 数据由 `python -m app.seed` 灌入，故意不在这里自动跑 ——
    # 启动时静默重建数据库会让"改了哪一版数据"变得不可追溯。
    init_db()

    detector = Detector(DEFAULT_WEIGHTS)
    detector.load()
    app.state.detector = detector

    # 定位辅助：类无关分割，只用于把泥水从病灶候选里减掉。
    # 它降级不影响判型（YOLO），只让定位回落纯 HSV 路径。
    segmenter = Segmenter()
    segmenter.load()
    app.state.segmenter = segmenter

    # 虫害闸门：只回答"有没有虫"，**不取它的虫种判定**（定种不可靠，见 pest_gate.py）。
    # 它降级不影响判型，只让"主判型说不出话"的那条路继续报「疑似病斑」。
    pest_gate = PestGate()
    pest_gate.load()
    app.state.pest_gate = pest_gate

    if detector.mode == "normal":
        logger.info("服务就绪 · 模型 %s · %d 类", DEFAULT_WEIGHTS.name, len(detector.model_names))
    else:
        logger.warning("服务以降级模式启动：%s", detector.error)

    if segmenter.mode == "normal":
        logger.info("定位分割就绪 · %s", segmenter.weights.name)
    else:
        logger.warning("定位分割降级（定位走纯 HSV）：%s", segmenter.error)

    if pest_gate.mode == "normal":
        logger.info("虫害闸门就绪 · %s · conf>=%.2f",
                    pest_gate.weights.name, pest_gate.conf)
    else:
        logger.warning("虫害闸门降级（判型回落「疑似病斑」）：%s", pest_gate.error)

    # 上传图过期清理：后台协程，随服务生命周期起停。
    # 它是"护栏"不是"备份" —— 只在本进程活着时跑。服务停机期间没人能上传，
    # 磁盘不会涨，所以停机不清也不出问题；再启动时 cleanup_loop 是**先扫再睡**，
    # 积压的过期图会在几十秒内被清掉。
    cleaner = asyncio.create_task(cleanup_loop(), name="upload-cleanup")

    yield

    # 先取消后台任务再退出，否则 uvicorn 关停时会报"任务未被 await"
    cleaner.cancel()
    with suppress(asyncio.CancelledError):
        await cleaner

    logger.info("服务停止")


def create_app() -> FastAPI:
    ensure_dirs()

    app = FastAPI(
        title="「机」到病除 API",
        description="水稻病虫害智能诊断系统 —— 检测链路",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS **默认不下发**（CORS_ORIGINS 为空 = 一条 CORS 头都不带）。
    # 同源部署（nginx 把 /api 反代到同一个域名下）时浏览器根本不发跨域请求，
    # 这个中间件一次都不会被触发 —— 所以默认空是收紧，不是"忘了配"。
    # 原来写死的 allow_origins=["*"] 是阶段一本机开发时为了少配一样东西留的，
    # 上公网必须收掉：那等于允许任意网站替访客调我们的接口。
    # 只有前后端分域部署时才设 CORS_ORIGINS 环境变量把它打开。
    if CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=CORS_ORIGINS,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ── 公网护栏：只拦 POST /api/detect ──
    # 这是一个**昂贵**端点（一次完整的模型推理，2 核机器上 300–500ms），
    # 而且是唯一对公网开放写入的入口。其余 /api/* 都是毫秒级的读库请求，
    # 给它们上同样的配额只会误伤正常浏览，而它们本身不构成资源风险。
    #
    # 并发闸门不在这里 —— 它要包住**推理那一段**而不是整个请求
    # （读文件、解码、写库、画标注图都不该占着闸门），见 routers/detect.py。
    @app.middleware("http")
    async def guard_detect(request: Request, call_next):
        if request.method == "POST" and request.url.path == "/api/detect":
            ip = client_ip(request)
            allowed, retry_after = limiter.check(ip)
            if not allowed:
                logger.warning(
                    "限流拒绝 %s（%d 秒后可再试）", ip, retry_after
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "请求过于频繁，请稍后再试",
                        "code": "RATE_LIMITED",
                        # 把额度写出来，让访客知道等多久、上限是多少，
                        # 而不是只看到一句"太频繁了"
                        "detail": (
                            f"每个 IP 每分钟 {limiter.per_min} 次、"
                            f"每天 {limiter.per_day} 次；请 {retry_after} 秒后再试"
                        ),
                    },
                    headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)

    # 标注图与原图直接静态暴露，前端 <img> 直接引用
    app.mount("/uploads", StaticFiles(directory=str(STATIC_DIR / "uploads")), name="uploads")

    # 一屏一路由：每屏的端点在各自模块里，main 只负责挂上来。
    # catalog 是跨屏共用的字典（类别 / 产品 / 模型登记 / 数据溯源 / 知识条目）。
    for r in (
        catalog.router,   # /classes /products /models /datasets /knowledge
        overview.router,  # /overview
        monitor.router,   # /monitor /sensors/*
        detect.router,    # /detect/* /health
        visualize.router, # /visualize /field/* /analytics/*
        alert.router,     # /alert /warnings /thresholds
        spray.router,     # /spray/*
        effect.router,    # /effect/*
    ):
        app.include_router(r)

    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)

    return app


# ── 错误体统一 ────────────────────────────────────────────
#
# 计划里的契约是 `{ error, code, detail? }`，但 FastAPI 默认发
# `{"detail": "..."}`。不统一的话，前端的 ApiError 读不到 error 字段，
# 界面上只会显示"请求失败（HTTP 404）"—— 真正的原因（"预警 999 不存在"）
# 就丢在响应体里没人看。答辩现场这类信息是唯一能定位问题的线索。

CODE_BY_STATUS = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_ERROR",
}


async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else None
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": detail or "请求失败",
            "code": CODE_BY_STATUS.get(exc.status_code, "ERROR"),
            "detail": detail,
        },
    )


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """把 pydantic 的报错压成一句人话。原样透传是个嵌套数组，前端显示不出来。

    只取第一条 —— 参数校验失败时通常就是同一个原因，列全了反而看不清。
    """
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", ()) if x != "body")
    msg = f"{loc}：{first.get('msg', '参数不合法')}" if loc else str(first.get("msg", "参数不合法"))
    return JSONResponse(
        status_code=422,
        content={"error": msg, "code": "VALIDATION_ERROR", "detail": msg},
    )


app = create_app()
