"""「机」到病除 —— FastAPI 应用入口。

结构 1:1 镜像 huajian-xinsheng/server 的约定（create_app 工厂 / lifespan /
routers / services），只是语言从 TypeScript 换成 Python。

启动：
    cd server && E:/anaconda3/python.exe -m uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import DEFAULT_WEIGHTS, STATIC_DIR, ensure_dirs
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
from .services.detector import Detector

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

    if detector.mode == "normal":
        logger.info("服务就绪 · 模型 %s · %d 类", DEFAULT_WEIGHTS.name, len(detector.model_names))
    else:
        logger.warning("服务以降级模式启动：%s", detector.error)

    yield

    logger.info("服务停止")


def create_app() -> FastAPI:
    ensure_dirs()

    app = FastAPI(
        title="「机」到病除 API",
        description="水稻病虫害智能诊断系统 —— 检测链路",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 阶段一本地开发用；接入 Vite 代理后同源，届时可收紧
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    return app


app = create_app()
