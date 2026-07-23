# services/upstox_service.py

from typing import List, Dict, Any, Optional
import upstox_client
from core.logger import get_logger

logger = get_logger("upstox_service")


class UpstoxService:
    """
    Service wrapper for fetching market data using upstox_client.
    """

    def __init__(self):
        # Initialize HistoryV3Api instance
        self.history_api = upstox_client.HistoryV3Api()

    def fetch_intraday_candles(
        self, instrument_key: str, unit: str = "minutes", interval: str = "1"
    ) -> List[List[Any]]:
        """
        Fetches intraday candle data for a given instrument key.

        Args:
            instrument_key (str): The Upstox instrument key (e.g., "NSE_EQ|INE848E01016" or "NSE_FO|63959").
            unit (str): Time unit (default: "minutes").
            interval (str): Interval length (default: "1").

        Returns:
            List[List[Any]]: List of candles where each candle format is:
                            [timestamp, open, high, low, close, volume, open_interest]
                            Returns an empty list if an error occurs.
        """
        try:
            # Calling Upstox SDK HistoryV3Api endpoint
            response = self.history_api.get_intra_day_candle_data(
                instrument_key=instrument_key, unit=unit, interval=interval
            )

            # Check response structure and extract candle data
            if response and hasattr(response, "data") and response.data:
                candles = getattr(response.data, "candles", [])
                if candles:
                    return candles

            logger.warning(f"No candle data returned for instrument: {instrument_key}")
            return []

        except Exception as e:
            logger.error(
                f"Exception when calling HistoryV3Api->get_intra_day_candle_data "
                f"for instrument {instrument_key}: {e}"
            )
            return []


# Single instance export for direct imports across services
upstox_service = UpstoxService()
