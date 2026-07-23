# main.py

import asyncio,os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from api.cache_api import router as cache_router
from api.system_api import router as system_router
from core.config import settings
from core.logger import get_logger
from core.time_utils import get_ist_formatted, get_ist_now
from services.live_ema_service import live_ema_service
from services.market_analysis_cache import market_analysis_cache
from services.market_scheduler import market_scheduler
from services.telegram_service import telegram_service

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle.

    Initializes market analysis cache, performs live EMA daily cache reset,
    starts background market scheduler, and sends Telegram notifications.
    """

    logger.info("=" * 60)
    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Project Started at (IST): {get_ist_formatted()}")
    logger.info("Application starting...")

    # 1. Load market analysis cache
    market_analysis_cache.load()

    cache_count = market_analysis_cache.count()
    logger.info(f"Market Analysis Cache Loaded: {cache_count} documents")

    # 2. Reset Live EMA Daily Cache in DB & Get Summary
    today_str = get_ist_now().strftime("%Y-%m-%d")
    cache_data = market_analysis_cache.get_all()  # Retrieves full in-memory cache dict

    reset_summary = live_ema_service.reset_today_cache(today_str, cache_data)

    logger.info(
        f"Live EMA Daily Cache Reset completed for date: {reset_summary.get('date')} "
        f"({reset_summary.get('total_instruments')} instruments initialized)"
    )

    # 3. Start the Market Scheduler task in the background asyncio event loop
    scheduler_task = asyncio.create_task(market_scheduler.start())
    logger.info("Live Market Scheduler background task started.")

    # 4. 🔔 Send Telegram startup alert
    await telegram_service.notify_app_startup()

    # 5. 🔔 Send Telegram Cache Reset & Market Analysis Summary Alert
    sample = reset_summary.get("sample_instrument") or {}
    sample_key = sample.get("instrument_key", "N/A")
    sample_symbol = sample.get("trading_symbol", "N/A")
    sample_strike = sample.get("strike", "N/A")
    sample_type = sample.get("type", "N/A")

    summary_msg = (
        f"🔄 <b>Pre-Market Cache Reset Summary</b>\n\n"
        f"📅 <b>Date:</b> <code>{reset_summary.get('date')}</code>\n"
        f"📊 <b>Market Analysis Loaded:</b> <code>{cache_count}</code> documents\n"
        f"⚙️ <b>Live EMA Initialized:</b> <code>{reset_summary.get('total_instruments')}</code> instruments\n\n"
        f"📝 <b>Sample Metadata:</b>\n"
        f"• <b>Symbol:</b> {sample_symbol}\n"
        f"• <b>Key:</b> <code>{sample_key}</code>\n"
        f"• <b>Strike:</b> {sample_strike}\n"
        f"• <b>Type:</b> {sample_type}\n\n"
        f"⚡ <i>Live EMA Analysis ready for trading!</i>"
    )

    await telegram_service.send_message(summary_msg)

    logger.info("Startup completed successfully.")
    logger.info("=" * 60)

    yield

    # Application Shutdown
    logger.info("=" * 60)
    logger.info(f"Application shutting down at (IST): {get_ist_formatted()}...")

    # 🔔 Send Telegram shutdown alert
    await telegram_service.notify_app_shutdown()

    # Gracefully stop background scheduler
    market_scheduler.stop()
    scheduler_task.cancel()

    try:
        await scheduler_task
    except asyncio.CancelledError:
        logger.info("Market Scheduler background task successfully cancelled.")

    logger.info("Shutdown completed successfully.")
    logger.info("=" * 60)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# Register Routers
app.include_router(cache_router)
app.include_router(system_router)


@app.get("/")
def root():
    return {
        "status": "success",
        "application": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "current_time_ist": get_ist_formatted(),
        "cache_documents": market_analysis_cache.count(),
        "scheduler_running": market_scheduler.is_running,
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "application": settings.APP_NAME,
        "current_time_ist": get_ist_formatted(),
        "cache_loaded": market_analysis_cache.count() > 0,
        "cache_documents": market_analysis_cache.count(),
        "scheduler_running": market_scheduler.is_running,
    }



if __name__ == "__main__":
    logger.info("Starting Uvicorn server...")
    
    # Read dynamic PORT from Railway environment variable (defaults to 8000 locally)
    port = int(os.getenv("PORT", 8000))

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,  # Disable reload in production
    )
