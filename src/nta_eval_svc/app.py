from fastapi import FastAPI

from nta_eval_svc.routers import tasks_api_router
from nta_eval_svc.config import config
from nta_eval_svc.middleware import RateLimitingMiddleware
from nta_eval_svc.routers.long_polling_api import long_polling_api_router

app = FastAPI(debug=True)

# Register middleware for rate limiting long-poll endpoints
app.add_middleware(RateLimitingMiddleware, config=config)

# Register routers
app.include_router(tasks_api_router, prefix="/api")
app.include_router(long_polling_api_router, prefix="/api")
