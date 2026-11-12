import json
import logging
import math
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
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
logger = logging.getLogger(__name__)

app = FastAPI(title="Rupee Tracker")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as file:
            json.dump(data, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
            temporary_path = file.name
        os.replace(temporary_path, path)
    except (OSError, TypeError, ValueError):
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        raise


def normalized_rates(rates: Any) -> dict[str, float] | None:
    if not isinstance(rates, dict):
        return None
    try:
        values = {currency: float(rates[currency]) for currency in SUPPORTED_CURRENCIES}
    except (KeyError, TypeError, ValueError):
        return None
    if any(not math.isfinite(value) or value <= 0 for value in values.values()):
        return None
    return values


def valid_next_update(value: Any) -> int | float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
        return value
    return int(time.time()) + FALLBACK_REFRESH_SECONDS


def cached_payload() -> dict[str, Any] | None:
    cached = memory_cache or read_json(CACHE_FILE, {})
    if not isinstance(cached, dict):
        return None
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
        "next_update_unix": valid_next_update(next_update),
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
    history = [item for item in history if isinstance(item, dict)]
    existing = next((item for item in history if item.get("date") == today), None)
    if existing:
        existing.update(snapshot)
    else:
        history.append(snapshot)
    history = sorted(history, key=lambda item: str(item.get("date", "")))[-30:]
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
    if not isinstance(payload, dict) or payload.get("result") != "success":
        return None
    rates = normalized_rates(payload.get("conversion_rates", {}))
    if not rates:
        return None
    updated = payload.get("time_last_update_utc")
    next_update = payload.get("time_next_update_unix")
    try:
        save_cache(rates, updated, next_update)
        save_daily_snapshot(rates)
    except OSError:
        logger.warning("Unable to persist exchange-rate cache or history", exc_info=True)
    return {"rates": rates, "updated": updated, "stale": False}


@app.get("/api/rates", response_model=None)
async def get_rates() -> dict[str, Any] | JSONResponse:
    cached = memory_cache or read_json(CACHE_FILE, {})
    if not isinstance(cached, dict):
        cached = {}
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
    return JSONResponse(
        status_code=503,
        content={"rates": {}, "updated": None, "stale": True, "error": "Rates are temporarily unavailable"},
    )


@app.get("/api/history")
async def get_history() -> list[dict[str, Any]]:
    history = read_json(HISTORY_FILE, [])
    return [item for item in history if isinstance(item, dict)] if isinstance(history, list) else []


@app.get("/")
async def serve_frontend() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")
