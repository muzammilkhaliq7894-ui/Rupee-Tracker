# Rupee Tracker

A fast, responsive PKR remittance calculator for USD, AED, and SAR. Rates are fetched server-side from ExchangeRate-API, cached for the provider's daily update window, and retained locally for offline fallback.

## Run locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Add your ExchangeRate-API key to .env
uvicorn main:app --reload
```

Open http://127.0.0.1:8000.

The API key is only read by the backend and is never sent to the browser. `cache.json` and `history.json` are generated automatically and are ignored by Git.
