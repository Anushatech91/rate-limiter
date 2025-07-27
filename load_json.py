import json

with open("rate_limits.json") as f:
    rate_limit_config = json.load(f)


import time
from fastapi import HTTPException

def apply_token_bucket(app_model_config: dict, request_tokens: int = 1):
    now = time.time()

    # --- Token bucket logic ---
    rate = app_model_config["rate_limit"]["refill_rate"]
    max_tokens = app_model_config["rate_limit"]["max_tokens"]
    last_refill = app_model_config["rate_limit"]["last_refill_ts"]
    available = app_model_config["rate_limit"]["available_tokens"]

    # Refill logic
    elapsed = now - last_refill
    new_tokens = min(available + int(elapsed * rate), max_tokens)

    if new_tokens < request_tokens:
        raise HTTPException(429, detail="Token bucket exhausted")

    # Update state
    app_model_config["rate_limit"]["available_tokens"] = new_tokens - request_tokens
    app_model_config["rate_limit"]["last_refill_ts"] = now

    # --- Burst logic ---
    burst = app_model_config.get("burst")
    if burst:
        burst_window = burst["burst_window"]
        burst_start = burst["burst_window_start"]
        burst_used = burst["burst_tokens_used"]
        burst_cap = burst["burst_capacity"]

        if now - burst_start > burst_window:
            # Reset burst window
            burst["burst_window_start"] = now
            burst["burst_tokens_used"] = request_tokens
        else:
            if burst_used + request_tokens > burst_cap:
                raise HTTPException(429, detail="Burst limit exceeded")
            burst["burst_tokens_used"] += request_tokens
