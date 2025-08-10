def get_rate_limiting_string(self, request: Request):
    app_id = request.state.app_id
    model_id = request.state.model_id
    
    model_config = self.model_lookup.get((app_id, model_id))
    if not model_config:
        return None
    
    rate_limit = model_config.get("rate_limit", {})
    return f"{app_id}:{model_id}:{rate_limit.get('rpm', 0)}"
