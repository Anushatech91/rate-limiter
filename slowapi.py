1. Decorator-Based: Expose Request Parameter in Function That Calls the Model
If your model-calling logic is defined in a separate module (e.g. llm_service.py), you can still apply SlowAPI decorators around that function—as long as it accepts a Request.

In llm_service.py:

python
Copy
Edit
from slowapi import Limiter
from fastapi import Request

limiter = Limiter(...)  # use same limiter instance as in app initialization

@limiter.shared_limit("50/minute", scope=lambda req: f"{req.state.user}:{req.state.model}")
async def call_model(request: Request, payload: dict):
    # call the downstream LLM here
    return await do_llm(payload)
Then in your route handler:

python
Copy
Edit
from fastapi import Request
from llm_service import call_model

@app.post("/inference")
async def infer(request: Request, payload: PayloadModel):
    request.state.user = payload.user_id
    request.state.model = payload.model_name
    return await call_model(request, payload.dict())
This ensures SlowAPI sees the Request and can apply its rate limit logic using the same shared limiter.
