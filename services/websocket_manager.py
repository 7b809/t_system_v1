import json
from threading import RLock
from typing import Dict, Optional, Any

from fastapi import WebSocket


class WebSocketManager:
    """
    Frontend WebSocket manager.

    Purpose:
    - Accept frontend WebSocket connections.
    - Store each client's subscription filter.
    - Send live LTP updates only to matching clients.

    Example frontend subscription message:

    {
        "strike": "24500",
        "type": "PE"
    }

    Matching backend payload:

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

    _lock = RLock()

    # Format:
    # {
    #     websocket: {
    #         "strike": "24500",
    #         "type": "PE",
    #         "instrument_key": None,
    #         "send_all": False
    #     }
    # }
    _clients: Dict[WebSocket, Dict[str, Any]] = {}

    @classmethod
    async def connect(cls, websocket: WebSocket):
        """
        Accept a new frontend WebSocket connection.
        """

        await websocket.accept()

        with cls._lock:
            cls._clients[websocket] = {
                "strike": None,
                "type": None,
                "instrument_key": None,
                "send_all": False,
            }

        await cls._safe_send(
            websocket,
            {
                "event": "connected",
                "message": "WebSocket connected successfully.",
            },
        )

    @classmethod
    def disconnect(cls, websocket: WebSocket):
        """
        Remove frontend WebSocket connection.
        """

        with cls._lock:
            if websocket in cls._clients:
                del cls._clients[websocket]

    @classmethod
    def update_subscription(
        cls,
        websocket: WebSocket,
        strike: Optional[str] = None,
        option_type: Optional[str] = None,
        instrument_key: Optional[str] = None,
        send_all: bool = False,
    ):
        """
        Update client subscription.

        Client can subscribe using:
        - strike + type
        - instrument_key
        - send_all=True

        Examples:
        {
            "strike": "24500",
            "type": "PE"
        }

        {
            "instrument_key": "NSE_FO|12345"
        }

        {
            "send_all": true
        }
        """

        normalized_strike = str(strike).strip() if strike else None

        normalized_type = str(option_type).strip().upper() if option_type else None

        normalized_instrument_key = (
            str(instrument_key).strip() if instrument_key else None
        )

        with cls._lock:
            if websocket in cls._clients:
                cls._clients[websocket] = {
                    "strike": normalized_strike,
                    "type": normalized_type,
                    "instrument_key": normalized_instrument_key,
                    "send_all": bool(send_all),
                }

    @classmethod
    def get_client_count(cls) -> int:
        """
        Return total connected frontend WebSocket clients.
        """

        with cls._lock:
            return len(cls._clients)

    @classmethod
    def get_subscriptions_snapshot(cls) -> list:
        """
        Return current subscriptions snapshot.
        Useful for debugging.
        """

        with cls._lock:
            return list(cls._clients.values())

    @classmethod
    async def broadcast_ltp(cls, payload: dict):
        """
        Broadcast LTP update to matching frontend clients.

        Matching priority:
        1. If client has send_all=True, send every tick.
        2. If client subscribed by instrument_key, match instrument_key.
        3. If client subscribed by strike + type, match strike and type.
        4. If client has no filters, send every tick.
        """

        disconnected_clients = []

        with cls._lock:
            clients_snapshot = dict(cls._clients)

        for websocket, subscription in clients_snapshot.items():
            try:
                if cls._matches_subscription(
                    payload=payload,
                    subscription=subscription,
                ):
                    await cls._safe_send(websocket, payload)

            except Exception:
                disconnected_clients.append(websocket)

        for websocket in disconnected_clients:
            cls.disconnect(websocket)

    @classmethod
    async def broadcast_message(cls, message: dict):
        """
        Broadcast generic message to all connected frontend clients.
        """

        disconnected_clients = []

        with cls._lock:
            clients_snapshot = dict(cls._clients)

        for websocket in clients_snapshot.keys():
            try:
                await cls._safe_send(websocket, message)

            except Exception:
                disconnected_clients.append(websocket)

        for websocket in disconnected_clients:
            cls.disconnect(websocket)

    @classmethod
    def _matches_subscription(
        cls,
        payload: dict,
        subscription: dict,
    ) -> bool:
        """
        Check whether payload matches client subscription.
        """

        if not subscription:
            return True

        send_all = subscription.get("send_all", False)

        if send_all:
            return True

        sub_instrument_key = subscription.get("instrument_key")
        sub_strike = subscription.get("strike")
        sub_type = subscription.get("type")

        payload_instrument_key = str(payload.get("instrument_key", "")).strip()

        payload_strike = str(payload.get("strike", "")).strip()

        payload_type = str(payload.get("type", "")).strip().upper()

        # -------------------------------------------------
        # Match by instrument_key
        # -------------------------------------------------
        if sub_instrument_key:
            return sub_instrument_key == payload_instrument_key

        # -------------------------------------------------
        # Match by strike + type
        # -------------------------------------------------
        if sub_strike and sub_type:
            return sub_strike == payload_strike and sub_type == payload_type

        # -------------------------------------------------
        # Match only strike
        # -------------------------------------------------
        if sub_strike and not sub_type:
            return sub_strike == payload_strike

        # -------------------------------------------------
        # Match only type CE/PE
        # -------------------------------------------------
        if sub_type and not sub_strike:
            return sub_type == payload_type

        # -------------------------------------------------
        # No filter means receive all ticks
        # -------------------------------------------------
        return True

    @classmethod
    async def _safe_send(
        cls,
        websocket: WebSocket,
        payload: dict,
    ):
        """
        Send JSON safely to one WebSocket client.
        """

        message = json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        )

        await websocket.send_text(message)
