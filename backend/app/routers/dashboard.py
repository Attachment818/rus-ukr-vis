"""Dashboard data API for map sandbox visualization."""
from __future__ import annotations

from fastapi import APIRouter, Query
from app.database import get_database

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/map-heatmap")
def map_heatmap(
    year: int | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=8000, ge=100, le=30000),
) -> list[dict]:
    """Return lat/lng points with event metadata for map plotting."""
    db = get_database()
    conditions = ["latitude IS NOT NULL", "longitude IS NOT NULL"]
    params: list = []
    if year:
        conditions.append("year = ?")
        params.append(year)
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    where = " AND ".join(conditions)
    with db.session() as conn:
        rows = conn.execute(
            f"""
            SELECT event_code, event_date, event_type, sub_event_type,
                   actor1_name, actor2_name, admin1, location_name,
                   latitude, longitude, fatalities
            FROM conflict_events
            WHERE {where}
            ORDER BY event_date DESC
            LIMIT ?
            """,
            tuple(params) + (limit,),
        ).fetchall()
    return [
        {
            "event_code": r["event_code"],
            "event_date": str(r["event_date"]) if r["event_date"] else None,
            "event_type": r["event_type"],
            "sub_event_type": r["sub_event_type"],
            "actor1": r["actor1_name"],
            "actor2": r["actor2_name"],
            "admin1": r["admin1"],
            "location": r["location_name"],
            "latitude": float(r["latitude"]) if r["latitude"] else None,
            "longitude": float(r["longitude"]) if r["longitude"] else None,
            "fatalities": int(r["fatalities"] or 0),
        }
        for r in rows
    ]


@router.get("/region-stats")
def region_stats(year: int | None = Query(default=None)) -> list[dict]:
    """Aggregated event counts and fatalities by admin1 region."""
    db = get_database()
    conditions = ["admin1 IS NOT NULL", "admin1 != ''"]
    params: list = []
    if year:
        conditions.append("year = ?")
        params.append(year)
    where = " AND ".join(conditions)
    with db.session() as conn:
        rows = conn.execute(
            f"""
            SELECT admin1,
                   COUNT(*) AS event_count,
                   SUM(COALESCE(fatalities, 0)) AS total_fatalities,
                   AVG(latitude) AS center_lat,
                   AVG(longitude) AS center_lng
            FROM conflict_events
            WHERE {where}
            GROUP BY admin1
            ORDER BY event_count DESC
            """,
            tuple(params),
        ).fetchall()
    return [
        {
            "region": r["admin1"],
            "event_count": int(r["event_count"]),
            "total_fatalities": int(r["total_fatalities"] or 0),
            "center_lat": round(float(r["center_lat"]), 4) if r["center_lat"] else None,
            "center_lng": round(float(r["center_lng"]), 4) if r["center_lng"] else None,
        }
        for r in rows
    ]


@router.get("/timeline-daily")
def timeline_daily(
    year: int | None = Query(default=None),
    admin1: str | None = Query(default=None),
) -> list[dict]:
    """Daily event counts for area/line charts."""
    db = get_database()
    conditions: list[str] = []
    params: list = []
    if year:
        conditions.append("year = ?")
        params.append(year)
    if admin1:
        conditions.append("admin1 = ?")
        params.append(admin1)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with db.session() as conn:
        rows = conn.execute(
            f"""
            SELECT event_date, COUNT(*) AS cnt, SUM(COALESCE(fatalities, 0)) AS fat
            FROM conflict_events
            {where}
            GROUP BY event_date
            ORDER BY event_date
            """,
            tuple(params),
        ).fetchall()
    return [
        {
            "date": str(r["event_date"]),
            "count": int(r["cnt"]),
            "fatalities": int(r["fat"] or 0),
        }
        for r in rows
    ]


@router.get("/event-type-distribution")
def event_type_distribution(year: int | None = Query(default=None)) -> list[dict]:
    """Event type counts for pie/treemap/bar charts."""
    db = get_database()
    conditions: list[str] = []
    params: list = []
    if year:
        conditions.append("year = ?")
        params.append(year)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with db.session() as conn:
        rows = conn.execute(
            f"""
            SELECT event_type, COUNT(*) AS cnt,
                   SUM(COALESCE(fatalities, 0)) AS fat
            FROM conflict_events
            {where}
            GROUP BY event_type
            ORDER BY cnt DESC
            """,
            tuple(params),
        ).fetchall()
    return [
        {
            "event_type": r["event_type"],
            "count": int(r["cnt"]),
            "fatalities": int(r["fat"] or 0),
        }
        for r in rows
    ]


@router.get("/yearly-stats")
def yearly_stats() -> list[dict]:
    """Year-by-year summary for trend analysis."""
    db = get_database()
    with db.session() as conn:
        rows = conn.execute(
            """
            SELECT year, COUNT(*) AS cnt,
                   SUM(COALESCE(fatalities, 0)) AS fat,
                   COUNT(DISTINCT admin1) AS regions,
                   COUNT(DISTINCT event_type) AS types
            FROM conflict_events
            WHERE year IS NOT NULL
            GROUP BY year
            ORDER BY year
            """
        ).fetchall()
    return [
        {
            "year": int(r["year"]),
            "count": int(r["cnt"]),
            "fatalities": int(r["fat"] or 0),
            "regions": int(r["regions"]),
            "event_types": int(r["types"]),
        }
        for r in rows
    ]


@router.get("/top-actors")
def top_actors(limit: int = Query(default=15, ge=5, le=50)) -> list[dict]:
    """Most frequent actors in conflict events."""
    db = get_database()
    with db.session() as conn:
        rows = conn.execute(
            """
            SELECT actor1_name AS actor, COUNT(*) AS cnt
            FROM conflict_events
            WHERE actor1_name IS NOT NULL AND actor1_name != ''
            GROUP BY actor1_name
            UNION ALL
            SELECT actor2_name AS actor, COUNT(*) AS cnt
            FROM conflict_events
            WHERE actor2_name IS NOT NULL AND actor2_name != ''
            GROUP BY actor2_name
            """
        ).fetchall()
    # Aggregate
    from collections import defaultdict
    actor_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        actor_counts[r["actor"]] += int(r["cnt"])
    sorted_actors = sorted(actor_counts.items(), key=lambda x: -x[1])[:limit]
    return [{"actor": a, "count": c} for a, c in sorted_actors]


@router.get("/animation-frames")
def animation_frames(
    interval: str = Query(default="day", description="day, week, or month"),
) -> dict:
    """Return events grouped by time interval for animation playback.

    Returns a dict with:
      - frames: list of {date, events: [{lat, lng, type, fatalities, ...}], cumulative_count, day_count}
      - date_range: [min_date, max_date]
      - total_frames: count
      - total_events: sum of all events
    """
    db = get_database()

    if interval == "week":
        date_expr = "DATE_FORMAT(event_date, '%Y-%W')"
        date_label_expr = "MIN(event_date)"
    elif interval == "month":
        date_expr = "DATE_FORMAT(event_date, '%Y-%m')"
        date_label_expr = "MIN(event_date)"
    else:
        date_expr = "event_date"
        date_label_expr = "event_date"

    with db.session() as conn:
        # Get date range
        range_row = conn.execute(
            "SELECT MIN(event_date) AS d1, MAX(event_date) AS d2 FROM conflict_events WHERE event_date IS NOT NULL"
        ).fetchone()

        # Get events grouped by date, with event details
        rows = conn.execute(
            f"""
            SELECT {date_label_expr} AS frame_date,
                   event_date, event_code, event_type, sub_event_type,
                   actor1_name, actor2_name, admin1, location_name,
                   latitude, longitude, fatalities
            FROM conflict_events
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
              AND event_date IS NOT NULL
            ORDER BY event_date
            """
        ).fetchall()

    # Group events by frame_date
    from collections import OrderedDict
    frames_map: OrderedDict[str, list] = OrderedDict()
    total = 0
    for r in rows:
        key = str(r["frame_date"])
        if key not in frames_map:
            frames_map[key] = []
        frames_map[key].append({
            "event_date": str(r["event_date"]),
            "event_code": r["event_code"],
            "event_type": r["event_type"],
            "sub_event_type": r["sub_event_type"],
            "actor1": r["actor1_name"],
            "actor2": r["actor2_name"],
            "admin1": r["admin1"],
            "location": r["location_name"],
            "latitude": float(r["latitude"]) if r["latitude"] else None,
            "longitude": float(r["longitude"]) if r["longitude"] else None,
            "fatalities": int(r["fatalities"] or 0),
        })
        total += 1

    cumulative = 0
    frames = []
    for date_key, events in frames_map.items():
        cumulative += len(events)
        day_fatalities = sum(e["fatalities"] for e in events)
        frames.append({
            "date": date_key,
            "events": events,
            "day_count": len(events),
            "day_fatalities": day_fatalities,
            "cumulative_count": cumulative,
        })

    return {
        "frames": frames,
        "date_range": [str(range_row["d1"]) if range_row else None, str(range_row["d2"]) if range_row else None],
        "total_frames": len(frames),
        "total_events": total,
    }
