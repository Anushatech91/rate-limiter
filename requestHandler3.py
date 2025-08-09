import time
import json
from urllib.parse import unquote
from utils.llm_proxy_service import ROUTE_PREFIX

class RequestHelper:
    def __init__(self, redis_client):
        """
        Initialize RequestHelper with Redis client
        All configurations loaded from iconfig as before
        """
        self.redis_client = redis_client
        self.app_id = None
        self.model_id = None

    def data_extraction_from_request(self, request):
        """
        Extract app_id, model_id and other data from request
        [KEEP YOUR EXISTING LOGIC - NO CHANGES]
        """
        try:
            # Extract endpoint config from request path
            endpoint_config = json.loads(get_iconfig().configurations["ENDPOINT_CONFIG"])
            env = get_iconfig().configurations["ENVIRONMENT"]
        except Exception as e:
            amt_logger.logger.error(
                f"Failed to retrieve endpoint config from iConfig: {str(e)}"
            )
            self.app_id = "endpoint_config_retrieval_failed"
            self.model_id = "500"
            return

        try:
            # Parse URL path to extract app_id and model_id
            url_path_parts = unquote(request.url.path).strip("/").split("/")
            
            # Remove route prefix if present
            if url_path_parts and url_path_parts[0] == ROUTE_PREFIX.strip("/"):
                url_path_parts = url_path_parts[1:]
            
            # Extract app_id from path (usually first segment after prefix)
            if len(url_path_parts) >= 1:
                self.app_id = url_path_parts[0]
            else:
                self.app_id = "default_app"
                
        except Exception as e:
            amt_logger.logger.error(
                f"Failed to process url. RoutePrefix: {ROUTE_PREFIX or 'None'}, request: {request.url.path}"
            )
            self.app_id = "process_route_failed" 
            self.model_id = "500"
            return

        # [REST OF YOUR EXISTING data_extraction_from_request LOGIC]
        # ... keeping all your existing validation and extraction logic ...

    def get_unique_string(self, request):
        """
        Generate unique string for app_id + model_id combination
        [KEEP YOUR EXISTING LOGIC]
        """
        self.data_extraction_from_request(request)
        return f"{self.app_id}:{self.model_id}"

    def find_model_config(self):
        """
        Find model configuration for current app_id + model_id
        [KEEP YOUR EXISTING LOGIC]
        """
        dynamic_ratelimit_config = json.loads(get_iconfig().configurations["RATE_LIMITS_DYNAMIC_INIT"])
        
        for app in dynamic_ratelimit_config["apps"]:
            if app["application-id"] == self.app_id:
                for model in app["models"]:
                    if model["model_id"] == self.model_id:
                        return model
        return None

    def get_rate_limiting_string(self):
        """
        Get rate limiting configuration string
        [KEEP YOUR EXISTING LOGIC]
        """
        dynamic_ratelimit_config = json.loads(get_iconfig().configurations["RATE_LIMITS_DYNAMIC_INIT"])
        
        for app in dynamic_ratelimit_config["apps"]:
            if app["application-id"] == self.app_id:
                for model in app["models"]:
                    if model["model_id"] == self.model_id:
                        rpm = model["rate_limit"]["rpm"]
                        return f"{rpm}/minute"
        return "Rate limit not configured"

    def _get_redis_state(self):
        """
        NEW: Get current token bucket state from Redis
        Similar to RedisTokenBucketAppModel._get_state()
        """
        redis_key = f"ratelimit:{self.app_id}:{self.model_id}"
        
        # Try to get existing state
        state_data = self.redis_client.get(redis_key)
        
        if state_data:
            state = json.loads(state_data)
            return {
                "available_tokens": float(state.get("available_tokens", 0)),
                "last_refill_ts": float(state.get("last_refill_ts", time.time())),
                "burst_tokens_used": float(state.get("burst_tokens_used", 0)),
                "burst_window_start": float(state.get("burst_window_start", time.time()))
            }
        else:
            # Initialize with default values from config
            model_config = self.find_model_config()
            if model_config:
                max_tokens = model_config["rate_limit"].get("available_tokens", 100)
                return {
                    "available_tokens": float(max_tokens),
                    "last_refill_ts": float(time.time()),
                    "burst_tokens_used": 0.0,
                    "burst_window_start": float(time.time())
                }
            else:
                return {
                    "available_tokens": 100.0,
                    "last_refill_ts": float(time.time()),
                    "burst_tokens_used": 0.0,
                    "burst_window_start": float(time.time())
                }

    def _save_redis_state(self, state):
        """
        NEW: Save token bucket state to Redis
        Similar to RedisTokenBucketAppModel._save_state()
        """
        redis_key = f"ratelimit:{self.app_id}:{self.model_id}"
        self.redis_client.set(redis_key, json.dumps(state))

    def allow_request(self, tokens_requested):
        """
        NEW: Enhanced token bucket logic from RedisTokenBucketAppModel
        This replaces/enhances your apply_rate_limit method
        """
        model_config = self.find_model_config()
        if not model_config:
            raise HTTPException(404, "Config not found")

        # Get configuration values
        rate_limit = model_config["rate_limit"]
        burst_config = model_config.get("burst", {})
        
        max_tokens = rate_limit.get("available_tokens", 100)
        refill_rate = rate_limit.get("rpm", 60) / 60.0  # Convert RPM to tokens per second
        burst_capacity = burst_config.get("capacity", 0)
        burst_window = burst_config.get("window", 60)

        now = time.time()
        state = self._get_redis_state()

        # Refill logic (IMPROVED from RedisTokenBucketAppModel)
        elapsed = now - state["last_refill_ts"]
        refill = elapsed * refill_rate
        state["available_tokens"] = min(max_tokens, state["available_tokens"] + refill)
        state["last_refill_ts"] = now

        # Burst window reset (NEW from RedisTokenBucketAppModel)
        if now - state["burst_window_start"] > burst_window:
            state["burst_window_start"] = now
            state["burst_tokens_used"] = 0

        # Decision logic (ENHANCED from RedisTokenBucketAppModel)
        if tokens_requested <= state["available_tokens"]:
            # Allow via base quota
            state["available_tokens"] -= tokens_requested
            self._save_redis_state(state)
            return True, "Allowed via base quota"
        elif burst_capacity > 0 and state["burst_tokens_used"] + tokens_requested <= burst_capacity:
            # Allow via burst quota
            state["burst_tokens_used"] += tokens_requested
            self._save_redis_state(state)
            return True, "Allowed via burst quota"
        else:
            # Deny request
            self._save_redis_state(state)
            return False, "Rate limit exceeded"

    def apply_rate_limit(self, tokens_requested):
        """
        UPDATED: Your existing method now uses the enhanced allow_request logic
        """
        return self.allow_request(tokens_requested)

    def init_redis_dynamic_state(self):
        """
        ENHANCED: Initialize Redis state for all app_id + model_id combinations
        Uses your existing config structure
        """
        try:
            dynamic_ratelimit_config = json.loads(get_iconfig().configurations["RATE_LIMITS_DYNAMIC_INIT"])
        except Exception as e:
            amt_logger.logger.error(f"Failed to load dynamic rate limit config: {str(e)}")
            return

        for app in dynamic_ratelimit_config["apps"]:
            app_id = app["application-id"]
            for model in app["models"]:
                model_id = model["model_id"] 
                burst = model.get("burst", {})
                rate = model.get("rate_limit", {})
                
                # Create initial state for this app_id + model_id combination
                initial_state = {
                    "available_tokens": rate.get("available_tokens", 100),
                    "last_refill_ts": time.time(),
                    "burst_tokens_used": 0,
                    "burst_window_start": time.time()
                }
                
                # Store in Redis with app_id:model_id key
                redis_key = f"ratelimit:{app_id}:{model_id}"
                self.redis_client.set(redis_key, json.dumps(initial_state))
                print(f"Initialized Redis state: {redis_key} -> {initial_state}")

    def update_dynamic_token_state(self, tokens_requested):
        """
        SIMPLIFIED: This is now handled by allow_request method
        Keeping for backward compatibility
        """
        allowed, message = self.allow_request(tokens_requested)
        return allowed, message

# HOW TO USE THIS CLASS:

# 1. Initialize once (usually in your main application startup)
redis_client = redis.Redis(host='localhost', port=6379, db=0)  # Your Redis client
request_helper = RequestHelper(redis_client)

# 2. Initialize Redis state on startup (call once)
request_helper.init_redis_dynamic_state()

# 3. For each incoming request, use like this:
def handle_request(request, tokens_needed=1):
    """
    Example usage in your request handler
    """
    # Extract app_id and model_id from request
    unique_key = request_helper.get_unique_string(request)
    
    # Check if request is allowed
    allowed, message = request_helper.allow_request(tokens_needed)
    
    if allowed:
        # Process the request
        return process_llm_request(request)
    else:
        # Return rate limit error
        return HTTPException(429, f"Rate limit exceeded: {message}")

# 4. In your FastAPI/Flask route:
@app.post("/api/v1/chat/completions")
async def chat_completion(request: Request):
    # Estimate tokens needed (you might have your own logic)
    tokens_needed = estimate_tokens_from_request(request)
    
    return handle_request(request, tokens_needed)
