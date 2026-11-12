import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "cache.json"
HISTORY_FILE = BASE_DIR / "history.json"
load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("EXCHANGE_API_KEY", "").strip()
API_URL = "https://v6.exchangerate-api.com/v6/{key}/latest/PKR"
SUPPORTED_CURRENCIES = ("PKR", "USD", "AED", "SAR")
FALLBACK_REFRESH_SECONDS = 12 * 60 * 60
memory_cache: dict[str, Any] | None = None

app = FastAPI(title="Rupee Tracker")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def normalized_rates(rates: dict[str, Any]) -> dict[str, float] | None:
    try:
        values = {currency: float(rates[currency]) for currency in SUPPORTED_CURRENCIES}
    except (KeyError, TypeError, ValueError):
        return None
    if any(value <= 0 for value in values.values()):
        return None
    return values


def cached_payload() -> dict[str, Any] | None:
    cached = memory_cache or read_json(CACHE_FILE, {})
    rates = normalized_rates(cached.get("rates", {}))
    if not rates:
        return None
    return {
        "rates": rates,
        "updated": cached.get("updated"),
        "stale": True,
    }


def save_cache(rates: dict[str, float], updated: str | None, next_update: int | None) -> None:
    global memory_cache
    memory_cache = {
        "rates": rates,
        "updated": updated,
        "next_update_unix": next_update or int(time.time()) + FALLBACK_REFRESH_SECONDS,
    }
    write_json(CACHE_FILE, memory_cache)


def save_daily_snapshot(rates: dict[str, float]) -> None:
    history = read_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []
    today = datetime.now(timezone.utc).date().isoformat()
    snapshot = {
        "date": today,
        "USD": rates["USD"],
        "AED": rates["AED"],
        "SAR": rates["SAR"],
    }
    existing = next((item for item in history if item.get("date") == today), None)
    if existing:
        existing.update(snapshot)
    else:
        history.append(snapshot)
    history = sorted(history, key=lambda item: item.get("date", ""))[-30:]
    write_json(HISTORY_FILE, history)


async def fetch_rates() -> dict[str, Any] | None:
    if not API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(API_URL.format(key=API_KEY))
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if payload.get("result") != "success":
        return None
    rates = normalized_rates(payload.get("conversion_rates", {}))
    if not rates:
        return None
    updated = payload.get("time_last_update_utc")
    next_update = payload.get("time_next_update_unix")
    save_cache(rates, updated, next_update)
    save_daily_snapshot(rates)
    return {"rates": rates, "updated": updated, "stale": False}


@app.get("/api/rates")
async def get_rates() -> dict[str, Any]:
    cached = memory_cache or read_json(CACHE_FILE, {})
    next_update = cached.get("next_update_unix", 0)
    rates = normalized_rates(cached.get("rates", {}))
    if rates and isinstance(next_update, (int, float)) and time.time() < next_update:
        return {"rates": rates, "updated": cached.get("updated"), "stale": False}

    fresh = await fetch_rates()
    if fresh:
        return fresh
    fallback = cached_payload()
    if fallback:
        return fallback
    return {
        "rates": {"PKR": 1, "USD": 1 / 280, "AED": 1 / 76, "SAR": 1 / 75},
        "updated": None,
        "stale": True,
    }


@app.get("/api/history")
async def get_history() -> list[dict[str, Any]]:
    history = read_json(HISTORY_FILE, [])
    return history if isinstance(history, list) else []


@app.get("/")
async def serve_frontend() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")
