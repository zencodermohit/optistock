from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from asgi_correlation_id import CorrelationIdMiddleware
import traceback
from fastapi import FastAPI
from app.core.logging import setup_logging
from app.core.scheduler import start_scheduler
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.database import get_db
import logging
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.rate_limit import limiter
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from redis import asyncio as aioredis
from prometheus_fastapi_instrumentator import Instrumentator
from app.core.config import settings
from app.modules.audit.listener import register_audit_listener
from app.modules.products.router import router as products_router
from app.modules.warehouses.router import router as warehouses_router
from app.modules.users.router import router as auth_router
from app.modules.sales.router import router as sales_router
from app.modules.suppliers.router import router as suppliers_router
from app.modules.purchase_orders.router import router as po_router
from app.modules.inventory.router import router as inventory_router
from app.modules.transfers.router import router as transfers_router
from app.modules.reconciliation.router import router as recon_router
from app.modules.recommendations.router import router as recommendations_router
from app.modules.companies.router import router as companies_router
from app.modules.audit.router import router as audit_router
from app.modules.customers.router import router as customers_router
from app.modules.alerts.router import router as alerts_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.events.router import router as events_router
from app.modules.ingest.router import router as ingest_router
from app.modules.insights.router import router as insights_router

setup_logging()
logger = logging.getLogger(__name__)

# Attach the flush hook that writes the compliance trail. Registered here, at
# import time, so it covers every session the process creates rather than
# depending on each service remembering to log.
register_audit_listener()

app = FastAPI(
    title="OptiStock Enterprise API",
    description="Backend for the OptiStock Inventory System",
    version="1.0.0",
)

# Instrument the FastAPI app for Prometheus metrics
Instrumentator().instrument(app).expose(app)

# 0. Setup Rate Limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 1. Add Request ID Middleware
app.add_middleware(CorrelationIdMiddleware)

# 2. Add CORS Middleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 2. Global Exception Handler (prevents raw 500 errors from leaking stack traces to clients)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log the full error + traceback as structured JSON
    logger.error(
        f"Unhandled exception: {str(exc)}",
        extra={"path": request.url.path, "traceback": traceback.format_exc()},
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected internal server error occurred. Please contact support."
        },
    )


@app.on_event("startup")
async def startup_event():
    logger.info("Starting up OptiStock API...")
    start_scheduler()

    redis = aioredis.from_url(
        settings.REDIS_URL, encoding="utf8", decode_responses=True
    )
    FastAPICache.init(RedisBackend(redis), prefix="optistock-cache")


@app.get("/health")
@limiter.limit("60/minute")
def health_check(request: Request, db: Session = Depends(get_db)):
    """Deep health probe for Kubernetes/AWS."""
    try:
        # Attempt a lightweight ping to the database
        db.execute(text("SELECT 1"))
        logger.info("Health check endpoint called. DB connection OK.")
        return {"status": "ok", "version": "1.1.0", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed. DB offline: {str(e)}")
        # 503 tells the Load Balancer to take this instance out of rotation
        raise HTTPException(
            status_code=503, detail="Service Unavailable: Database offline"
        )


@app.get("/ready")
@limiter.limit("60/minute")
def readiness_check(request: Request):
    """
    Lightweight readiness probe for Kubernetes/AWS load balancers.
    Checks if the web server process is accepting traffic.
    Does NOT check backend dependencies like the database.
    """
    return {"status": "ok", "ready": True}


app.include_router(products_router)
app.include_router(warehouses_router)
app.include_router(auth_router)
app.include_router(sales_router)
app.include_router(suppliers_router)
app.include_router(po_router)
app.include_router(inventory_router)
app.include_router(transfers_router)
app.include_router(recon_router)
app.include_router(recommendations_router)
app.include_router(companies_router)
app.include_router(audit_router)
app.include_router(customers_router)
app.include_router(alerts_router)
app.include_router(dashboard_router)
app.include_router(events_router)
app.include_router(ingest_router)
app.include_router(insights_router)
