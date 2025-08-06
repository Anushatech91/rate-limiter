import time
import json
import redis
from fastapi import HTTPException

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Static values can be fetched from DB/config service
STATIC_CONFIG = {
    "app_001": {
        "gpt-4.5": {
            "refill_rate": 1000,
            "max_tokens": 100000
        },
        "gpt-3.5": {
            "refill_rate": 500,
            "max_tokens": 50000
        }
    },
    "app_002": {
        "gpt-4.5": {
            "refill_rate": 2000,
            "max_tokens": 200000
        }
    }
}

def update_rate_limit(app_id, model_id, tokens_requested):
    redis_key = f"ratelimit:{app_id}:{model_id}"
    
    # 1. Load dynamic state from Redis
    state_json = r.get(redis_key)
    if not state_json:
        raise Exception("Rate limit state not found")
    
    state = json.loads(state_json)
    now = time.time()

    # 2. Get static config
    try:
        config = STATIC_CONFIG[app_id][model_id]
        refill_rate = config["refill_rate"]
        max_tokens = config["max_tokens"]
    except KeyError:
        raise Exception("Static config missing")

    # 3. Refill logic
    elapsed = now - state.get("last_refill_ts", now)
    refilled_tokens = int(elapsed * refill_rate)
    state["available_tokens"] = min(
        state.get("available_tokens", 0) + refilled_tokens,
        max_tokens
    )
    state["last_refill_ts"] = now

    # 4. Enforce token check
    if state["available_tokens"] < tokens_requested:
        raise HTTPException(429, "Rate limit exceeded")

    # 5. Deduct tokens and save
    state["available_tokens"] -= tokens_requested
    r.set(redis_key, json.dumps(state))

    return state
