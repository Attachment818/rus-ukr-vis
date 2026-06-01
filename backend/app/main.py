import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.database import get_database
from app.routers.datasets import router as datasets_router
from app.routers.documents import router as documents_router
from app.routers.graph import router as graph_router
from app.routers.health import router as health_router
from app.routers.intelligence import router as intelligence_router
from app.routers.llm import router as llm_router
from app.routers.qa import router as qa_router
from app.routers.query import router as query_router
from app.services.neo4j_service import get_neo4j_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        get_database().init()
        logger.info("MySQL 连接成功")
    except Exception as exc:
        logger.error(
            "MySQL 无法连接（127.0.0.1:3306）。请在 Windows 服务中启动 MySQL80，或在 Navicat 中启动本地实例。详情: %s",
            exc,
        )

    try:
        neo4j = get_neo4j_service()
        neo4j.ensure_constraints()
        ok, msg = neo4j.verify()
        if ok:
            logger.info("Neo4j 连接成功: %s", msg)
        else:
            logger.warning("Neo4j 不可用: %s", msg)
            if "Unauthorized" in msg or "authentication" in msg.lower():
                logger.warning(
                    "Neo4j 密码与 .env 中 NEO4J_PASSWORD 不一致。"
                    "请在 Neo4j Desktop 打开实例 → 查看/重置密码，并写入 .env 后重启后端。"
                )
            if "AuthenticationRateLimit" in msg:
                logger.warning("Neo4j 登录尝试过多已限流，请等待约 1 分钟再重启后端。")
    except Exception as exc:
        logger.warning("Neo4j 初始化跳过: %s", exc)

    try:
        from app.services.workspace_bootstrap import get_macro_workspace_id

        wid = get_macro_workspace_id()
        logger.info("宏观工作空间 id=%s；冲突 CSV 将在首次访问数据集 API 时导入 MySQL", wid)
    except Exception as exc:
        logger.error("MySQL 初始化失败: %s", exc)

    yield

    try:
        get_neo4j_service().close()
    except Exception:
        pass


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:5176",
        "http://127.0.0.1:5176",
        "http://localhost:5177",
        "http://127.0.0.1:5177",
        "http://localhost:5178",
        "http://127.0.0.1:5178",
        "http://localhost:5179",
        "http://127.0.0.1:5179",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """浏览器打开 http://127.0.0.1:8000/ 时跳转到交互式 API 文档。"""
    return RedirectResponse(url="/docs")


app.include_router(health_router)
app.include_router(datasets_router)
app.include_router(documents_router)
app.include_router(intelligence_router)
app.include_router(graph_router)
app.include_router(qa_router)
app.include_router(query_router)
app.include_router(llm_router)
