# api/cache_api.py

from fastapi import APIRouter, HTTPException

from services.market_analysis_cache import market_analysis_cache

router = APIRouter(prefix="/api/cache", tags=["Cache"])


@router.get("")
def get_cache():
    """
    Return the complete in-memory market analysis cache.
    """
    return {
        "status": "success",
        "count": market_analysis_cache.count(),
        "data": market_analysis_cache.get_all(),
    }


@router.get("/{strike}/{option_type}")
def get_cache_item(strike: str, option_type: str):
    """
    Return a single cached document.

    Example:
        /api/cache/24500/CE
    """

    option_type = option_type.upper()

    doc = market_analysis_cache.get(strike, option_type)

    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"{strike} {option_type} not found in cache.",
        )

    return {
        "status": "success",
        "data": doc,
    }


@router.post("/reload")
def reload_cache():
    """
    Reload the cache from MongoDB.
    """

    market_analysis_cache.reload()

    return {
        "status": "success",
        "message": "Cache reloaded successfully.",
        "count": market_analysis_cache.count(),
    }
