from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: float
    y: float


def point_in_polygon(point: Point, polygon: list[list[float]]) -> bool:
    """Ray-casting algorithm for normalized polygon coordinates."""
    if len(polygon) < 3:
        return False

    inside = False
    x, y = point.x, point.y
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def zones_at_point(
    x: float,
    y: float,
    zone_definitions: list[dict],
) -> list[dict]:
    point = Point(x, y)
    matches = []
    for zone in zone_definitions:
        if point_in_polygon(point, zone["polygon"]):
            matches.append(zone)
    return matches


def crossed_entry_line(
    prev_y: float,
    curr_y: float,
    line_position: float,
    inbound_direction: str,
) -> str | None:
    """Return ENTRY or EXIT when centroid crosses the entry threshold."""
    if inbound_direction == "down":
        if prev_y < line_position <= curr_y:
            return "ENTRY"
        if prev_y >= line_position > curr_y:
            return "EXIT"
    elif inbound_direction == "up":
        if prev_y > line_position >= curr_y:
            return "ENTRY"
        if prev_y <= line_position < curr_y:
            return "EXIT"
    return None


def crossed_entry_line_x(
    prev_x: float,
    curr_x: float,
    line_position: float,
    inbound_direction: str,
) -> str | None:
    if inbound_direction == "right":
        if prev_x < line_position <= curr_x:
            return "ENTRY"
        if prev_x >= line_position > curr_x:
            return "EXIT"
    elif inbound_direction == "left":
        if prev_x > line_position >= curr_x:
            return "ENTRY"
        if prev_x <= line_position < curr_x:
            return "EXIT"
    return None
