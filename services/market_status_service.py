from datetime import datetime

import upstox_client
from upstox_client.rest import ApiException
from zoneinfo import ZoneInfo

from core.logger import get_logger

logger = get_logger(__name__)


class MarketStatusService:

    _status_cache = {}

    @classmethod
    def get_market_status(cls, date_str: str):

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

    @classmethod
    def is_market_open_today(cls):

        try:

            today = (
                datetime.now(
                    ZoneInfo("Asia/Kolkata")
                ).date().isoformat()
            )

            response = cls.get_market_status(today)

            if not response:
                return False

            for exchange in response.data:

                if exchange.exchange == "NSE":

                    logger.info(
                        f"NSE Session Found "
                        f"| Start={exchange.start_time} "
                        f"| End={exchange.end_time}"
                    )

                    return True

            logger.info(
                f"NSE session not found for {today}"
            )

            return False

        except Exception as ex:

            logger.exception(
                f"Failed checking market open today: {ex}"
            )

            return False