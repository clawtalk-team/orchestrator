from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging
import os

from app.config import get_settings
from app.services.dynamodb import ensure_table_exists
from app.routes import containers, health
from app.middleware.auth import APIKeyMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.dynamodb_endpoint:
        # Local mode only — in AWS the table is provisioned by Terraform
        logger.info("Starting orchestrator — ensuring DynamoDB table exists...")
        try:
            ensure_table_exists()
        except Exception as exc:
            logger.warning("Could not reach DynamoDB at startup: %s", exc)
    yield
    logger.info("Shutting down orchestrator")


settings = get_settings()

app = FastAPI(
    title="orchestrator",
    description="Container orchestrator for OpenClaw agents",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(APIKeyMiddleware)

app.include_router(health.router)
app.include_router(containers.router)


@app.get("/", include_in_schema=False)
def root():
    return {"message": "orchestrator", "docs": "/docs"}
