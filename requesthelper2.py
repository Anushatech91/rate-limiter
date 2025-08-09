import time
import json
import re
from urllib.parse import unquote
from utils.llm_proxy_service import ROUTE_PREFIX

class RequestHelper:
    def __init__(self):
        """
        Initialize RequestHelper with dual rate limiting:
        1. Token-based (dynamic) - uses RATE_LIMITS_DYNAMIC_INIT
        2. API rate limiting (fixed) - uses RATE_LIMITS
        """
        self.app_id = None
        self.model_id = None
        
        # Token-based rate limiting config (from RATE_LIMITS_DYNAMIC_INIT)
        self.max_tokens = None
        self.refill_rate = None
        self.burst_capacity = None
        self.burst_window = None
        self.dynamic_config = None
        
        # API rate limiting config (from RATE_LIMITS) 
        self.api_rate_config = None
        self.requests_per_minute = None
        self.requests_per_second = None

    def _load_dynamic_rate_limit_config(self):
        """
        Load dynamic/token-based rate limiting configuration from RATE_LIMITS_DYNAMIC_INIT
        """
        try:
            self.dynamic_config = json.loads(get_iconfig().configurations["RATE_LIMITS_DYNAMIC_INIT"])
        except Exception as e:
            amt_logger.logger.error(f"Failed to load dynamic rate limits config: {str(e)}")
            self.dynamic_config = {"apps": []}

    def _load_api_rate_limit_config(self):
        """
        Load fixed API rate limiting configuration from RATE_LIMITS
        """
        try:
            self.api_rate_config = json.loads(get_iconfig().configurations["RATE_LIMITS"])
        except Exception as e:
            amt_logger.logger.error(f"Failed to load API rate limits config: {str(e)}")
            self.api_rate_config = {"apps": []}

    def _get_dynamic_config_for_app_model(self):
        """
        Get dynamic/token-based configuration for current app_id and model_id
        """
        if not self.dynamic_config:
            self._load_dynamic_rate_limit_config()
            
        for app in self.dynamic_config["apps"]:
            if app["application-id"] == self.app_id:
                for model in app["models"]:
                    if model["model_id"] == self.model_id:
                        # Extract token-based rate limiting parameters
                        rate_limit = model.get("rate_limit", {})
                        burst = model.get("burst", {})
                        
                        self.max_tokens = rate_limit.get("max_tokens", 1000)
                        self.refill_rate = rate_limit.get("refill_rate", 10)
                        self.burst_capacity = burst.get("capacity", 100)
                        self.burst_window = burst.get("window", 60)
                        
                        return model
        
        # Default values if not found in dynamic config
        self.max_tokens = 1000
        self.refill_rate = 10
        self.burst_capacity = 100
        self.burst_window = 60
        return None

    def _get_api_rate_config_for_app_model(self):
        """
        Get fixed API rate limiting configuration for current app_id and model_id
        """
        if not self.api_rate_config:
            self._load_api_rate_limit_config()
            
        for app in self.api_rate_config["apps"]:
            if app["application-id"] == self.app_id:
                for model in app["models"]:
                    if model["model_id"] == self.model_id:
                        # Extract API rate limiting parameters
                        rate_limit = model.get("rate_limit", {})
                        
                        self.requests_per_minute = rate_limit.get("rpm", 60)
                        self.requests_per_second = rate_limit.get("rps", 1)
                        
                        return model
        
        # Default values if not found in API config
        self.requests_per_minute = 60
        self.requests_per_second = 1
        return None

    def _get_dynamic_state(self):
        """
        Get current dynamic/token-based state for app_id + model_id combination
        """
        key = f"dynamic:{self.app_id}:{self.model_id}"
        
        try:
            state_data = redis_client.hmget(key, [
                "available_tokens", "last_refill_ts", 
                "burst_tokens_used", "burst_window_start"
            ])
            
            if not any(state_data):
                # Initialize with defaults from dynamic config
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
            amt_logger.logger.error(f"Failed to get dynamic state for {key}: {str(e)}")
            return {
                "available_tokens": float(self.max_tokens or 1000),
                "last_refill_ts": float(time.time()),
                "burst_tokens_used": float(0),
                "burst_window_start": float(time.time())
            }

    def _save_dynamic_state(self, state):
        """
        Save dynamic/token-based state for app_id + model_id combination
        """
        key = f"dynamic:{self.app_id}:{self.model_id}"
        try:
            redis_client.hset(key, {
                "available_tokens": state["available_tokens"],
                "last_refill_ts": state["last_refill_ts"], 
                "burst_tokens_used": state["burst_tokens_used"],
                "burst_window_start": state["burst_window_start"]
            })
        except Exception as e:
            amt_logger.logger.error(f"Failed to save dynamic state for {key}: {str(e)}")

    def _get_api_rate_state(self):
        """
        Get current API rate limiting state for app_id + model_id combination
        """
        key = f"api_rate:{self.app_id}:{self.model_id}"
        
        try:
            state_data = redis_client.hmget(key, [
                "requests_this_minute", "minute_window_start",
                "requests_this_second", "second_window_start"
            ])
            
            now = time.time()
            return {
                "requests_this_minute": int(state_data[0] or 0),
                "minute_window_start": float(state_data[1] or now),
                "requests_this_second": int(state_data[2] or 0),
                "second_window_start": float(state_data[3] or now)
            }
        except Exception as e:
            amt_logger.logger.error(f"Failed to get API rate state: {str(e)}")
            now = time.time()
            return {
                "requests_this_minute": 0,
                "minute_window_start": now,
                "requests_this_second": 0,
                "second_window_start": now
            }

    def _save_api_rate_state(self, state):
        """
        Save API rate limiting state for app_id + model_id combination
        """
        key = f"api_rate:{self.app_id}:{self.model_id}"
        try:
            redis_client.hset(key, {
                "requests_this_minute": state["requests_this_minute"],
                "minute_window_start": state["minute_window_start"],
                "requests_this_second": state["requests_this_second"],
                "second_window_start": state["second_window_start"]
            })
        except Exception as e:
            amt_logger.logger.error(f"Failed to save API rate state for {key}: {str(e)}")

    def check_token_based_rate_limit(self, request, requested_tokens):
        """
        Check token-based rate limiting (uses RATE_LIMITS_DYNAMIC_INIT config)
        """
        # Load dynamic config for this app_id + model_id
        self._get_dynamic_config_for_app_model()
        
        now = time.time()
        state = self._get_dynamic_state()

        # Token bucket refill logic
        elapsed = now - state["last_refill_ts"]
        refill = elapsed * self.refill_rate
        state["available_tokens"] = min(self.max_tokens, state["available_tokens"] + refill)
        state["last_refill_ts"] = now

        # Burst window reset logic
        if now - state["burst_window_start"] > self.burst_window:
            state["burst_window_start"] = now
            state["burst_tokens_used"] = 0

        # Decision logic for token-based limiting
        if requested_tokens <= state["available_tokens"]:
            state["available_tokens"] -= requested_tokens
            self._save_dynamic_state(state)
            return True, "Allowed via token quota"
        elif state["burst_tokens_used"] + requested_tokens <= self.burst_capacity:
            state["burst_tokens_used"] += requested_tokens
            self._save_dynamic_state(state)
            return True, "Allowed via token burst quota"
        else:
            self._save_dynamic_state(state)
            return False, "Token limit exceeded"

    def check_api_rate_limit(self, request):
        """
        Check API rate limiting (uses RATE_LIMITS config)
        """
        # Load API rate config for this app_id + model_id
        self._get_api_rate_config_for_app_model()
        
        now = time.time()
        state = self._get_api_rate_state()

        # Reset minute window if needed
        if now - state["minute_window_start"] >= 60:
            state["minute_window_start"] = now
            state["requests_this_minute"] = 0

        # Reset second window if needed
        if now - state["second_window_start"] >= 1:
            state["second_window_start"] = now
            state["requests_this_second"] = 0

        # Check rate limits
        if state["requests_this_minute"] >= self.requests_per_minute:
            self._save_api_rate_state(state)
            return False, f"API rate limit exceeded: {self.requests_per_minute} requests/minute"

        if state["requests_this_second"] >= self.requests_per_second:
            self._save_api_rate_state(state)
            return False, f"API rate limit exceeded: {self.requests_per_second} requests/second"

        # Increment counters
        state["requests_this_minute"] += 1
        state["requests_this_second"] += 1
        self._save_api_rate_state(state)
        
        return True, "API rate limit passed"

    def allow_request(self, request, requested_tokens=None):
        """
        Main method: Check both token-based AND API rate limiting
        """
        # First extract app_id and model_id from request
        self.data_extraction_from_request(request)
        
        # Check API rate limiting first (faster check)
        api_allowed, api_message = self.check_api_rate_limit(request)
        if not api_allowed:
            return False, api_message
        
        # If API rate limit passed, check token-based rate limiting
        if requested_tokens is not None:
            token_allowed, token_message = self.check_token_based_rate_limit(request, requested_tokens)
            if not token_allowed:
                return False, token_message
            
            return True, f"Request allowed - {api_message} + {token_message}"
        else:
            return True, f"Request allowed - {api_message}"

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

    def init_redis_dynamic_state(self, redis_client):
        """
        Initialize Redis state for dynamic rate limiting (from RATE_LIMITS_DYNAMIC_INIT)
        """
        try:
            # Load dynamic config from iConfig
            dynamic_ratelimit_config = json.loads(get_iconfig().configurations["RATE_LIMITS_DYNAMIC_INIT"])
            
            for app in dynamic_ratelimit_config["apps"]:
                app_id = app["application-id"]
                for model in app["models"]:
                    model_id = model["model_id"] 
                    burst = model.get("burst", {})
                    rate = model.get("rate_limit", {})
                    
                    # Initialize dynamic state for this app_id + model_id combination
                    dynamic_state = {
                        "available_tokens": rate.get("max_tokens", 1000),
                        "last_refill_ts": time.time(),
                        "burst_tokens_used": 0,
                        "burst_window_start": time.time()
                    }
                    
                    # Store dynamic rate limiting state
                    redis_key = f"dynamic:{app_id}:{model_id}"
                    redis_client.hset(redis_key, dynamic_state)
                    print(f"Stored dynamic: {redis_key} -> {dynamic_state}")
                    
        except Exception as e:
            amt_logger.logger.error(f"Failed to initialize Redis dynamic state: {str(e)}")

    def init_redis_api_rate_state(self, redis_client):
        """
        Initialize Redis state for API rate limiting (from RATE_LIMITS)
        """
        try:
            # Load API rate config from iConfig
            api_rate_config = json.loads(get_iconfig().configurations["RATE_LIMITS"])
            
            for app in api_rate_config["apps"]:
                app_id = app["application-id"]
                for model in app["models"]:
                    model_id = model["model_id"]
                    
                    # Initialize API rate limiting state
                    now = time.time()
                    api_state = {
                        "requests_this_minute": 0,
                        "minute_window_start": now,
                        "requests_this_second": 0,
                        "second_window_start": now
                    }
                    
                    # Store API rate limiting state
                    redis_key = f"api_rate:{app_id}:{model_id}"
                    redis_client.hset(redis_key, api_state)
                    print(f"Stored API rate: {redis_key} -> {api_state}")
                    
        except Exception as e:
            amt_logger.logger.error(f"Failed to initialize Redis API rate state: {str(e)}")

    # Legacy methods for backward compatibility
    def get_unique_string(self, request):
        """Generate unique string for app_id + model_id combination"""
        self.data_extraction_from_request(request)
        return f"{self.app_id}:{self.model_id}"

    def apply_rate_limit(self, request, tokens_requested=None):
        """Legacy method - use allow_request instead"""
        return self.allow_request(request, tokens_requested)
