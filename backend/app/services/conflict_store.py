from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from datetime import date, datetime
from functools import lru_cache
from typing import Any

import pandas as pd
from pymysql.err import OperationalError

from app.config import get_settings
from app.database import get_database
from app.services.workspace_bootstrap import get_macro_workspace_id

logger = logging.getLogger(__name__)
_import_lock = threading.Lock()

CONFLICT_COLUMNS = [
    "event_id_cnty",
    "event_date",
    "year",
    "time_precision",
    "disorder_type",
    "event_type",
    "sub_event_type",
    "actor1",
    "assoc_actor_1",
    "inter1",
    "actor2",
    "assoc_actor_2",
    "inter2",
    "interaction",
    "civilian_targeting",
    "iso",
    "region",
    "country",
    "admin1",
    "admin2",
    "admin3",
    "location",
    "latitude",
    "longitude",
    "geo_precision",
    "source",
    "source_scale",
    "notes",
    "fatalities",
    "tags",
    "timestamp",
]

EVENT_SELECT = """
    event_code AS event_id_cnty,
    event_date,
    event_date_raw,
    year,
    time_precision,
    disorder_type,
    event_type,
    sub_event_type,
    actor1_name AS actor1,
    actor1_assoc,
    actor1_type,
    actor2_name AS actor2,
    actor2_assoc,
    actor2_type,
    interaction_type,
    civilian_targeting,
    iso_code,
    region,
    country,
    admin1,
    admin2,
    admin3,
    location_name AS location,
    latitude,
    longitude,
    geo_precision,
    source_name AS source,
    source_scale,
    notes,
    fatalities,
    tags,
    source_timestamp
"""


class ConflictStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.conflict_path = self.settings.conflict_dataset_path

    def _workspace_id(self) -> int:
        return get_macro_workspace_id()

    def is_imported(self) -> bool:
        db = get_database()
        wid = self._workspace_id()
        with db.session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM conflict_events WHERE workspace_id = ?",
                (wid,),
            ).fetchone()
            return bool(row and int(row["c"]) > 0)

    def _insert_records(self, records: list[dict[str, Any]], max_retries: int = 5) -> None:
        sql = """
            INSERT INTO conflict_events (
                workspace_id, event_code, event_date, event_date_raw, year,
                time_precision, disorder_type, event_type, sub_event_type,
                actor1_name, actor1_assoc, actor1_type,
                actor2_name, actor2_assoc, actor2_type,
                interaction_type, civilian_targeting,
                iso_code, region, country, admin1, admin2, admin3,
                location_name, latitude, longitude, geo_precision,
                source_name, source_scale, notes, fatalities, tags, source_timestamp
            ) VALUES (
                %(workspace_id)s, %(event_code)s, %(event_date)s, %(event_date_raw)s, %(year)s,
                %(time_precision)s, %(disorder_type)s, %(event_type)s, %(sub_event_type)s,
                %(actor1_name)s, %(actor1_assoc)s, %(actor1_type)s,
                %(actor2_name)s, %(actor2_assoc)s, %(actor2_type)s,
                %(interaction_type)s, %(civilian_targeting)s,
                %(iso_code)s, %(region)s, %(country)s, %(admin1)s, %(admin2)s, %(admin3)s,
                %(location_name)s, %(latitude)s, %(longitude)s, %(geo_precision)s,
                %(source_name)s, %(source_scale)s, %(notes)s, %(fatalities)s, %(tags)s, %(source_timestamp)s
            )
        """
        for attempt in range(max_retries):
            try:
                with get_database().session() as conn:
                    conn.executemany(sql, records)
                return
            except OperationalError as exc:
                if exc.args and exc.args[0] == 1213 and attempt < max_retries - 1:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise

    def import_from_csv(self, batch_size: int = 5000) -> int:
        if not self.conflict_path.exists():
            raise FileNotFoundError(f"冲突数据文件不存在: {self.conflict_path}")

        workspace_id = self._workspace_id()
        self._clear_acled_derived(workspace_id)
        with get_database().session() as conn:
            conn.execute(
                "DELETE FROM conflict_events WHERE workspace_id = ?",
                (workspace_id,),
            )

        total = 0
        for chunk in pd.read_csv(self.conflict_path, chunksize=batch_size):
            chunk = chunk[CONFLICT_COLUMNS].copy()
            chunk["event_date_raw"] = chunk["event_date"].fillna("").astype(str)
            chunk["event_date"] = pd.to_datetime(chunk["event_date"], errors="coerce").dt.date
            for numeric_col in ("year", "time_precision", "iso", "geo_precision", "timestamp"):
                chunk[numeric_col] = pd.to_numeric(chunk[numeric_col], errors="coerce")
            chunk["latitude"] = pd.to_numeric(chunk["latitude"], errors="coerce")
            chunk["longitude"] = pd.to_numeric(chunk["longitude"], errors="coerce")
            chunk["fatalities"] = (
                pd.to_numeric(chunk["fatalities"], errors="coerce").fillna(0).astype(int)
            )
            for col in (
                "disorder_type",
                "event_type",
                "sub_event_type",
                "actor1",
                "assoc_actor_1",
                "inter1",
                "actor2",
                "assoc_actor_2",
                "inter2",
                "interaction",
                "civilian_targeting",
                "region",
                "country",
                "admin1",
                "admin2",
                "admin3",
                "location",
                "source",
                "source_scale",
                "notes",
                "tags",
            ):
                chunk[col] = chunk[col].fillna("").astype(str)

            records = [
                {
                    "workspace_id": workspace_id,
                    "event_code": _clean_str(row["event_id_cnty"]),
                    "event_date": row["event_date"],
                    "event_date_raw": _clean_str(row["event_date_raw"]),
                    "year": _optional_int(row["year"]),
                    "time_precision": _optional_int(row["time_precision"]),
                    "disorder_type": _clean_str(row["disorder_type"]),
                    "event_type": _clean_str(row["event_type"]),
                    "sub_event_type": _clean_str(row["sub_event_type"]),
                    "actor1_name": _clean_str(row["actor1"]),
                    "actor1_assoc": _clean_str(row["assoc_actor_1"]),
                    "actor1_type": _clean_str(row["inter1"]),
                    "actor2_name": _clean_str(row["actor2"]),
                    "actor2_assoc": _clean_str(row["assoc_actor_2"]),
                    "actor2_type": _clean_str(row["inter2"]),
                    "interaction_type": _clean_str(row["interaction"]),
                    "civilian_targeting": _clean_str(row["civilian_targeting"]),
                    "iso_code": _optional_int(row["iso"]),
                    "region": _clean_str(row["region"]),
                    "country": _clean_str(row["country"]),
                    "admin1": _clean_str(row["admin1"]),
                    "admin2": _clean_str(row["admin2"]),
                    "admin3": _clean_str(row["admin3"]),
                    "location_name": _clean_str(row["location"]),
                    "latitude": _optional_float(row["latitude"]),
                    "longitude": _optional_float(row["longitude"]),
                    "geo_precision": _optional_int(row["geo_precision"]),
                    "source_name": _clean_str(row["source"]),
                    "source_scale": _clean_str(row["source_scale"]),
                    "notes": _clean_str(row["notes"]),
                    "fatalities": int(row["fatalities"]),
                    "tags": _clean_str(row["tags"]),
                    "source_timestamp": _optional_int(row["timestamp"]),
                }
                for row in chunk.to_dict(orient="records")
                if _clean_str(row["event_id_cnty"])
            ]
            self._insert_records(records)
            total += len(records)
            logger.info("已导入冲突事件 %s 条", total)
        return total

    def _clear_acled_derived(self, workspace_id: int) -> None:
        with get_database().session() as conn:
            conn.execute(
                """
                DELETE l FROM event_entity_links l
                JOIN conflict_events e ON e.id = l.event_id
                WHERE e.workspace_id = ?
                """,
                (workspace_id,),
            )
            conn.execute(
                "DELETE FROM evidences WHERE workspace_id = ? AND evidence_type = 'acled_note'",
                (workspace_id,),
            )
            conn.execute(
                "DELETE FROM relations WHERE workspace_id = ? AND source_origin = 'acled'",
                (workspace_id,),
            )
            conn.execute(
                "DELETE FROM entities WHERE workspace_id = ? AND source_origin = 'acled'",
                (workspace_id,),
            )

    def ensure_imported(self, force: bool = False) -> int:
        if not force and self.is_imported():
            return self.count()
        with _import_lock:
            if not force and self.is_imported():
                return self.count()
            logger.info("开始从 CSV 导入 conflict_events（请勿并行重复触发）…")
            return self.import_from_csv()

    def count(self) -> int:
        db = get_database()
        wid = self._workspace_id()
        with db.session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM conflict_events WHERE workspace_id = ?",
                (wid,),
            ).fetchone()
            return int(row["c"]) if row else 0

    def knowledge_summary(self) -> dict[str, int]:
        wid = self._workspace_id()
        db = get_database()
        with db.session() as conn:
            entities = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM entities
                WHERE workspace_id = ? AND source_origin = 'acled'
                """,
                (wid,),
            ).fetchone()
            links = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM event_entity_links l
                JOIN conflict_events e ON e.id = l.event_id
                WHERE e.workspace_id = ?
                """,
                (wid,),
            ).fetchone()
            evidences = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM evidences
                WHERE workspace_id = ? AND evidence_type = 'acled_note'
                """,
                (wid,),
            ).fetchone()
            relations = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM relations
                WHERE workspace_id = ? AND source_origin = 'acled'
                """,
                (wid,),
            ).fetchone()
        return {
            "entities": int(entities["c"]) if entities else 0,
            "event_entity_links": int(links["c"]) if links else 0,
            "evidences": int(evidences["c"]) if evidences else 0,
            "relations": int(relations["c"]) if relations else 0,
        }

    def overview(self) -> dict[str, Any]:
        if not self.is_imported():
            return {
                "total_events": 0,
                "date_min": None,
                "date_max": None,
                "total_fatalities": 0,
                "geo_events": 0,
                "event_type_counts": [],
                "admin1_counts": [],
                "source_counts": [],
                "yearly_counts": [],
                "knowledge": self.knowledge_summary(),
            }

        wid = self._workspace_id()
        db = get_database()
        with db.session() as conn:
            summary = conn.execute(
                """
                SELECT COUNT(*) AS total_events,
                       CAST(MIN(event_date) AS CHAR) AS date_min,
                       CAST(MAX(event_date) AS CHAR) AS date_max,
                       COALESCE(SUM(fatalities), 0) AS total_fatalities,
                       SUM(CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL THEN 1 ELSE 0 END) AS geo_events
                FROM conflict_events
                WHERE workspace_id = ?
                """,
                (wid,),
            ).fetchone()
            event_types = _count_items(
                conn,
                "event_type",
                "conflict_events",
                "workspace_id = ? AND event_type IS NOT NULL AND event_type != ''",
                [wid],
                8,
            )
            admin1_counts = _count_items(
                conn,
                "admin1",
                "conflict_events",
                "workspace_id = ? AND admin1 IS NOT NULL AND admin1 != ''",
                [wid],
                8,
            )
            source_counts = _count_items(
                conn,
                "source_name",
                "conflict_events",
                "workspace_id = ? AND source_name IS NOT NULL AND source_name != ''",
                [wid],
                8,
            )
            yearly_rows = conn.execute(
                """
                SELECT CAST(year AS CHAR) AS name, COUNT(*) AS count
                FROM conflict_events
                WHERE workspace_id = ? AND year IS NOT NULL
                GROUP BY year
                ORDER BY year
                """,
                (wid,),
            ).fetchall()

        return {
            "total_events": int(summary["total_events"]) if summary else 0,
            "date_min": summary.get("date_min") if summary else None,
            "date_max": summary.get("date_max") if summary else None,
            "total_fatalities": int(summary["total_fatalities"]) if summary else 0,
            "geo_events": int(summary["geo_events"] or 0) if summary else 0,
            "event_type_counts": event_types,
            "admin1_counts": admin1_counts,
            "source_counts": source_counts,
            "yearly_counts": [{"name": row["name"], "count": int(row["count"])} for row in yearly_rows],
            "knowledge": self.knowledge_summary(),
        }

    def iter_event_batches(self, batch_size: int = 2000) -> Iterator[list[dict[str, Any]]]:
        """按 event_code 顺序分批读取全部事件，供 Neo4j 全量同步。"""
        if not self.is_imported():
            return
        wid = self._workspace_id()
        last_code = ""
        while True:
            db = get_database()
            with db.session() as conn:
                rows = conn.execute(
                    f"""
                    SELECT {EVENT_SELECT}
                    FROM conflict_events
                    WHERE workspace_id = ? AND event_code > ?
                    ORDER BY event_code
                    LIMIT ?
                    """,
                    (wid, last_code, batch_size),
                ).fetchall()
            if not rows:
                break
            batch = [_normalize_event_row(row) for row in rows]
            last_code = batch[-1]["event_id_cnty"]
            yield batch
            if len(batch) < batch_size:
                break

    def _where_clause(
        self,
        year: int | None,
        event_type: str | None,
        admin1: str | None,
        keyword: str | None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = ["workspace_id = ?"]
        params: list[Any] = [self._workspace_id()]
        if year is not None:
            clauses.append("year = ?")
            params.append(year)
        if event_type:
            clauses.append("LOWER(event_type) LIKE ?")
            params.append(f"%{event_type.lower()}%")
        if admin1:
            clauses.append("LOWER(admin1) LIKE ?")
            params.append(f"%{admin1.lower()}%")
        if keyword:
            kw = f"%{keyword.lower()}%"
            clauses.append(
                "(LOWER(notes) LIKE ? OR LOWER(actor1_name) LIKE ? OR LOWER(actor2_name) LIKE ? OR LOWER(location_name) LIKE ?)"
            )
            params.extend([kw, kw, kw, kw])
        return " WHERE " + " AND ".join(clauses), params

    def list_events(
        self,
        limit: int = 100,
        offset: int = 0,
        year: int | None = None,
        event_type: str | None = None,
        admin1: str | None = None,
        keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_imported():
            return []
        where, params = self._where_clause(year, event_type, admin1, keyword)
        db = get_database()
        with db.session() as conn:
            rows = conn.execute(
                f"""
                SELECT {EVENT_SELECT}
                FROM conflict_events
                {where}
                ORDER BY event_date DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return [_normalize_event_row(row) for row in rows]

    def count_events(
        self,
        year: int | None = None,
        event_type: str | None = None,
        admin1: str | None = None,
        keyword: str | None = None,
    ) -> int:
        if not self.is_imported():
            return 0
        where, params = self._where_clause(year, event_type, admin1, keyword)
        with get_database().session() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM conflict_events
                {where}
                """,
                params,
            ).fetchone()
        return int(row["c"]) if row else 0

    def get_event(self, event_id_cnty: str) -> dict[str, Any] | None:
        if not self.is_imported():
            return None
        db = get_database()
        with db.session() as conn:
            row = conn.execute(
                f"""
                SELECT {EVENT_SELECT}
                FROM conflict_events
                WHERE workspace_id = ? AND event_code = ?
                """,
                (self._workspace_id(), event_id_cnty),
            ).fetchone()
        return _normalize_event_row(row) if row else None

    def timeline(
        self,
        limit: int = 2000,
        year: int | None = None,
        event_type: str | None = None,
        admin1: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_imported():
            return []
        where, params = self._where_clause(year, event_type, admin1, None)
        db = get_database()
        with db.session() as conn:
            rows = conn.execute(
                f"""
                SELECT CAST(event_date AS CHAR) AS date, COUNT(*) AS value
                FROM conflict_events
                {where}
                GROUP BY event_date
                ORDER BY event_date
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        return [
            {"date": str(row["date"]), "value": int(row["value"]), "label": str(row["date"])}
            for row in rows
        ]

    def map_points(
        self,
        limit: int = 3000,
        year: int | None = None,
        admin1: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_imported():
            return []
        where, params = self._where_clause(year, None, admin1, None)
        geo = "latitude IS NOT NULL AND longitude IS NOT NULL"
        sql_where = f"{where} AND {geo}"
        db = get_database()
        with db.session() as conn:
            rows = conn.execute(
                f"""
                SELECT event_code AS event_id_cnty, CAST(event_date AS CHAR) AS event_date,
                       event_type, admin1, location_name AS location,
                       latitude, longitude, actor1_name AS actor1, actor2_name AS actor2, fatalities
                FROM conflict_events
                {sql_where}
                ORDER BY event_date DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        return [dict(row) for row in rows]

    def phase_evolution(self, top_types: int = 5) -> dict[str, Any]:
        if not self.is_imported():
            return {"months": [], "event_types": [], "series": [], "fatalities": []}

        wid = self._workspace_id()
        db = get_database()
        with db.session() as conn:
            type_rows = conn.execute(
                """
                SELECT event_type, COUNT(*) AS count
                FROM conflict_events
                WHERE workspace_id = ? AND event_type IS NOT NULL AND event_type != ''
                GROUP BY event_type
                ORDER BY count DESC
                LIMIT ?
                """,
                (wid, top_types),
            ).fetchall()

        event_types = [str(row["event_type"]) for row in type_rows]
        if not event_types:
            return {"months": [], "event_types": [], "series": [], "fatalities": []}

        placeholders = ", ".join(["?"] * len(event_types))
        with db.session() as conn:
            rows = conn.execute(
                f"""
                SELECT DATE_FORMAT(event_date, '%%Y-%%m') AS month, event_type, COUNT(*) AS count
                FROM conflict_events
                WHERE workspace_id = ?
                  AND event_date IS NOT NULL
                  AND event_type IN ({placeholders})
                GROUP BY month, event_type
                ORDER BY month
                """,
                [wid, *event_types],
            ).fetchall()
            fatal_rows = conn.execute(
                """
                SELECT DATE_FORMAT(event_date, '%%Y-%%m') AS month, COALESCE(SUM(fatalities), 0) AS fatalities
                FROM conflict_events
                WHERE workspace_id = ? AND event_date IS NOT NULL
                GROUP BY month
                ORDER BY month
                """,
                (wid,),
            ).fetchall()

        months = sorted({str(row["month"]) for row in rows} | {str(row["month"]) for row in fatal_rows})
        month_index = {month: index for index, month in enumerate(months)}
        series_map = {event_type: [0 for _ in months] for event_type in event_types}
        for row in rows:
            series_map[str(row["event_type"])][month_index[str(row["month"])]] = int(row["count"])

        fatalities = [0 for _ in months]
        for row in fatal_rows:
            fatalities[month_index[str(row["month"])]] = int(row["fatalities"] or 0)

        return {
            "months": months,
            "event_types": event_types,
            "series": [{"name": name, "data": data} for name, data in series_map.items()],
            "fatalities": fatalities,
        }

    def region_event_matrix(self, region_limit: int = 10, type_limit: int = 6) -> dict[str, Any]:
        if not self.is_imported():
            return {"regions": [], "event_types": [], "cells": []}

        wid = self._workspace_id()
        db = get_database()
        with db.session() as conn:
            region_rows = conn.execute(
                """
                SELECT admin1, COUNT(*) AS count
                FROM conflict_events
                WHERE workspace_id = ? AND admin1 IS NOT NULL AND admin1 != ''
                GROUP BY admin1
                ORDER BY count DESC
                LIMIT ?
                """,
                (wid, region_limit),
            ).fetchall()
            type_rows = conn.execute(
                """
                SELECT event_type, COUNT(*) AS count
                FROM conflict_events
                WHERE workspace_id = ? AND event_type IS NOT NULL AND event_type != ''
                GROUP BY event_type
                ORDER BY count DESC
                LIMIT ?
                """,
                (wid, type_limit),
            ).fetchall()

        regions = [str(row["admin1"]) for row in region_rows]
        event_types = [str(row["event_type"]) for row in type_rows]
        if not regions or not event_types:
            return {"regions": regions, "event_types": event_types, "cells": []}

        region_placeholders = ", ".join(["?"] * len(regions))
        type_placeholders = ", ".join(["?"] * len(event_types))
        with db.session() as conn:
            rows = conn.execute(
                f"""
                SELECT admin1, event_type, COUNT(*) AS count
                FROM conflict_events
                WHERE workspace_id = ?
                  AND admin1 IN ({region_placeholders})
                  AND event_type IN ({type_placeholders})
                GROUP BY admin1, event_type
                """,
                [wid, *regions, *event_types],
            ).fetchall()

        return {
            "regions": regions,
            "event_types": event_types,
            "cells": [
                {
                    "region": str(row["admin1"]),
                    "event_type": str(row["event_type"]),
                    "value": int(row["count"]),
                }
                for row in rows
            ],
        }

    def actor_pair_stats(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.is_imported():
            return []

        db = get_database()
        with db.session() as conn:
            rows = conn.execute(
                """
                SELECT actor1_name AS source,
                       actor2_name AS target,
                       interaction_type AS relation_type,
                       COUNT(*) AS count,
                       COALESCE(SUM(fatalities), 0) AS fatalities
                FROM conflict_events
                WHERE workspace_id = ?
                  AND actor1_name IS NOT NULL AND actor1_name != ''
                  AND actor2_name IS NOT NULL AND actor2_name != ''
                GROUP BY actor1_name, actor2_name, interaction_type
                ORDER BY count DESC
                LIMIT ?
                """,
                (self._workspace_id(), limit),
            ).fetchall()
        return [
            {
                "source": row["source"],
                "target": row["target"],
                "relation_type": row.get("relation_type"),
                "count": int(row["count"]),
                "fatalities": int(row["fatalities"] or 0),
            }
            for row in rows
        ]

    def event_chain(self, event_id_cnty: str, window_days: int = 45, limit: int = 40) -> list[dict[str, Any]]:
        seed = self.get_event(event_id_cnty)
        if not seed:
            return []
        actors = [
            actor
            for actor in (seed.get("actor1"), seed.get("actor2"))
            if actor
        ]
        actor1 = actors[0] if actors else "__none__"
        actor2 = actors[1] if len(actors) > 1 else actor1
        db = get_database()
        with db.session() as conn:
            rows = conn.execute(
                f"""
                SELECT {EVENT_SELECT}
                FROM conflict_events
                WHERE workspace_id = ?
                  AND event_code != ?
                  AND event_date BETWEEN DATE_SUB(?, INTERVAL ? DAY) AND DATE_ADD(?, INTERVAL ? DAY)
                  AND (
                    admin1 = ?
                    OR admin2 = ?
                    OR event_type = ?
                    OR actor1_name IN (?, ?)
                    OR actor2_name IN (?, ?)
                  )
                """,
                (
                    self._workspace_id(),
                    event_id_cnty,
                    seed["event_date"],
                    window_days,
                    seed["event_date"],
                    window_days,
                    seed.get("admin1") or "",
                    seed.get("admin2") or "",
                    seed.get("event_type") or "",
                    actor1,
                    actor2,
                    actor1,
                    actor2,
                ),
            ).fetchall()

        ranked: list[dict[str, Any]] = []
        for row in rows:
            event = _normalize_event_row(row)
            score, reasons = _chain_score(seed, event)
            if score <= 0:
                continue
            event["relevance_score"] = round(score, 3)
            event["relevance_reasons"] = reasons
            ranked.append(event)
        ranked.sort(
            key=lambda event: (
                -float(event.get("relevance_score") or 0),
                _date_distance(seed.get("event_date"), event.get("event_date")),
            )
        )
        selected = ranked[: max(0, limit - 1)]
        selected.sort(key=lambda event: (event.get("event_date") or "", event.get("event_id_cnty") or ""))
        seed = {**seed, "relevance_score": 999.0, "relevance_reasons": ["锚点事件"]}
        return [seed, *selected]

    def _region_timeline_window(self, admin1: str, anchor_date: str, window_days: int = 90) -> list[dict[str, Any]]:
        db = get_database()
        with db.session() as conn:
            rows = conn.execute(
                """
                SELECT CAST(event_date AS CHAR) AS date, COUNT(*) AS value
                FROM conflict_events
                WHERE workspace_id = ?
                  AND admin1 = ?
                  AND event_date BETWEEN DATE_SUB(?, INTERVAL ? DAY) AND DATE_ADD(?, INTERVAL ? DAY)
                GROUP BY event_date
                ORDER BY event_date
                """,
                (
                    self._workspace_id(),
                    admin1,
                    anchor_date,
                    window_days,
                    anchor_date,
                    window_days,
                ),
            ).fetchall()
        return [
            {"date": str(row["date"]), "value": int(row["value"]), "label": str(row["date"])}
            for row in rows
        ]

    def event_chain_detail(self, event_id_cnty: str, limit: int = 40) -> dict[str, Any]:
        seed = self.get_event(event_id_cnty)
        if not seed:
            return {
                "anchor": None,
                "chain": [],
                "before": [],
                "after": [],
                "same_region_timeline": [],
                "actor_counts": [],
                "source_counts": [],
                "map_points": [],
                "notes": [],
                "analysis_notes": [],
            }

        admin1 = seed.get("admin1") or ""
        date = seed["event_date"]
        chain = self.event_chain(event_id_cnty, limit=limit)
        before = [
            event
            for event in chain
            if event.get("event_id_cnty") != event_id_cnty and (event.get("event_date") or "") <= date
        ][-12:]
        after = [
            event
            for event in chain
            if event.get("event_id_cnty") != event_id_cnty and (event.get("event_date") or "") >= date
        ][:12]
        actor_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        notes: list[str] = []
        map_points: list[dict[str, Any]] = []
        for event in chain:
            for actor_key in ("actor1", "actor2"):
                actor = (event.get(actor_key) or "").strip()
                if actor:
                    actor_counts[actor] = actor_counts.get(actor, 0) + 1
            source = (event.get("source") or "").strip()
            if source:
                source_counts[source] = source_counts.get(source, 0) + 1
            note = (event.get("notes") or "").strip()
            if note and len(notes) < 8:
                notes.append(note)
            if event.get("latitude") is not None and event.get("longitude") is not None:
                map_points.append(
                    {
                        "event_id_cnty": event["event_id_cnty"],
                        "event_date": event["event_date"],
                        "event_type": event.get("event_type"),
                        "admin1": event.get("admin1"),
                        "location": event.get("location"),
                        "latitude": event["latitude"],
                        "longitude": event["longitude"],
                        "actor1": event.get("actor1"),
                        "actor2": event.get("actor2"),
                        "fatalities": event.get("fatalities"),
                    }
                )

        same_region_timeline = (
            self._region_timeline_window(admin1, date, window_days=90)
            if admin1
            else []
        )
        analysis_notes = _build_chain_analysis_notes(
            seed=seed,
            chain=chain,
            before=before,
            after=after,
            actor_counts=actor_counts,
            source_counts=source_counts,
            same_region_timeline=same_region_timeline,
        )

        return {
            "anchor": seed,
            "chain": chain,
            "before": before,
            "after": after,
            "same_region_timeline": same_region_timeline,
            "actor_counts": [
                {"name": name, "count": count}
                for name, count in sorted(actor_counts.items(), key=lambda item: item[1], reverse=True)[:10]
            ],
            "source_counts": [
                {"name": name, "count": count}
                for name, count in sorted(source_counts.items(), key=lambda item: item[1], reverse=True)[:10]
            ],
            "map_points": map_points[:80],
            "notes": notes,
            "analysis_notes": analysis_notes,
        }

    def source_stats(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.is_imported():
            return []
        db = get_database()
        with db.session() as conn:
            rows = conn.execute(
                """
                SELECT source_name AS name, COUNT(*) AS count
                FROM conflict_events
                WHERE workspace_id = ? AND source_name IS NOT NULL AND source_name != ''
                GROUP BY source_name
                ORDER BY count DESC
                LIMIT ?
                """,
                (self._workspace_id(), limit),
            ).fetchall()
        return [{"name": row["name"], "count": int(row["count"]), "source_type": "acled"} for row in rows]

    def search_for_global(self, question: str, limit: int = 12) -> list[dict[str, Any]]:
        terms = [t for t in question.replace("，", " ").replace("。", " ").split() if len(t) >= 2]
        keyword = terms[0] if terms else question[:20]
        return self.list_events(limit=limit, keyword=keyword)

    def filter_options(self) -> dict[str, Any]:
        if not self.is_imported():
            return {"years": [], "admin1": []}
        wid = self._workspace_id()
        db = get_database()
        with db.session() as conn:
            years = conn.execute(
                """
                SELECT DISTINCT year FROM conflict_events
                WHERE workspace_id = ? AND year IS NOT NULL
                ORDER BY year
                """,
                (wid,),
            ).fetchall()
            admin_rows = conn.execute(
                """
                SELECT admin1 AS name, COUNT(*) AS count
                FROM conflict_events
                WHERE workspace_id = ? AND admin1 IS NOT NULL AND admin1 != ''
                GROUP BY admin1
                ORDER BY count DESC
                LIMIT 40
                """,
                (wid,),
            ).fetchall()
        return {
            "years": [int(row["year"]) for row in years],
            "admin1": [{"name": row["name"], "count": int(row["count"])} for row in admin_rows],
        }

    def aggregate_stats(self, question: str) -> dict[str, Any]:
        events = self.search_for_global(question, limit=500)
        if not events:
            return {"total": 0, "by_type": [], "by_admin1": []}
        frame = pd.DataFrame(events)
        by_type = (
            frame.groupby("event_type").size().reset_index(name="count").sort_values("count", ascending=False).head(8)
        )
        by_admin1 = (
            frame.groupby("admin1").size().reset_index(name="count").sort_values("count", ascending=False).head(8)
        )
        return {
            "total": len(events),
            "by_type": by_type.to_dict(orient="records"),
            "by_admin1": by_admin1.to_dict(orient="records"),
        }


def _normalize_event_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if out.get("event_date") is not None:
        val = out["event_date"]
        out["event_date"] = val.isoformat() if hasattr(val, "isoformat") else str(val)
    for key in ("latitude", "longitude"):
        if out.get(key) is not None:
            out[key] = float(out[key])
    return out


def _date_obj(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def _date_distance(a: object, b: object) -> int:
    da = _date_obj(a)
    db = _date_obj(b)
    if not da or not db:
        return 99999
    return abs((da - db).days)


def _build_chain_analysis_notes(
    *,
    seed: dict[str, Any],
    chain: list[dict[str, Any]],
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    actor_counts: dict[str, int],
    source_counts: dict[str, int],
    same_region_timeline: list[dict[str, Any]],
) -> list[str]:
    related = [event for event in chain if event.get("event_id_cnty") != seed.get("event_id_cnty")]
    reason_counts: dict[str, int] = {}
    scores: list[float] = []
    for event in related:
        try:
            scores.append(float(event.get("relevance_score") or 0))
        except (TypeError, ValueError):
            pass
        for reason in event.get("relevance_reasons") or []:
            label = str(reason).split("：", 1)[0].strip()
            if label:
                reason_counts[label] = reason_counts.get(label, 0) + 1

    top_reasons = "、".join(
        f"{name}{count}次"
        for name, count in sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)[:3]
    )
    top_actors = "、".join(
        f"{name}（{count}）"
        for name, count in sorted(actor_counts.items(), key=lambda item: item[1], reverse=True)[:3]
    )
    top_sources = "、".join(
        f"{name}（{count}）"
        for name, count in sorted(source_counts.items(), key=lambda item: item[1], reverse=True)[:2]
    )
    timeline_total = sum(int(item.get("value") or 0) for item in same_region_timeline)
    peak = max(same_region_timeline, key=lambda item: int(item.get("value") or 0), default=None)
    avg_score = sum(scores) / len(scores) if scores else 0.0

    notes = [
        (
            f"围绕锚点共筛出 {len(related)} 条邻近事件，其中锚点前 {len(before)} 条、锚点后 {len(after)} 条；"
            f"平均关联评分 {avg_score:.1f}。"
        ),
        (
            f"主要连接依据为 {top_reasons or '同地区、同主体、同类型与时间距离'}；"
            "评分越高表示与锚点在空间、主体和事件类型上重合越多。"
        ),
        f"链路中的高频主体为 {top_actors or '暂无高频主体'}；主要来源为 {top_sources or '暂无集中来源'}。",
    ]
    if peak:
        notes.append(
            f"锚点所在一级地区前后 90 天共记录 {timeline_total} 条事件，峰值出现在 {peak.get('date')}，当日 {peak.get('value')} 条。"
        )
    return notes


def _chain_score(seed: dict[str, Any], event: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    if seed.get("admin1") and seed.get("admin1") == event.get("admin1"):
        score += 3.0
        reasons.append("同一一级地区")
    if seed.get("admin2") and seed.get("admin2") == event.get("admin2"):
        score += 2.0
        reasons.append("同一二级地区")
    if seed.get("location") and seed.get("location") == event.get("location"):
        score += 2.5
        reasons.append("同一地点")
    if seed.get("event_type") and seed.get("event_type") == event.get("event_type"):
        score += 2.0
        reasons.append("同一事件类型")
    if seed.get("sub_event_type") and seed.get("sub_event_type") == event.get("sub_event_type"):
        score += 1.0
        reasons.append("同一子事件类型")

    seed_actors = {str(v) for v in (seed.get("actor1"), seed.get("actor2")) if v}
    event_actors = {str(v) for v in (event.get("actor1"), event.get("actor2")) if v}
    overlap = sorted(seed_actors.intersection(event_actors))
    if overlap:
        score += 4.0 + min(2.0, len(overlap))
        reasons.append("同参与主体：" + "、".join(overlap[:2]))

    distance = _date_distance(seed.get("event_date"), event.get("event_date"))
    if distance <= 45:
        score += max(0.0, 4.5 - distance / 10)
        reasons.append(f"时间距离 {distance} 天")

    fatalities = int(event.get("fatalities") or 0)
    if fatalities > 0:
        score += min(1.5, fatalities / 50)
        reasons.append("存在伤亡记录")
    return score, reasons[:5]


def _clean_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _count_items(
    conn: Any,
    column: str,
    table: str,
    where: str,
    params: list[Any],
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT {column} AS name, COUNT(*) AS count
        FROM {table}
        WHERE {where}
        GROUP BY {column}
        ORDER BY count DESC
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    return [{"name": row["name"], "count": int(row["count"])} for row in rows]


@lru_cache(maxsize=1)
def get_conflict_store() -> ConflictStore:
    return ConflictStore()
