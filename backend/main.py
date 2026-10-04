"""FastAPI application entry point for Silent Window."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from backend.routes.health import router as health_router
from backend.routes.patients import router as patients_router
from backend.routes.models import router as models_router
from backend.routes.accounts import router as accounts_router
from backend.routes.workflow import router as workflow_router


LOCAL_FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app = FastAPI(
    title="Silent Window API",
    description="Backend foundation for the Silent Window dashboard.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT"],
    allow_headers=["*"],
    expose_headers=["X-Silent-Window-Model"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])


@app.exception_handler(SQLAlchemyError)
async def database_unavailable(request, error):
    return JSONResponse(status_code=503, content={"detail": "Account storage is unavailable. Check the MySQL server and retry."})


@app.middleware("http")
async def private_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response

app.include_router(health_router, prefix="/api")
app.include_router(patients_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(accounts_router, prefix="/api")
app.include_router(workflow_router, prefix="/api")
