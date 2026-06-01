from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel
import os


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value
    return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    app_name: str = "Russo-Ukrainian War Monitor"
    app_version: str = "0.1.0"
    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "backend" / "app" / "data"
    upload_dir: Path = BASE_DIR / "backend" / "app" / "data" / "uploads"
    ru_dataset_path: Path = BASE_DIR / "RU_Dataset_cleaned.csv"
    conflict_dataset_path: Path = BASE_DIR / "russia_ukraine_conflict.csv"
    mysql_host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user: str = os.getenv("MYSQL_USER", "root")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "")
    mysql_database: str = os.getenv("MYSQL_DATABASE", "rus_ukr_analysis")
    neo4j_uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user: str = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "")
    chat_openai_api_key: str = _env_first("CHAT_OPENAI_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")
    chat_openai_base_url: str = _env_first("CHAT_OPENAI_BASE_URL", "LLM_BASE_URL", "OPENAI_BASE_URL")
    chat_openai_model: str = _env_first("CHAT_OPENAI_MODEL", "LLM_MODEL", "OPENAI_MODEL")
    embedding_openai_api_key: str = _env_first("EMBEDDING_OPENAI_API_KEY", "EMBEDDING_API_KEY")
    embedding_openai_base_url: str = _env_first("EMBEDDING_OPENAI_BASE_URL", "EMBEDDING_BASE_URL")
    embedding_openai_model: str = _env_first("EMBEDDING_OPENAI_MODEL", "EMBEDDING_MODEL")
    openai_api_key: str = _env_first("CHAT_OPENAI_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")
    openai_base_url: str = _env_first("CHAT_OPENAI_BASE_URL", "LLM_BASE_URL", "OPENAI_BASE_URL")
    openai_model: str = _env_first("CHAT_OPENAI_MODEL", "LLM_MODEL", "OPENAI_MODEL")
    openai_request_timeout_sec: float = float(os.getenv("OPENAI_REQUEST_TIMEOUT_SEC", "150"))
    embedding_request_timeout_sec: float = float(os.getenv("EMBEDDING_REQUEST_TIMEOUT_SEC", "25"))
    openai_max_retries: int = int(os.getenv("OPENAI_MAX_RETRIES", "1"))
    qa_request_timeout_sec: float = float(os.getenv("QA_REQUEST_TIMEOUT_SEC", "180"))
    llm_debug_log_raw: bool = _env_bool("LLM_DEBUG_LOG_RAW", True)
    llm_debug_log_chars: int = int(os.getenv("LLM_DEBUG_LOG_CHARS", "4000"))


GRAPH_CONFIG = {
    "allowed_nodes": [
        "军事组织",
        "武器装备",
        "地理位置",
        "冲突事件",
        "行动计划",
        "时间节点",
    ],
    "allowed_relationships": [
        "部署于",
        "隶属于",
        "打击目标",
        "升级为",
        "研发自",
        "参与",
        "导致",
        "支撑",
    ],
}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings
