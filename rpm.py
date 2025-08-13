from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

@app.middleware("http")
async def extract_ids(request: Request, call_next):
    # Extract once per request
    app_id, model_id = request_helper.data_extraction_from_request(request)
    request.state.app_id = app_id
    request.state.model_id = model_id

    # Build limiter key
    limiter_key = f"{app_id}:{model_id}"
    
    # Apply limit check manually
    try:
        limiter._check_request_limit(
            request,
            lambda req: limiter_key,  # key function
            False
        )
    except RateLimitExceeded:
        return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)

    # Continue to next handler
    response = await call_next(request)
    return response
