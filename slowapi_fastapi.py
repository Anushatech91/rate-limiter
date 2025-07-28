from fastapi import FastAPI, Request
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi import Limiter
from llm_service import call_model

app = FastAPI()
limiter = Limiter(key_func=get_remote_address, storage_uri="redis://localhost:6379")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

@app.post("/inference")
async def inference(request: Request, payload: PayloadModel):
    # Set metadata for limiter scope
    request.state.user = payload.user_id
    request.state.model = payload.model_name
    # Delegate to service-level function
    return await call_model(request, payload.dict())


--------------
# limiter_config.py or app.py
from slowapi import Limiter
from limits.storage import RedisStorage  # optional for production

def rate_limit_key_func(request):
    return f"{request.state.app_id}:{request.state.model}"

limiter = Limiter(
    key_func=rate_limit_key_func,
    storage_uri="redis://localhost:6379"  # optional: for persistent, distributed limits
)
