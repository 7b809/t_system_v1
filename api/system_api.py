# api/system_api.py

import sys
from fastapi import APIRouter, Request
from core.config import settings
from core.time_utils import get_ist_formatted
from services.market_analysis_cache import market_analysis_cache
from services.market_scheduler import market_scheduler

router = APIRouter(prefix="/api/system", tags=["System & Management"])


@router.get("/")
def health_check():
    """Detailed health check endpoint reporting status of database cache and market scheduler."""
    cache_count = market_analysis_cache.count()
    return {
        "status": "healthy",
        "application": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "current_time_ist": get_ist_formatted(),
        "python_version": sys.version.split(" ")[0],
        "cache": {
            "loaded": cache_count > 0,
            "document_count": cache_count,
        },
        "scheduler": {
            "running": market_scheduler.is_running,
        },
    }


@router.get("/routes")
def list_available_apis(request: Request):
    """Dynamically inspects the FastAPI application instance and returns a list

    of all active registered routes, HTTP methods, and tags.
    """
    routes = []
    for route in request.app.routes:
        if hasattr(route, "endpoint") and hasattr(route, "methods"):
            routes.append(
                {
                    "path": route.path,
                    "name": route.name,
                    "methods": list(route.methods),
                    "tags": getattr(route, "tags", []),
                }
            )

    return {
        "status": "success",
        "total_routes": len(routes),
        "routes": routes,
    }
