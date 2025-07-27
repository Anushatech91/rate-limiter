from fastapi import FastAPI, HTTPException
import json
import time
from filelock import FileLock

app = FastAPI()

CONFIG_FILE = "rate_limits.json"
LOCK_FILE = CONFIG_FILE + ".lock"

# 🔁 Load once on startup
with open(CONFIG_FILE) as f:
    rate_limiting = json.load(f)

# 🔍 Find model config
def find_model_config(app_id, model_id):
    for app in rate_limiting["apps"]:
        if app["app_id"] == app_id:
            for model in app["models"]:
                if model["model_id"] == model_id:
                    return model
    return None

# 🧪 Rate limiter logic
def apply_rate_limit(app_id, model_id, tokens_requested=1):
    now = time.time()
    model_config = find_model_config(app_id, model_id)
    if not model_config:
        raise HTTPException(404, "Config not found")

    rate_limit = model_config["rate_limit"]
    burst = model_config.get("burst", {})

    # ⛽ Token Bucket
    elapsed = now - rate_limit["last_refill_ts"]
    refilled_tokens = int(elapsed * rate_limit["refill_rate"])
    new_available = min(rate_limit["available_tokens"] + refilled_tokens, rate_limit["max_tokens"])

    if new_available < tokens_requested:
        raise HTTPException(429, "Token bucket limit exceeded")

    # 💥 Burst Check
    if burst:
        if now - burst["burst_window_start"] > burst["burst_window"]:
            burst["burst_window_start"] = now
            burst["burst_tokens_used"] = tokens_requested
        else:
            if burst["burst_tokens_used"] + tokens_requested > burst["burst_capacity"]:
                raise HTTPException(429, "Burst limit exceeded")
            burst["burst_tokens_used"] += tokens_requested

    # ✅ Update in-memory state
    rate_limit["available_tokens"] = new_available - tokens_requested
    rate_limit["last_refill_ts"] = now

    # 💾 Write back to file with lock
    with FileLock(LOCK_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(rate_limiting, f, indent=2)

# ✅ API Route
@app.get("/run-model")
def run_model(app_id: str, model_id: str, tokens: int = 1):
    apply_rate_limit(app_id, model_id, tokens)
    return {
        "status": "allowed",
        "app_id": app_id,
        "model_id": model_id,
        "tokens_used": tokens
    }
