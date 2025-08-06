✅ Call This Function In Your Rate-Limiting Endpoint or Middleware
For example, in a FastAPI route:

python
Copy
Edit
@app.post("/chat")
def chat_endpoint(app_id: str, model_id: str, tokens_requested: int):
    try:
        update_rate_limit(app_id, model_id, tokens_requested)
    except Exception as e:
        raise HTTPException(status_code=429, detail=str(e))

    return {"message": "Request accepted."}
