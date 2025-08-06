# init_redis_dynamic_state.py

import redis
import json

# Connect to Redis
r = redis.Redis(host="localhost", port=6379, decode_responses=True)

# Load your config from file or inline
with open("your_config.json") as f:
    config = json.load(f)

for app in config["apps"]:
    app_id = app["app_id"]
    for model in app["models"]:
        model_id = model["model_id"]
        rate = model.get("rate_limit", {})
        burst = model.get("burst", {})

        dynamic_state = {
            "available_tokens": rate.get("available_tokens"),
            "last_refill_ts": rate.get("last_refill_ts"),
            "burst_tokens_used": burst.get("burst_tokens_used"),
            "burst_window_start": burst.get("burst_window_start")
        }

        redis_key = f"ratelimit:{app_id}:{model_id}"
        r.set(redis_key, json.dumps(dynamic_state))
        print(f"✅ Stored: {redis_key}")
