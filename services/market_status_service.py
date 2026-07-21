from datetime import datetime
from zoneinfo import ZoneInfo

import upstox_client
from upstox_client.rest import ApiException

from config.settings import Settings
from core.logger import get_logger

logger = get_logger(__name__)


class MarketStatusService:

    _status_cache = {}

    @classmethod
    def get_market_status(cls, date_str: str):
        """
        Fetch market status / exchange timings for a given date.

        Uses cache to avoid repeated API calls for the same date.
        """

        try:

            if date_str in cls._status_cache:
                return cls._status_cache[date_str]

            configuration = upstox_client.Configuration()

            api_instance = upstox_client.MarketHolidaysAndTimingsApi(
                upstox_client.ApiClient(configuration)
            )

            response = api_instance.get_exchange_timings(date_str)

            cls._status_cache[date_str] = response

            return response

        except ApiException as ex:

            logger.exception(f"Failed to fetch exchange status for {date_str}: {ex}")

            return None

        except Exception as ex:

            logger.exception(
                f"Unexpected error while fetching market status for {date_str}: {ex}"
            )

            return None

    @classmethod
    def is_market_open_today(cls):
        """
        Check whether NSE has a trading session today.
        """

        try:

            today = datetime.now(ZoneInfo(Settings.TIMEZONE)).date().isoformat()

            response = cls.get_market_status(today)

            if not response:

                logger.warning(f"No market status response received for {today}")

                return False

            response_data = getattr(response, "data", None)

            if not response_data:

                logger.info(f"No exchange timing data available for {today}")

                return False

            for exchange in response_data:

                if getattr(exchange, "exchange", None) == "NSE":

                    logger.info(
                        f"NSE Session Found | "
                        f"Date={today} | "
                        f"Start={getattr(exchange, 'start_time', None)} | "
                        f"End={getattr(exchange, 'end_time', None)}"
                    )

                    return True

            logger.info(f"NSE session not found for {today}")

            return False

        except Exception as ex:

            logger.exception(f"Failed checking market open today: {ex}")

            return False
