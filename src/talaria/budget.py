"""Per-user local budget policy over one assigned Hermes profile."""

from __future__ import annotations

import datetime as dt
import math

from .hermes import APIError

MICRO_IDR = 1_000_000
MAX_MONTHLY_IDR = 10**12


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _timestamp(value):
    if type(value) in (int, float) and math.isfinite(value):
        return dt.datetime.fromtimestamp(value, dt.UTC)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                dt.UTC
            )
        except ValueError:
            return None
    return None


def windows(now=None):
    now = now or dt.datetime.now(dt.UTC)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    week = (now - dt.timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return week, month


def _session_micro_idr(session):
    for key in ("actual_cost_micro_idr", "estimated_cost_micro_idr", "cost_micro_idr"):
        value = _number(session.get(key))
        if value is not None:
            return int(value)
    return None


async def _session_cost(client, session):
    direct = _session_micro_idr(session)
    if direct is not None:
        return direct
    model = session.get("model")
    if not isinstance(model, str) or not model.strip():
        return None
    fields = {"model": model.strip()}
    for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
        value = session.get(key, 0)
        if type(value) is not int or value < 0:
            return None
        fields[key] = value
    try:
        result = await client.request("POST", "/kenari/v1/estimate", json=fields)
    except APIError:
        return None
    value = result.get("estimated_micro_idr") if isinstance(result, dict) else None
    return int(value) if type(value) is int and value >= 0 else None


async def profile_usage(client, now=None):
    """Sum known Kenari cost for every session in this Hermes profile."""
    week_start, month_start = windows(now)
    totals = {"weekly_micro_idr": 0, "monthly_micro_idr": 0, "unknown_sessions": 0}
    offset = 0
    while offset < 10_000:
        try:
            page = await client.request(
                "GET",
                "/api/sessions",
                params={"limit": 100, "offset": offset, "include_children": "false"},
            )
        except APIError:
            totals["unknown_sessions"] += 1
            break
        rows = page.get("data", []) if isinstance(page, dict) else []
        if not isinstance(rows, list):
            break
        for session in rows:
            if not isinstance(session, dict):
                continue
            started = _timestamp(session.get("started_at") or session.get("created_at"))
            if started is None or started < month_start:
                continue
            cost = await _session_cost(client, session)
            if cost is None:
                totals["unknown_sessions"] += 1
                continue
            totals["monthly_micro_idr"] += cost
            if started >= week_start:
                totals["weekly_micro_idr"] += cost
        if not page.get("has_more") or not rows:
            break
        offset += len(rows)
    return totals


def snapshot(user, usage):
    monthly = user.get("monthly_budget_micro_idr")
    if type(monthly) is not int or monthly <= 0:
        return {
            "configured": False,
            "monthly_percent": None,
            "weekly_percent": None,
            "blocked": False,
            "unknown_sessions": usage["unknown_sessions"],
        }
    weekly = monthly // 4
    month_percent = min(100, usage["monthly_micro_idr"] * 100 / monthly)
    week_percent = min(100, usage["weekly_micro_idr"] * 100 / weekly) if weekly else 100
    return {
        "configured": True,
        "monthly_percent": round(month_percent, 2),
        "weekly_percent": round(week_percent, 2),
        "blocked": usage["monthly_micro_idr"] >= monthly or usage["weekly_micro_idr"] >= weekly,
        "unknown_sessions": usage["unknown_sessions"],
    }


def parse_monthly_budget(value):
    if type(value) is not int or value < 0 or value > MAX_MONTHLY_IDR:
        raise ValueError("monthly_budget_idr")
    return value * MICRO_IDR
