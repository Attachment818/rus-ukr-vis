from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.config import get_settings
from app.database import get_database
from app.services.conflict_store import get_conflict_store
from app.services.neo4j_service import get_neo4j_service
from app.services.weibo_store import get_weibo_store


class DatasetService:
    def __init__(self) -> None:
        settings = get_settings()
        self.ru_path = settings.ru_dataset_path
        self.conflict_store = get_conflict_store()
        self.weibo_store = get_weibo_store()

    @staticmethod
    def _read_csv(path: Path, nrows: int | None = None) -> pd.DataFrame:
        return pd.read_csv(path, nrows=nrows)

    @staticmethod
    def _optional_str(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip() or None

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _normalize_weibo_row(self, row: dict) -> dict:
        return {
            "index": int(row["index"]),
            "created_at": self._optional_str(row.get("created_at")),
            "pub_time": self._optional_str(row.get("pub_time")),
            "msg_id": self._optional_str(row.get("msg_id")),
            "text": self._optional_str(row.get("text")),
            "screen_name": self._optional_str(row.get("screen_name")),
            "source": self._optional_str(row.get("source")),
            "reposts_count": self._optional_int(row.get("reposts_count")),
            "comments_count": self._optional_int(row.get("comments_count")),
            "attitudes_count": self._optional_int(row.get("attitudes_count")),
        }

    @staticmethod
    def _count_rows(path: Path) -> int:
        with path.open("rb") as handle:
            return max(sum(1 for _ in handle) - 1, 0)

    def summarize(self) -> list[dict]:
        ru_head = self._read_csv(self.ru_path, nrows=0)
        conflict_count = (
            self.conflict_store.count()
            if self.conflict_store.is_imported()
            else 0
        )
        weibo_count = (
            self.weibo_store.count() if self.weibo_store.is_imported() else self._count_rows(self.ru_path)
        )
        return [
            {
                "dataset": "公开文本样本（默认微博适配器）",
                "total_rows": weibo_count,
                "columns": list(ru_head.columns),
            },
            {
                "dataset": "公开事件数据（默认 ACLED 适配器）",
                "total_rows": conflict_count,
                "columns": [
                    "event_id_cnty",
                    "event_date",
                    "year",
                    "event_type",
                    "sub_event_type",
                    "actor1",
                    "actor2",
                    "admin1",
                    "location",
                    "latitude",
                    "longitude",
                    "source",
                    "notes",
                    "fatalities",
                ],
            },
        ]

    def get_conflict_events(
        self,
        limit: int = 100,
        offset: int = 0,
        year: int | None = None,
        event_type: str | None = None,
        admin1: str | None = None,
        keyword: str | None = None,
    ) -> list[dict]:
        return self.conflict_store.list_events(
            limit=limit, offset=offset, year=year, event_type=event_type, admin1=admin1, keyword=keyword
        )

    def get_conflict_filters(self) -> dict:
        return self.conflict_store.filter_options()

    def get_conflict_overview(self) -> dict:
        return self.conflict_store.overview()

    def get_weibo_posts(self, limit: int = 100, offset: int = 0, keyword: str | None = None) -> list[dict]:
        if self.weibo_store.is_imported():
            return self.weibo_store.list_posts(limit=limit, offset=offset, keyword=keyword)
        wanted = [
            "index",
            "created_at",
            "pub_time",
            "msg_id",
            "text",
            "screen_name",
            "source",
            "reposts_count",
            "comments_count",
            "attitudes_count",
        ]
        if keyword:
            term = keyword.lower()
            matched: list[dict] = []
            skipped = 0
            for chunk in pd.read_csv(self.ru_path, chunksize=3000, low_memory=False):
                available = [column for column in wanted if column in chunk.columns]
                frame = chunk[available].copy()
                text = frame.get("text", pd.Series("", index=frame.index)).fillna("").astype(str).str.lower()
                screen_name = frame.get("screen_name", pd.Series("", index=frame.index)).fillna("").astype(str).str.lower()
                source = frame.get("source", pd.Series("", index=frame.index)).fillna("").astype(str).str.lower()
                filtered = frame[text.str.contains(term, regex=False) | screen_name.str.contains(term, regex=False) | source.str.contains(term, regex=False)]
                for row in filtered.to_dict(orient="records"):
                    if skipped < offset:
                        skipped += 1
                        continue
                    matched.append(self._normalize_weibo_row(row))
                    if len(matched) >= limit:
                        return matched
            return matched
        frame = pd.read_csv(
            self.ru_path,
            skiprows=range(1, offset + 1) if offset > 0 else None,
            nrows=limit,
        )
        records = frame[[column for column in wanted if column in frame.columns]].to_dict(orient="records")
        return [self._normalize_weibo_row(row) for row in records]

    def count_weibo_posts(self, keyword: str | None = None) -> int:
        if self.weibo_store.is_imported():
            return self.weibo_store.count_posts(keyword=keyword)
        if not keyword:
            return self._count_rows(self.ru_path)
        term = keyword.lower()
        total = 0
        for chunk in pd.read_csv(self.ru_path, chunksize=5000, low_memory=False):
            text = chunk.get("text", pd.Series("", index=chunk.index)).fillna("").astype(str).str.lower()
            screen_name = chunk.get("screen_name", pd.Series("", index=chunk.index)).fillna("").astype(str).str.lower()
            source = chunk.get("source", pd.Series("", index=chunk.index)).fillna("").astype(str).str.lower()
            total += int(
                (text.str.contains(term, regex=False)
                 | screen_name.str.contains(term, regex=False)
                 | source.str.contains(term, regex=False)).sum()
            )
        return total

    def get_conflict_timeline(
        self,
        limit: int = 2000,
        year: int | None = None,
        event_type: str | None = None,
        admin1: str | None = None,
    ) -> list[dict]:
        return self.conflict_store.timeline(limit=limit, year=year, event_type=event_type, admin1=admin1)

    def get_conflict_map(
        self,
        limit: int = 3000,
        year: int | None = None,
        admin1: str | None = None,
    ) -> list[dict]:
        return self.conflict_store.map_points(limit=limit, year=year, admin1=admin1)

    def get_phase_evolution(self) -> dict:
        return self.conflict_store.phase_evolution()

    def get_region_event_matrix(self) -> dict:
        return self.conflict_store.region_event_matrix()

    def get_actor_pair_stats(self, limit: int = 20) -> list[dict]:
        return self.conflict_store.actor_pair_stats(limit=limit)

    def get_conflict_event(self, event_id_cnty: str) -> dict | None:
        return self.conflict_store.get_event(event_id_cnty)

    def get_event_chain(self, event_id_cnty: str, limit: int = 40) -> list[dict]:
        return self.conflict_store.event_chain(event_id_cnty, limit=limit)

    def get_event_chain_detail(self, event_id_cnty: str, limit: int = 40) -> dict:
        return self.conflict_store.event_chain_detail(event_id_cnty, limit=limit)

    def get_source_stats(self) -> dict:
        acled = self.conflict_store.source_stats(limit=15)
        weibo_frame = self._read_csv(self.ru_path, nrows=5000)
        if "screen_name" in weibo_frame.columns:
            weibo_stats = (
                weibo_frame["screen_name"]
                .fillna("未知")
                .value_counts()
                .head(10)
                .reset_index()
            )
            weibo_stats.columns = ["name", "count"]
            weibo = [
                {"name": row["name"], "count": int(row["count"]), "source_type": "weibo"}
                for _, row in weibo_stats.iterrows()
            ]
        else:
            weibo = []
        return {"acled": acled, "weibo": weibo}

    @staticmethod
    def _count_table(conn, table_name: str) -> int:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table_name}").fetchone()
        return int(row["c"]) if row else 0

    def get_processing_pipeline(self) -> dict:
        raw_acled = self.conflict_store.count() if self.conflict_store.is_imported() else self._count_rows(self.conflict_store.conflict_path)
        raw_weibo = self.weibo_store.count() if self.weibo_store.is_imported() else self._count_rows(self.ru_path)
        knowledge = self.conflict_store.knowledge_summary()

        with get_database().session() as conn:
            mysql_events = self._count_table(conn, "conflict_events")
            mysql_posts = self._count_table(conn, "public_opinion_posts")
            documents = self._count_table(conn, "documents")
            chunks = self._count_table(conn, "document_chunks")
            chunk_embeddings = self._count_table(conn, "chunk_embeddings")

        try:
            neo4j_counts = get_neo4j_service().graph_counts()
        except Exception:
            neo4j_counts = {}

        neo4j_nodes = sum(value for key, value in neo4j_counts.items() if key != "relationships")
        neo4j_relationships = int(neo4j_counts.get("relationships", 0))
        mysql_total = mysql_events + mysql_posts + documents + chunks
        knowledge_total = (
            knowledge["entities"]
            + knowledge["event_entity_links"]
            + knowledge["evidences"]
            + knowledge["relations"]
        )

        def _status(count: int) -> str:
            return "done" if count > 0 else "pending"

        stages = [
            {
                "id": "raw",
                "name": "主题数据输入",
                "count": raw_acled + raw_weibo + documents,
                "status": _status(raw_acled + raw_weibo + documents),
                "detail": f"事件数据 {raw_acled:,} 条，文本样本 {raw_weibo:,} 条，上传文档 {documents:,} 份",
            },
            {
                "id": "mysql",
                "name": "MySQL 清洗存储",
                "count": mysql_total,
                "status": _status(mysql_total),
                "detail": f"结构化事件 {mysql_events:,}，文本样本 {mysql_posts:,}，文档 {documents:,}，chunk {chunks:,}",
            },
            {
                "id": "knowledge",
                "name": "结构化知识层",
                "count": knowledge_total,
                "status": _status(knowledge_total),
                "detail": f"实体 {knowledge['entities']:,}，事件-实体链接 {knowledge['event_entity_links']:,}，证据 {knowledge['evidences']:,}，关系 {knowledge['relations']:,}",
            },
            {
                "id": "embedding",
                "name": "文档向量索引",
                "count": chunk_embeddings,
                "status": _status(chunk_embeddings),
                "detail": f"已向量化 chunk {chunk_embeddings:,} 个，用于语义相似度检索",
            },
            {
                "id": "neo4j",
                "name": "Neo4j 图组织",
                "count": neo4j_nodes + neo4j_relationships,
                "status": _status(neo4j_nodes + neo4j_relationships),
                "detail": f"节点 {neo4j_nodes:,}，关系 {neo4j_relationships:,}",
            },
            {
                "id": "retrieval",
                "name": "检索与问答",
                "count": max(mysql_events, chunks),
                "status": _status(max(mysql_events, chunks)),
                "detail": "支持 global / local / event_chain / evidence 四类查询",
            },
            {
                "id": "visual",
                "name": "可视化呈现",
                "count": 8,
                "status": "done",
                "detail": "态势指标、时间线、地图热点、地区矩阵、主体关系、事件链、知识图谱、证据面板",
            },
        ]
        edges = [
            {"source": "主题数据输入", "target": "MySQL 清洗存储", "value": max(1, mysql_total), "label": "导入/解析"},
            {"source": "MySQL 清洗存储", "target": "结构化知识层", "value": max(1, knowledge_total), "label": "实体/关系/证据派生"},
            {"source": "MySQL 清洗存储", "target": "文档向量索引", "value": max(1, chunk_embeddings), "label": "chunk embedding"},
            {"source": "结构化知识层", "target": "Neo4j 图组织", "value": max(1, neo4j_nodes + neo4j_relationships), "label": "图谱同步/抽取"},
            {"source": "MySQL 清洗存储", "target": "检索与问答", "value": max(1, mysql_events + chunks), "label": "结构化检索"},
            {"source": "文档向量索引", "target": "检索与问答", "value": max(1, chunk_embeddings), "label": "语义召回"},
            {"source": "Neo4j 图组织", "target": "检索与问答", "value": max(1, neo4j_nodes), "label": "子图扩展"},
            {"source": "检索与问答", "target": "可视化呈现", "value": 8, "label": "联动展示"},
        ]
        return {
            "stages": stages,
            "edges": edges,
            "metrics": {
                "raw_acled": raw_acled,
                "raw_weibo": raw_weibo,
                "mysql_events": mysql_events,
                "mysql_posts": mysql_posts,
                "documents": documents,
                "chunks": chunks,
                "chunk_embeddings": chunk_embeddings,
                "neo4j_nodes": neo4j_nodes,
                "neo4j_relationships": neo4j_relationships,
                **knowledge,
            },
        }


@lru_cache(maxsize=1)
def get_dataset_service() -> DatasetService:
    return DatasetService()
