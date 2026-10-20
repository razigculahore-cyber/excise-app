"""Estimates a user has saved. Every query is scoped to the owner's user id."""
import json
import math

from flask import current_app

from ..db import get_db

INPUT_KEYS = ("txn", "vehicle", "motorCycleSub", "commercialSub", "cc", "kw", "ladenWeight",
              "invoiceValue", "advanceTax", "taxStatus", "owner", "cvt", "hpa", "invoiceDate", "regDate")
MAX_LINES = 40


class InvalidEstimate(ValueError):
    pass


class TooManyEstimates(Exception):
    pass


def clean(payload) -> dict:
    """Validate an estimate sent by the browser and keep only the fields we store."""
    if not isinstance(payload, dict):
        raise InvalidEstimate("Expected a JSON object.")

    title = str(payload.get("title") or "").strip()[:120]
    summary = str(payload.get("summary") or "").strip()[:200]
    if not title:
        title = summary or "Untitled estimate"

    total = payload.get("total")
    if isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total):
        raise InvalidEstimate("Total must be a number.")

    raw_inputs = payload.get("inputs")
    if not isinstance(raw_inputs, dict):
        raise InvalidEstimate("Inputs are missing.")
    inputs = {k: str(raw_inputs.get(k, ""))[:40] for k in INPUT_KEYS}

    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines or len(raw_lines) > MAX_LINES:
        raise InvalidEstimate("Breakdown lines are missing.")
    lines = []
    for line in raw_lines:
        if not isinstance(line, dict):
            raise InvalidEstimate("Each breakdown line must be an object.")
        amount = line.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
            raise InvalidEstimate("Each breakdown amount must be a number.")
        lines.append({"label": str(line.get("label") or "")[:80], "amount": amount})

    return {"title": title, "summary": summary, "total": float(total), "inputs": inputs, "lines": lines}


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": row["summary"],
        "total": row["total"],
        "inputs": json.loads(row["inputs"]),
        "lines": json.loads(row["lines"]),
        "created_at": row["created_at"],
    }


def count_for(user_id: int) -> int:
    return get_db().execute(
        "SELECT COUNT(*) AS n FROM estimates WHERE user_id = %s", (user_id,)).fetchone()["n"]


def list_for(user_id: int, limit: int | None = None) -> list[dict]:
    sql = "SELECT * FROM estimates WHERE user_id = %s ORDER BY id DESC"
    params: tuple = (user_id,)
    if limit:
        sql += " LIMIT %s"
        params += (limit,)
    return [_row_to_dict(r) for r in get_db().execute(sql, params).fetchall()]


def get_for(user_id: int, estimate_id: int) -> dict | None:
    row = get_db().execute(
        "SELECT * FROM estimates WHERE id = %s AND user_id = %s", (estimate_id, user_id)).fetchone()
    return _row_to_dict(row) if row else None


def create(user_id: int, data: dict) -> int:
    if count_for(user_id) >= current_app.config["MAX_SAVED_ESTIMATES"]:
        raise TooManyEstimates()
    row = get_db().execute(
        "INSERT INTO estimates (user_id, title, summary, total, inputs, lines)"
        " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (user_id, data["title"], data["summary"], data["total"],
         json.dumps(data["inputs"]), json.dumps(data["lines"]))).fetchone()
    return row["id"]


def delete_for(user_id: int, estimate_id: int) -> bool:
    cur = get_db().execute("DELETE FROM estimates WHERE id = %s AND user_id = %s", (estimate_id, user_id))
    return cur.rowcount > 0
