from fastapi import FastAPI

from nta_eval_svc.routers import tasks_api_router

app = FastAPI(debug=True)

# Register routers
app.include_router(tasks_api_router, prefix="/api")
