"""Generate GeoJSON region boundaries from conflict event coordinates.

For each admin1 region, compute the convex hull of event locations.
This creates data-driven region boundaries for the map overlay.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

import os
import pymysql


def convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Monotone chain convex hull algorithm. Returns points in CCW order."""
    if len(points) < 3:
        return points
    # Remove duplicates and sort
    points = sorted(set((round(p[0], 5), round(p[1], 5)) for p in points))
    if len(points) < 3:
        return points

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def buffer_hull(hull: list[tuple[float, float]], padding_deg: float = 0.3) -> list[tuple[float, float]]:
    """Expand a convex hull outward by approximately padding_deg degrees."""
    if len(hull) < 3:
        return hull
    # Compute centroid
    cx = sum(p[0] for p in hull) / len(hull)
    cy = sum(p[1] for p in hull) / len(hull)
    buffered = []
    for x, y in hull:
        # Vector from centroid to point
        dx = x - cx
        dy = y - cy
        dist = math.sqrt(dx * dx + dy * dy) or 1e-6
        # Scale outward
        scale = 1 + (padding_deg / dist) * 111  # ~111km per degree
        new_x = cx + dx * scale
        new_y = cy + dy * scale
        buffered.append((round(new_x, 6), round(new_y, 6)))
    return buffered


REGION_COLORS: list[str] = [
    "#ef4444", "#f97316", "#eab308", "#22c55e", "#06b6d4",
    "#3b82f6", "#6366f1", "#8b5cf6", "#ec4899", "#f43f5e",
    "#14b8a6", "#a855f7", "#0ea5e9", "#84cc16", "#d946ef",
    "#f59e0b", "#10b981", "#64748b", "#78716c", "#dc2626",
    "#7c3aed", "#0891b2", "#65a30d", "#c026d3", "#ea580c",
    "#2563eb", "#9333ea",
]


def main():
    pwd = os.getenv("MYSQL_PASSWORD", "")
    conn = pymysql.connect(
        host="127.0.0.1", port=3306, user="root",
        password=pwd, database="rus_ukr_analysis", charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT admin1,
                       COUNT(*) AS cnt,
                       SUM(COALESCE(fatalities, 0)) AS fat
                FROM conflict_events
                WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                  AND admin1 IS NOT NULL AND admin1 != ''
                GROUP BY admin1
                ORDER BY cnt DESC
            """)
            regions = cur.fetchall()

            features = []
            for idx, (admin1, cnt, fat) in enumerate(regions):
                # Get all points for this region
                cur.execute("""
                    SELECT latitude, longitude
                    FROM conflict_events
                    WHERE admin1 = %s AND latitude IS NOT NULL AND longitude IS NOT NULL
                """, (admin1,))
                rows = cur.fetchall()
                if len(rows) < 3:
                    # Create a small circle around the first point
                    lat, lng = rows[0] if rows else (48.0, 31.0)
                    points = [(lng, lat), (lng + 0.01, lat), (lng, lat + 0.01)]
                    hull = points
                else:
                    # Sample points for performance
                    sample = rows if len(rows) <= 500 else rows[::len(rows) // 500]
                    points = [(float(r[1]), float(r[0])) for r in sample]  # (lng, lat)
                    hull = convex_hull(points)

                buffered = buffer_hull(hull, padding_deg=0.05)
                # Close the polygon
                if buffered and buffered[0] != buffered[-1]:
                    buffered.append(buffered[0])

                color = REGION_COLORS[idx % len(REGION_COLORS)]
                features.append({
                    "type": "Feature",
                    "properties": {
                        "name": admin1,
                        "event_count": int(cnt),
                        "fatalities": int(fat or 0),
                        "color": color,
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [buffered],
                    },
                })

            geojson = {
                "type": "FeatureCollection",
                "features": features,
            }

            out_path = ROOT / "frontend" / "src" / "assets" / "ukraine-regions.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False)
            print(f"Generated {len(features)} regions → {out_path} "
                  f"({out_path.stat().st_size / 1024:.0f} KB)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
