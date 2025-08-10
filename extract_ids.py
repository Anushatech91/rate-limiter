from fastapi import FastAPI, Request
from your_module import request_helper  # your existing helper instance

app = FastAPI()

@app.middleware("http")
async def extract_ids(request: Request, call_next):
    # Extract once per request
    app_id, model_id = request_helper.data_extraction_from_request(request)
    
    # Store in request.state so it’s available everywhere
    request.state.app_id = app_id
    request.state.model_id = model_id
    
    # Pass control to the next handler
    response = await call_next(request)
    return response
