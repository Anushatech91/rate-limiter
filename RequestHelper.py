import time
import json
import re
from urllib.parse import unquote
from utils.llm_proxy_service import ROUTE_PREFIX

class RequestHelper:
    def __init__(self):
        """
        Initialize RequestHelper - app_id, model_id and rate limits will be loaded dynamically from config
        """
        self.app_id = None
        self.model_id = None
        self.max_tokens = None
        self.refill_rate = None
        self.burst_capacity = None
        self.burst_window = None
        self.rate_limits_config = None

    def _load_rate_limit_config(self):
        """
        Load rate limiting configuration from iConfig
        """
        try:
            self.rate_limits_config = json.loads(get_iconfig().configurations["RATE_LIMITS_DYNAMIC_INIT"])
        except Exception as e:
            amt_logger.logger.error(f"Failed to load rate limits config: {str(e)}")
            self.rate_limits_config = {"apps": []}

    def _get_app_model_config(self):
        """
        Get configuration for current app_id and model_id combination
        Returns the rate limiting parameters
        """
        if not self.rate_limits_config:
            self._load_rate_limit_config()
            
        for app in self.rate_limits_config["apps"]:
            if app["application-id"] == self.app_id:
                for model in app["models"]:
                    if model["model_id"] == self.model_id:
                        # Extract rate limiting parameters from config
                        rate_limit = model.get("rate_limit", {})
                        burst = model.get("burst", {})
                        
                        self.max_tokens = rate_limit.get("max_tokens", 1000)
                        self.refill_rate = rate_limit.get("refill_rate", 10)
                        self.burst_capacity = burst.get("capacity", 100)
                        self.burst_window = burst.get("window", 60)
                        
                        return model
        
        # Default values if not found in config
        self.max_tokens = 1000
        self.refill_rate = 10
        self.burst_capacity = 100
        self.burst_window = 60
        return None

    def _get_state(self):
        """
        Get current state for app_id + model_id combination
        """
        # IMPROVED: Use app_id:model_id key structure (not user-level anymore)
        key = f"ratelimit:{self.app_id}:{self.model_id}"
        
        try:
            state_data = redis_client.hmget(key, [
                "available_tokens", "last_refill_ts", 
                "burst_tokens_used", "burst_window_start"
            ])
            
            if not any(state_data):
                # Initialize with defaults from config
                return {
                    "available_tokens": float(self.max_tokens),
                    "last_refill_ts": float(time.time()),
                    "burst_tokens_used": float(0),
                    "burst_window_start": float(time.time())
                }
            
            return {
                "available_tokens": float(state_data[0] or self.max_tokens),
                "last_refill_ts": float(state_data[1] or time.time()),
                "burst_tokens_used": float(state_data[2] or 0),
                "burst_window_start": float(state_data[3] or time.time())
            }
        except Exception as e:
            amt_logger.logger.error(f"Failed to get state for {key}: {str(e)}")
            # Return default state
            return {
                "available_tokens": float(self.max_tokens or 1000),
                "last_refill_ts": float(time.time()),
                "burst_tokens_used": float(0),
                "burst_window_start": float(time.time())
            }

    def _save_state(self, state):
        """
        Save state for app_id + model_id combination
        """
        key = f"ratelimit:{self.app_id}:{self.model_id}"
        try:
            redis_client.hset(key, {
                "available_tokens": state["available_tokens"],
                "last_refill_ts": state["last_refill_ts"], 
                "burst_tokens_used": state["burst_tokens_used"],
                "burst_window_start": state["burst_window_start"]
            })
        except Exception as e:
            amt_logger.logger.error(f"Failed to save state for {key}: {str(e)}")

    def allow_request(self, request, requested_tokens):
        """
        Check if request is allowed for app_id + model_id combination
        IMPROVED: Dynamically loads config based on request
        """
        # First extract app_id and model_id from request
        self.data_extraction_from_request(request)
        
        # Then load the rate limiting config for this app_id + model_id
        self._get_app_model_config()
        
        # Now apply the token bucket algorithm
        now = time.time()
        state = self._get_state()

        # IMPROVED: More robust refill logic using config values
        elapsed = now - state["last_refill_ts"]
        refill = elapsed * self.refill_rate
        state["available_tokens"] = min(self.max_tokens, state["available_tokens"] + refill)
        state["last_refill_ts"] = now

        # IMPROVED: Better burst window reset logic using config values
        if now - state["burst_window_start"] > self.burst_window:
            state["burst_window_start"] = now
            state["burst_tokens_used"] = 0

        # IMPROVED: Decision logic with proper state updates
        if requested_tokens <= state["available_tokens"]:
            state["available_tokens"] -= requested_tokens
            self._save_state(state)
            return True, "Allowed via base quota"
        elif state["burst_tokens_used"] + requested_tokens <= self.burst_capacity:
            state["burst_tokens_used"] += requested_tokens
            self._save_state(state)
            return True, "Allowed via burst quota"
        else:
            self._save_state(state)
            return False, "Rate limit exceeded"

    def data_extraction_from_request(self, request):
        """
        Extract app_id and model_id from request - KEEPING YOUR ORIGINAL LOGIC
        """
        try:
            # YOUR ORIGINAL: Load your config from iConfig
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
            # YOUR ORIGINAL: URL parsing logic to extract app_id
            url_path_parts = unquote(request.url.path).strip("/").split("/")
            
            if url_path_parts and url_path_parts[0] == ROUTE_PREFIX.strip("/"):
                url_path_parts = url_path_parts[1:]
            
            if len(url_path_parts) >= 1:
                self.app_id = url_path_parts[0]  # This is your app_id extraction
            else:
                self.app_id = "default_app"
                
        except Exception as e:
            amt_logger.logger.error(
                f"Failed to process url. RoutePrefix: {ROUTE_PREFIX or 'None'}, request: {request.url.path}"
            )
            self.app_id = "process_route_failed" 
            self.model_id = "500"
            return

        # YOUR ORIGINAL: Validate endpoint version
        try:
            if request.query_params.get("api-version"):
                endpoint_version = request.query_params.get("api-version")
                endpoint_version_provided = True
            else:
                endpoint_version = "v1"
                
            if endpoint_version_provided:
                request_ai_service = url_path_parts[1] if len(url_path_parts) > 1 else None
            else:
                request_ai_service = url_path_parts[0] if len(url_path_parts) > 0 else None
                
        except Exception:
            amt_logger.logger.debug(
                f"Could not parse endpoint version from request path. Request: {request.url.path}"
            )
            self.app_id = "could_not_parse_endpoint_version"
            self.model_id = "500"
            return

        # YOUR ORIGINAL: Validate AI service for the provided cloud provider
        try:
            request_cloud_provider = url_path_parts[0] if len(url_path_parts) > 0 else None
            cloud_provider = endpoint_config[request_cloud_provider]
        except KeyError:
            amt_logger.logger.debug(
                f"Cloud provider {request_cloud_provider} not found in {env} config."
            )
            self.app_id = "cloud_provider_not_found"
            self.model_id = "500" 
            return

        # YOUR ORIGINAL: Validate and extract model information
        try:
            ai_service = cloud_provider[request_ai_service][endpoint_version]
        except KeyError:
            amt_logger.logger.debug(
                f"AI service {request_ai_service} not found for {request_cloud_provider} in {env} config."
            )
            self.app_id = "ai_service_not_found"
            self.model_id = "500"
            return

        # YOUR ORIGINAL: Extract model_id from request body or URL
        try:
            if hasattr(request, 'body') and request.body and len(request.body) == 0:
                self.app_id = "no_path_parts_identified"
                self.model_id = "500"
                return

            request_cloud_provider = url_path_parts[0]
            try:
                cloud_provider = endpoint_config[request_cloud_provider]
            except KeyError:
                amt_logger.logger.debug(
                    f"Cloud provider {request_cloud_provider} not found in {env} config."
                )
                self.app_id = "cloud_provider_not_found" 
                self.model_id = "500"
                return

            # YOUR ORIGINAL: Find model configuration
            url_path = request.url.path
            segments = re.split(r'[/\?]', url_path)
            
            # Assuming model_blacklist is defined somewhere in your code
            model_blacklist = ["v1", "completions", "chat", "embeddings"]  # Add your blacklist
            matches = [s for s in segments if s not in model_blacklist]

            if not matches:
                amt_logger.logger.error(
                    f"Could not identify suitable model for {cloud_provider} + {ai_service} in {env} from {url_path}"
                )
                self.model_id = "could_not_identify"
                return
                
            if len(matches) == 1:
                self.model_id = matches[0]  # This is your model_id extraction
                return
                
            # YOUR ORIGINAL: Pick the longest model name -> most specific
            max_len = max(len(m) for m in matches)
            longest = [m for m in matches if len(m) == max_len]
            
            if len(longest) == 1:
                self.model_id = longest[0]
                return
                
            # YOUR ORIGINAL: Tie-breaker logic
            best_model = max(longest, key=lambda m: url_path.rfind(m))
            self.model_id = best_model
            return

        except Exception as e:
            amt_logger.logger.error(f"Exception occurred during accessing models from AI Service: {str(e)}")
            self.app_id = "ai_service_not_found"
            self.model_id = "500"
            return

    def get_unique_string(self, request):
        """
        Generate unique string for app_id + model_id combination
        """
        self.data_extraction_from_request(request)
        return f"{self.app_id}:{self.model_id}"

    def find_model_config(self):
        """
        Find model configuration for current app_id and model_id
        """
        if not self.rate_limits_config:
            self._load_rate_limit_config()
            
        for app in self.rate_limits_config["apps"]:
            if app["application-id"] == self.app_id:
                for model in app["models"]:
                    if model["model_id"] == self.model_id:
                        return model
        return None

    def get_rate_limiting_string(self):
        """
        Get rate limiting configuration string for app_id + model_id
        """
        model_config = self.find_model_config()
        if model_config:
            rate_limit = model_config.get("rate_limit", {})
            rpm = rate_limit.get("rpm", "unknown")
            return f"{rpm}/minute"
        return "unknown/minute"

    def apply_rate_limit(self, request, tokens_requested):
        """
        Apply rate limiting at app_id + model_id level
        """
        return self.allow_request(request, tokens_requested)

    def init_redis_dynamic_state(self, redis_client):
        """
        Initialize Redis state for all app_id + model_id combinations from config
        """
        try:
            # Load config from iConfig
            dynamic_ratelimit_config = json.loads(get_iconfig().configurations["RATE_LIMITS_DYNAMIC_INIT"])
            
            for app in dynamic_ratelimit_config["apps"]:
                app_id = app["application-id"]
                for model in app["models"]:
                    model_id = model["model_id"] 
                    burst = model.get("burst", {})
                    rate = model.get("rate_limit", {})
                    
                    # Initialize state for this app_id + model_id combination
                    dynamic_state = {
                        "available_tokens": rate.get("max_tokens", 1000),
                        "last_refill_ts": time.time(),
                        "burst_tokens_used": 0,
                        "burst_window_start": time.time()
                    }
                    
                    # IMPROVED: Use app_id:model_id key structure
                    redis_key = f"ratelimit:{app_id}:{model_id}"
                    redis_client.hset(redis_key, dynamic_state)
                    print(f"Stored: {redis_key} -> {dynamic_state}")
                    
        except Exception as e:
            amt_logger.logger.error(f"Failed to initialize Redis dynamic state: {str(e)}")

    def update_dynamic_token_state(self, redis_client, tokens_requested):
        """
        Update dynamic token state for current app_id + model_id
        """
        try:
            # Use app_id:model_id key structure
            redis_key = f"ratelimit:{self.app_id}:{self.model_id}"
            
            # Load and update state
            state = self._get_state()
            state["available_tokens"] = max(0, state["available_tokens"] - tokens_requested)
            state["last_refill_ts"] = time.time()
            
            # Save updated state
            self._save_state(state)
            print(f"Updated {redis_key} -> {state}")
            
        except Exception as e:
            amt_logger.logger.error(f"Failed to update dynamic token state: {str(e)}")
