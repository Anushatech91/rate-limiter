import time
import json
import redis

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

def update_rate_limit(app_id, model_id, tokens_requested):
    redis_key = f"ratelimit:{app_id}:{model_id}"
    
    # Load dynamic state from Redis
    state_json = r.get(redis_key)
    if not state_json:
        raise Exception("Rate limit state not found")
    
    state = json.loads(state_json)
    now = time.time()

    # Apply logic (example: naive token deduction)
    if state["available_tokens"] < tokens_requested:
        raise Exception("Rate limit exceeded")
    
    state["available_tokens"] -= tokens_requested
    state["last_refill_ts"] = now

    # Save updated state back to Redis
    r.set(redis_key, json.dumps(state))

    return state
