"""Exact token-usage persistence and aggregation for wynxq.storage.

This module is Qt-free and works through the stable Store facade's private
SQLite connection/lock. Time bucketing stays centralized here so UI and
workspace layers consume one consistent accounting policy.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import time


def record_token_usage(self, conversation_id: str, model: str, metrics: dict,
                       created_at: float | None = None) -> bool:
    """Persist one completed model run's exact Ollama token accounting."""
    output = max(0, int(metrics.get("tokens", 0) or 0))
    prompt = max(0, int(metrics.get("prompt_tokens", 0) or 0))
    cached = max(0, int(metrics.get("cached_prompt_tokens", 0) or 0))
    if not output and not prompt:
        return False
    duration = max(0.0, float(metrics.get("total_ms", 0.0) or 0.0))
    rate = max(0.0, float(metrics.get("tokens_per_second", 0.0) or 0.0))
    with self._lock, self._db:
        self._db.execute(
            "INSERT INTO token_usage "
            "(created_at,conversation_id,model,output_tokens,prompt_tokens,"
            "cached_prompt_tokens,duration_ms,tokens_per_second) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                time.time() if created_at is None else float(created_at),
                str(conversation_id or ""),
                str(model or ""),
                output,
                prompt,
                cached,
                duration,
                rate,
            ),
        )
    return True


def _usage_boundaries(now: float) -> dict[str, float | None]:
    local = datetime.fromtimestamp(float(now))
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    return {
        "today": today.timestamp(),
        "week": week.timestamp(),
        "month": month.timestamp(),
        "allTime": None,
    }


def token_usage_summary(self, now: float | None = None) -> dict[str, dict]:
    """Aggregate exact usage in local-day, Monday-week, month and lifetime buckets."""
    now = time.time() if now is None else float(now)
    summary: dict[str, dict] = {}
    with self._lock:
        for key, start in self._usage_boundaries(now).items():
            if start is None:
                where, params = "WHERE created_at <= ?", (now,)
            else:
                where, params = (
                    "WHERE created_at >= ? AND created_at <= ?",
                    (start, now),
                )
            row = self._db.execute(
                "SELECT COALESCE(SUM(output_tokens),0) output_tokens, "
                "COALESCE(SUM(prompt_tokens),0) prompt_tokens, "
                "COALESCE(SUM(cached_prompt_tokens),0) cached_prompt_tokens, "
                "COUNT(*) runs, "
                "COALESCE(SUM(CASE WHEN tokens_per_second > 0 "
                "THEN tokens_per_second * output_tokens ELSE 0 END),0) rate_weighted, "
                "COALESCE(SUM(CASE WHEN tokens_per_second > 0 "
                "THEN output_tokens ELSE 0 END),0) rate_tokens "
                f"FROM token_usage {where}",
                params,
            ).fetchone()
            output = int(row["output_tokens"] or 0)
            prompt = int(row["prompt_tokens"] or 0)
            rate_tokens = int(row["rate_tokens"] or 0)
            average_rate = (
                float(row["rate_weighted"] or 0.0) / rate_tokens
                if rate_tokens else 0.0
            )
            summary[key] = {
                "tokens": output + prompt,
                "outputTokens": output,
                "promptTokens": prompt,
                "cachedTokens": int(row["cached_prompt_tokens"] or 0),
                "runs": int(row["runs"] or 0),
                "averageRate": round(average_rate, 1),
            }
    return summary


def token_usage_daily(self, days: int = 7, now: float | None = None) -> list[dict]:
    """Exact local-day usage for a compact trend view, including empty days."""
    days = max(2, min(int(days or 7), 366))
    now = time.time() if now is None else float(now)
    local_now = datetime.fromtimestamp(now)
    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    starts = [
        today - timedelta(days=offset)
        for offset in range(days - 1, -1, -1)
    ]
    first = starts[0].timestamp()
    buckets = {
        start.date(): {
            "date": start.date().isoformat(),
            "label": start.strftime("%a"),
            "tokens": 0,
            "outputTokens": 0,
            "promptTokens": 0,
            "runs": 0,
            "rateWeighted": 0.0,
            "rateTokens": 0,
        }
        for start in starts
    }
    with self._lock:
        rows = self._db.execute(
            "SELECT created_at, output_tokens, prompt_tokens, tokens_per_second "
            "FROM token_usage WHERE created_at >= ? AND created_at <= ? ORDER BY created_at",
            (first, now),
        ).fetchall()
    for row in rows:
        day = datetime.fromtimestamp(float(row["created_at"])).date()
        bucket = buckets.get(day)
        if bucket is None:
            continue
        output = int(row["output_tokens"] or 0)
        prompt = int(row["prompt_tokens"] or 0)
        rate = max(0.0, float(row["tokens_per_second"] or 0.0))
        bucket["outputTokens"] += output
        bucket["promptTokens"] += prompt
        bucket["tokens"] += output + prompt
        bucket["runs"] += 1
        if output and rate:
            bucket["rateWeighted"] += output * rate
            bucket["rateTokens"] += output
    result = []
    for start in starts:
        bucket = buckets[start.date()]
        weighted = float(bucket.pop("rateWeighted"))
        rate_tokens = int(bucket.pop("rateTokens"))
        bucket["averageRate"] = (
            round(weighted / rate_tokens, 1) if rate_tokens else 0.0
        )
        result.append(bucket)
    return result


def token_usage_overview(self, now: float | None = None) -> dict:
    """Lifetime activity statistics from exact runs; calendar days use local time."""
    now = time.time() if now is None else float(now)
    today = datetime.fromtimestamp(now).date()
    with self._lock:
        rows = self._db.execute(
            "SELECT created_at, conversation_id, output_tokens + prompt_tokens tokens, "
            "duration_ms FROM token_usage WHERE created_at <= ? ORDER BY created_at", (now,)
        ).fetchall()
    daily = {}
    chats = {}
    for row in rows:
        day = datetime.fromtimestamp(row["created_at"]).date()
        daily[day] = daily.get(day, 0) + row["tokens"]
        if row["conversation_id"]:
            chats[row["conversation_id"]] = chats.get(row["conversation_id"], 0) + row["duration_ms"]
    longest = streak = 0
    previous = None
    for day in sorted(daily):
        streak = streak + 1 if previous and day == previous + timedelta(days=1) else 1
        longest = max(longest, streak)
        previous = day
    current = 0
    cursor = today if today in daily else today - timedelta(days=1)
    while cursor in daily:
        current += 1
        cursor -= timedelta(days=1)
    return {
        "peakDayTokens": max(daily.values(), default=0),
        "longestGenerationMs": max(chats.values(), default=0),
        "currentStreak": current, "longestStreak": longest,
        "activeDays": len(daily), "totalChats": len(chats),
        "year": token_usage_daily(self, 366, now),
    }


def token_usage_models(self, days: int = 30, now: float | None = None,
                       limit: int = 6) -> list[dict]:
    """Top models by exact input + output usage over a recent local window."""
    days = max(1, min(int(days or 30), 3650))
    limit = max(1, min(int(limit or 6), 20))
    now = time.time() if now is None else float(now)
    start = now - days * 86400
    with self._lock:
        rows = self._db.execute(
            "SELECT model, SUM(output_tokens) output_tokens, "
            "SUM(prompt_tokens) prompt_tokens, COUNT(*) runs, "
            "SUM(CASE WHEN tokens_per_second > 0 "
            "THEN tokens_per_second * output_tokens ELSE 0 END) rate_weighted, "
            "SUM(CASE WHEN tokens_per_second > 0 "
            "THEN output_tokens ELSE 0 END) rate_tokens "
            "FROM token_usage WHERE created_at >= ? AND created_at <= ? "
            "GROUP BY model ORDER BY "
            "(SUM(output_tokens) + SUM(prompt_tokens)) DESC LIMIT ?",
            (start, now, limit),
        ).fetchall()
    result = []
    for row in rows:
        output = int(row["output_tokens"] or 0)
        prompt = int(row["prompt_tokens"] or 0)
        rate_tokens = int(row["rate_tokens"] or 0)
        result.append({
            "name": str(row["model"] or "Unknown model"),
            "tokens": output + prompt,
            "outputTokens": output,
            "promptTokens": prompt,
            "runs": int(row["runs"] or 0),
            "averageRate": (
                round(float(row["rate_weighted"] or 0.0) / rate_tokens, 1)
                if rate_tokens else 0.0
            ),
        })
    return result


def conversation_token_usage(self, conversation_id: str) -> dict[str, int]:
    """Return exact recorded usage for one conversation without period scans."""
    conversation_id = str(conversation_id or "")
    if not conversation_id:
        return {
            "tokens": 0,
            "outputTokens": 0,
            "promptTokens": 0,
            "cachedTokens": 0,
            "runs": 0,
        }
    with self._lock:
        row = self._db.execute(
            "SELECT COALESCE(SUM(output_tokens),0) output_tokens, "
            "COALESCE(SUM(prompt_tokens),0) prompt_tokens, "
            "COALESCE(SUM(cached_prompt_tokens),0) cached_prompt_tokens, "
            "COUNT(*) runs FROM token_usage WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
    output = int(row["output_tokens"] or 0)
    prompt = int(row["prompt_tokens"] or 0)
    return {
        "tokens": output + prompt,
        "outputTokens": output,
        "promptTokens": prompt,
        "cachedTokens": int(row["cached_prompt_tokens"] or 0),
        "runs": int(row["runs"] or 0),
    }


__all__ = ['record_token_usage', 'token_usage_summary', 'token_usage_overview', 'token_usage_daily', 'token_usage_models', 'conversation_token_usage']
