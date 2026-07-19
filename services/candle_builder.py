from datetime import datetime
from threading import Lock

from core.logger import get_logger

logger = get_logger(__name__)


class CandleBuilder:
    """
    Converts live market ticks into
    1-minute OHLCV candles.
    """

    ACTIVE_CANDLES = {}

    _lock = Lock()

    @staticmethod
    def _extract_minute(timestamp_str: str) -> str:
        """
        Convert timestamp into minute bucket.

        Example:

        2026-07-16T09:15:12+05:30
        ->
        2026-07-16T09:15:00+05:30
        """

        try:

            dt = datetime.fromisoformat(timestamp_str)

            dt = dt.replace(second=0, microsecond=0)

            return dt.isoformat()

        except Exception as ex:

            logger.exception(f"Failed extracting minute: {ex}")
            raise

    @classmethod
    def _create_new_candle(cls, timestamp: str, price: float, volume: int) -> dict:

        return {
            "timestamp": timestamp,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": volume,
        }

    @classmethod
    def process_tick(
        cls,
        instrument_key: str,
        price: float,
        volume: int,
        timestamp: str,
    ):
        """
        Process incoming tick.

        Returns:

        None
            -> candle still forming

        dict
            -> completed candle
        """

        try:

            current_minute = cls._extract_minute(timestamp)

            with cls._lock:

                candle = cls.ACTIVE_CANDLES.get(instrument_key)

                # --------------------------------
                # First Tick
                # --------------------------------

                if candle is None:

                    cls.ACTIVE_CANDLES[instrument_key] = cls._create_new_candle(
                        current_minute,
                        price,
                        volume,
                    )

                    logger.debug(f"New candle started " f"| {instrument_key}")

                    return None

                # --------------------------------
                # Same Minute
                # --------------------------------

                if candle["timestamp"] == current_minute:

                    candle["high"] = max(candle["high"], price)

                    candle["low"] = min(candle["low"], price)

                    candle["close"] = price

                    candle["volume"] += volume

                    return None

                # --------------------------------
                # Minute Changed
                # --------------------------------

                completed_candle = candle.copy()

                cls.ACTIVE_CANDLES[instrument_key] = cls._create_new_candle(
                    current_minute,
                    price,
                    volume,
                )

                logger.info(
                    f"Candle completed "
                    f"| {instrument_key} "
                    f"| O={completed_candle['open']} "
                    f"| H={completed_candle['high']} "
                    f"| L={completed_candle['low']} "
                    f"| C={completed_candle['close']}"
                )

                return completed_candle

        except Exception as ex:

            logger.exception(f"Failed processing tick " f"{instrument_key}: {ex}")

            return None

    @classmethod
    def get_active_candle(cls, instrument_key: str):
        """
        Return active candle.
        """

        try:

            return cls.ACTIVE_CANDLES.get(instrument_key)

        except Exception as ex:

            logger.exception(f"Failed getting active candle " f"{instrument_key}: {ex}")

            return None

    @classmethod
    def get_all_active_candles(cls):
        """
        Snapshot of all active candles.

        Used by MarketScheduler
        during market close.
        """

        try:

            with cls._lock:

                return dict(cls.ACTIVE_CANDLES)

        except Exception as ex:

            logger.exception(f"Failed retrieving " f"active candles: {ex}")

            return {}

    @classmethod
    def force_close_candle(cls, instrument_key: str):
        """
        Force close single candle.
        """

        try:

            with cls._lock:

                candle = cls.ACTIVE_CANDLES.pop(instrument_key, None)

            if candle:

                logger.info(f"Force closed candle " f"| {instrument_key}")

            return candle

        except Exception as ex:

            logger.exception(f"Failed force closing " f"{instrument_key}: {ex}")

            return None

    @classmethod
    def force_close_all(cls):
        """
        Force close all candles.

        Used during shutdown.
        """

        try:

            with cls._lock:

                candle_map = dict(cls.ACTIVE_CANDLES)

                total = len(candle_map)

                cls.ACTIVE_CANDLES.clear()

            logger.info(f"Force closed " f"{total} candles.")

            return candle_map

        except Exception as ex:

            logger.exception(f"Failed force closing " f"all candles: {ex}")

            return {}

    @classmethod
    def get_total_active_candles(
        cls,
    ) -> int:
        """
        Total active candles.
        """

        try:

            return len(cls.ACTIVE_CANDLES)

        except Exception as ex:

            logger.exception(f"Failed getting " f"active candle count: {ex}")

            return 0

    @classmethod
    def get_instrument_count(cls):
        """
        Alias for monitoring.
        """

        return cls.get_total_active_candles()

    @classmethod
    def clear(cls):
        """
        Clear runtime candle cache.
        """

        try:

            with cls._lock:

                total = len(cls.ACTIVE_CANDLES)

                cls.ACTIVE_CANDLES.clear()

            logger.info(f"Cleared " f"{total} active candles.")

        except Exception as ex:

            logger.exception(f"Failed clearing " f"candles: {ex}")

    @classmethod
    def has_active_candle(cls, instrument_key: str) -> bool:
        """
        Check if candle exists.
        """

        try:

            return instrument_key in cls.ACTIVE_CANDLES

        except Exception as ex:

            logger.exception(f"Failed checking candle " f"{instrument_key}: {ex}")

            return False

    @classmethod
    def runtime_summary(cls):
        """
        Runtime monitoring summary.
        """

        try:

            total = len(cls.ACTIVE_CANDLES)

            logger.info(f"Active Candle Count: " f"{total}")

        except Exception as ex:

            logger.exception(f"Failed runtime summary: {ex}")
