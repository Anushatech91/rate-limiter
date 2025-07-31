def rate_limit_key_func(request):
    # Default fallback values
    app_id = "unknown-app"
    model_id = "unknown-model"
    env = "unknown-env"
    error_stage = None

    try:
        config = get_iconfig().configurations
    except Exception as e:
        error_stage = "get_iconfig"
        amt_logger.logger.error(f"[rate_limit_key_func][{error_stage}] Failed to get iconfig: {str(e)}")
        return f"{env}:{app_id}:{model_id}:error-{error_stage}"

    try:
        endpoint_config = json.loads(config["ENDPOINT_CONFIG"])
    except Exception as e:
        error_stage = "parse_endpoint_config"
        amt_logger.logger.error(f"[rate_limit_key_func][{error_stage}] Failed to parse ENDPOINT_CONFIG: {str(e)}")
        return f"{env}:{app_id}:{model_id}:error-{error_stage}"

    try:
        env = config["ENVIRONMENT"]
    except Exception as e:
        error_stage = "get_environment"
        amt_logger.logger.error(f"[rate_limit_key_func][{error_stage}] Failed to retrieve ENVIRONMENT: {str(e)}")
        # Still proceed; fallback env used

    app_id = endpoint_config.get("app_id", "missing-app_id")
    model_id = endpoint_config.get("model_id", "missing-model_id")

    # Optionally attach request identity (IP, user ID, etc.)
    client_ip = request.client.host if request.client else "unknown-ip"

    return f"{env}:{app_id}:{model_id}:{client_ip}"
