import json
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from core.logger import get_logger
from core.datetime_utils import now
from services.dashboard_state import DashboardState
from services.websocket_manager import WebSocketManager

logger = get_logger(__name__)

router = APIRouter()

templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """
    Render main dashboard page.

    This page loads templates/index.html.

    Existing behavior:
    - Frontend can still call /api/dashboard for full snapshot.

    New behavior:
    - Frontend can also connect to /ws/ltp for live LTP updates.
    """
    try:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "request": request,
            },
        )

    except Exception as ex:
        logger.exception(f"Failed rendering dashboard page: {ex}")

        return HTMLResponse(
            content="""
            <html>
                <head>
                    <title>Dashboard Error</title>
                </head>
                <body>
                    <h2>Dashboard rendering failed</h2>
                    <p>Please check templates/index.html exists.</p>
                </body>
            </html>
            """,
            status_code=500,
        )


@router.get("/api/dashboard")
async def get_dashboard_snapshot():
    """
    Return complete dashboard state as JSON.

    Used by static/dashboard.js to refresh dashboard data.

    Response contains:
    - app info
    - market status
    - websocket status
    - NIFTY index data
    - runtime summary
    - all subscribed instrument states
    - recent crossovers
    """
    try:
        snapshot = DashboardState.get_snapshot()

        return JSONResponse(
            content=snapshot,
            status_code=200,
        )

    except Exception as ex:
        logger.exception(f"Dashboard API failed: {ex}")

        return JSONResponse(
            content={
                "status": "error",
                "message": str(ex),
            },
            status_code=500,
        )


@router.get("/api/health")
async def dashboard_health():
    """
    Lightweight health endpoint.

    Useful for:
    - browser check
    - deployment platform health checks
    - quick dashboard availability validation
    """
    try:
        snapshot = DashboardState.get_snapshot()

        return JSONResponse(
            content={
                "status": "ok",
                "dashboard": "running",
                "upstox_websocket_connected": snapshot.get("status", {}).get(
                    "websocket_connected"
                ),
                "frontend_socket_clients": WebSocketManager.get_client_count(),
                "market_status": snapshot.get("status", {}).get("market_status"),
                "scheduler_status": snapshot.get("status", {}).get("scheduler_status"),
                "total_runtime_instruments": snapshot.get("summary", {}).get(
                    "total_runtime_instruments"
                ),
                "total_ticks": snapshot.get("summary", {}).get("total_ticks"),
                "last_feed_time": snapshot.get("status", {}).get("last_feed_time"),
            },
            status_code=200,
        )

    except Exception as ex:
        logger.exception(f"Dashboard health check failed: {ex}")

        return JSONResponse(
            content={
                "status": "error",
                "dashboard": "failed",
                "message": str(ex),
            },
            status_code=500,
        )


@router.get("/api/socket/clients")
async def get_socket_clients():
    """
    Debug endpoint.

    Returns frontend WebSocket client count and subscription snapshot.

    Useful for checking:
    - How many browser clients are connected
    - What strike/type each client subscribed to
    """
    try:
        return JSONResponse(
            content={
                "status": "ok",
                "client_count": WebSocketManager.get_client_count(),
                "subscriptions": WebSocketManager.get_subscriptions_snapshot(),
            },
            status_code=200,
        )

    except Exception as ex:
        logger.exception(f"Socket clients API failed: {ex}")

        return JSONResponse(
            content={
                "status": "error",
                "message": str(ex),
            },
            status_code=500,
        )


@router.websocket("/ws/ltp")
async def websocket_ltp(websocket: WebSocket):
    """
    Frontend WebSocket endpoint for live LTP updates.

    Frontend connects to:

        ws://localhost:8000/ws/ltp

    Then frontend can subscribe by strike/type:

        {
            "strike": "24500",
            "type": "PE"
        }

    Or by instrument_key:

        {
            "instrument_key": "NSE_FO|12345"
        }

    Or receive all live ticks:

        {
            "send_all": true
        }

    Backend will push messages like:

        {
            "event": "ltp_update",
            "instrument_key": "NSE_FO|12345",
            "strike": "24500",
            "type": "PE",
            "trading_symbol": "NIFTY24500PE",
            "ltp": 12.45,
            "volume": 100,
            "timestamp": "2026-07-20T09:15:00+05:30"
        }
    """
    await WebSocketManager.connect(websocket)

    try:
        while True:
            message = await websocket.receive_text()

            try:
                data = json.loads(message)

                strike = data.get("strike")
                option_type = (
                    data.get("type")
                    or data.get("option_type")
                    or data.get("optionType")
                )
                instrument_key = data.get("instrument_key")
                send_all = data.get("send_all", False)

                WebSocketManager.update_subscription(
                    websocket=websocket,
                    strike=strike,
                    option_type=option_type,
                    instrument_key=instrument_key,
                    send_all=send_all,
                )

                await websocket.send_text(
                    json.dumps(
                        {
                            "event": "subscription_updated",
                            "strike": strike,
                            "type": option_type,
                            "instrument_key": instrument_key,
                            "send_all": bool(send_all),
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                )

            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps(
                        {
                            "event": "error",
                            "message": "Invalid JSON message.",
                        },
                        ensure_ascii=False,
                    )
                )

            except Exception as ex:
                logger.exception(f"WebSocket subscription update failed: {ex}")

                await websocket.send_text(
                    json.dumps(
                        {
                            "event": "error",
                            "message": str(ex),
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                )

    except WebSocketDisconnect:
        WebSocketManager.disconnect(websocket)
        logger.info("Frontend WebSocket client disconnected.")

    except Exception as ex:
        WebSocketManager.disconnect(websocket)
        logger.exception(f"Frontend WebSocket connection failed: {ex}")


# =====================================================
# NEW: JSON crossover file endpoint
# =====================================================


@router.get("/api/crossovers")
@router.get("/api/crossovers/{date}")
async def get_crossovers(date: str | None = None):
    """
    Return the local JSON crossover data for a given trading date.

    If no date is provided, uses today's date.
    File is expected at: data/crossovers/YYYY-MM-DD.json

    Returns:
        JSON object mapping instrument_key to its crossover data.
        Returns empty object if file does not exist.
    """
    try:
        # Determine date
        if date is None:
            date = now().date().isoformat()
        else:
            # Validate format (basic)
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                return JSONResponse(
                    content={"error": "Invalid date format. Use YYYY-MM-DD."},
                    status_code=400,
                )

        file_path = Path("data/crossovers") / f"{date}.json"

        if not file_path.exists():
            logger.warning(f"Crossover file not found: {file_path}")
            return JSONResponse(
                content={},
                status_code=200,
            )

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return JSONResponse(
            content=data,
            status_code=200,
        )

    except json.JSONDecodeError:
        logger.exception(f"Malformed JSON in crossover file: {file_path}")
        return JSONResponse(
            content={"error": "Crossover data corrupted."},
            status_code=500,
        )
    except Exception as ex:
        logger.exception(f"Error serving crossover file: {ex}")
        return JSONResponse(
            content={"error": "Internal server error."},
            status_code=500,
        )
