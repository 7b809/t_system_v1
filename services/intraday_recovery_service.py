from datetime import datetime
from zoneinfo import ZoneInfo

import upstox_client
from upstox_client.rest import ApiException

from config.settings import Settings
from core.logger import get_logger
from db.repositories import UpstoxRepository
from indicators.ema import EMAIndicator
from core.datetime_utils import now

logger = get_logger(__name__)


class IntradayRecoveryService:
    """
    Rebuilds runtime EMA state using today's intraday candles from Upstox.

    Used when application starts or restarts during market hours.

    New compact MongoDB behavior:

    MongoDB saves only:

    daily.<date>.status
    daily.<date>.total_crosses
    daily.<date>.crosses
    last_updated
    last_updated_date

    MongoDB does NOT save:

    candles
    today_candles
    ema_short
    ema_long
    last_price
    candle_timestamp
    latest_crosses
    crosses_today

    Important:
    Intraday candle fetching uses Upstox HistoryApi directly.
    Access token is not required here.

    Access token is required only for live market feed subscription
    through Upstox MarketDataStreamerV3.
    """

    API_VERSION = Settings.API_VERSION

    @classmethod
    def _build_history_api(cls):
        """
        Create Upstox History API instance.

        Intraday candle data can be fetched using HistoryApi()
        without passing access token.
        """

        return upstox_client.HistoryApi()

    @staticmethod
    def _parse_timestamp(timestamp: str):
        """
        Parse ISO timestamp safely.

        Handles:
        - 2026-07-20T09:15:00+05:30
        - 2026-07-20T03:45:00Z
        """

        return datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))

    @classmethod
    def _extract_candles_from_response(cls, response):
        """
        Convert Upstox intraday candle response into candle dictionary format.

        Output:

        [
            {
                "timestamp": "2026-07-21T09:15:00+05:30",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1200
            }
        ]
        """

        candles = []

        try:
            data = getattr(response, "data", None)

            if not data:
                return candles

            raw_candles = getattr(data, "candles", None)

            if not raw_candles:
                return candles

            for row in raw_candles:
                try:
                    candles.append(
                        {
                            "timestamp": str(row[0]),
                            "open": float(row[1]),
                            "high": float(row[2]),
                            "low": float(row[3]),
                            "close": float(row[4]),
                            "volume": int(row[5]),
                        }
                    )

                except Exception as row_ex:
                    logger.warning(
                        f"Skipping invalid intraday candle row: {row} | {row_ex}"
                    )

            candles.sort(key=lambda candle: cls._parse_timestamp(candle["timestamp"]))

            return candles

        except Exception as ex:
            logger.exception(f"Failed extracting candle response: {ex}")
            return []

    @classmethod
    def fetch_intraday_candles(
        cls,
        instrument_key: str,
    ):
        """
        Download today's intraday candles from Upstox.

        Access token is not required for this call.
        """

        try:
            api = cls._build_history_api()

            interval = getattr(
                Settings,
                "RECOVERY_INTERVAL",
                Settings.CANDLE_INTERVAL,
            )

            response = api.get_intra_day_candle_data(
                instrument_key=instrument_key,
                interval=interval,
                api_version=cls.API_VERSION,
            )

            candles = cls._extract_candles_from_response(response)

            logger.info(
                f"Fetched intraday candles | "
                f"{instrument_key} | "
                f"Count={len(candles)}"
            )

            return candles

        except ApiException as ex:
            logger.exception(f"Upstox intraday API failed | {instrument_key}: {ex}")
            return []

        except Exception as ex:
            logger.exception(f"Intraday fetch failed | {instrument_key}: {ex}")
            return []

    @classmethod
    def _get_trading_date(cls):
        """
        Current trading date using configured timezone.
        """

        return now().date().isoformat()

    @classmethod
    def _filter_missing_candles(
        cls,
        candles: list,
        last_processed_timestamp: str | None,
    ):
        """
        Keep only candles newer than the last processed candle.

        In compact Mongo format, candle_timestamp is not persisted.
        So repository currently returns None and this method replays all
        available intraday candles.

        If later you add root runtime.last_candle_timestamp, this method
        can again replay only missing candles.
        """

        try:
            if not candles:
                return []

            if not last_processed_timestamp:
                return candles

            last_processed_dt = cls._parse_timestamp(last_processed_timestamp)

            missing_candles = [
                candle
                for candle in candles
                if cls._parse_timestamp(candle["timestamp"]) > last_processed_dt
            ]

            return missing_candles

        except Exception as ex:
            logger.exception(f"Failed filtering missing candles: {ex}")
            return candles

    @classmethod
    def recover_single_instrument(
        cls,
        strike_doc: dict,
        base_state: dict,
    ):
        """
        Recover EMA state for one instrument.

        Compact recovery flow:

        1. Start from base runtime EMA state.
        2. Fetch today's intraday candles from Upstox HistoryApi.
        3. Since compact Mongo does not store candle_timestamp, replay all
           available intraday candles unless repository later provides a timestamp.
        4. Recalculate EMA9 and EMA21 in memory.
        5. Detect recovered crossovers.
        6. Persist only compact crossover data to MongoDB.
        7. Return latest EMA state for runtime memory.

        MongoDB will only persist:

        daily.<date>.status
        daily.<date>.total_crosses
        daily.<date>.crosses
        last_updated
        last_updated_date

        Access token is not required for intraday candle recovery.
        """

        try:
            instrument_key = strike_doc.get("instrument_key")

            if not instrument_key:
                logger.warning("Skipping recovery because instrument_key is missing.")
                return None

            trading_date = cls._get_trading_date()

            # --------------------------------------------------
            # Ensure compact daily document exists
            # --------------------------------------------------
            UpstoxRepository.ensure_daily_document(
                instrument_key=instrument_key,
                trading_date=trading_date,
            )

            # --------------------------------------------------
            # Fetch today's intraday candles
            # --------------------------------------------------
            candles = cls.fetch_intraday_candles(
                instrument_key=instrument_key,
            )

            if not candles:
                logger.warning(f"No intraday candles available for {instrument_key}")
                return None

            # --------------------------------------------------
            # Compact Mongo currently does not save candle_timestamp.
            # Repository returns None, so this replays all candles.
            # --------------------------------------------------
            last_processed_timestamp = UpstoxRepository.get_last_processed_timestamp(
                instrument_key=instrument_key,
                trading_date=trading_date,
            )

            missing_candles = cls._filter_missing_candles(
                candles=candles,
                last_processed_timestamp=last_processed_timestamp,
            )

            if not missing_candles:
                logger.info(
                    f"No missing candles for recovery | "
                    f"{instrument_key} | "
                    f"LastProcessed={last_processed_timestamp}"
                )

                return {
                    "instrument_key": instrument_key,
                    "ema_state": {
                        "ema_short": float(base_state.get("ema_short", 0.0)),
                        "ema_long": float(base_state.get("ema_long", 0.0)),
                        "last_close": float(base_state.get("last_close", 0.0)),
                        "relation": base_state.get(
                            "relation",
                            "BELOW",
                        ),
                    },
                    "crossovers": [],
                    "candle_count": 0,
                }

            # --------------------------------------------------
            # Start from base runtime EMA state
            # --------------------------------------------------
            ema_short = float(base_state.get("ema_short", 0.0))
            ema_long = float(base_state.get("ema_long", 0.0))

            relation = base_state.get(
                "relation",
                "BELOW",
            )

            last_close = float(base_state.get("last_close", 0.0))

            recovered_crossovers = []

            # --------------------------------------------------
            # Replay intraday candles and detect recovered crosses
            # --------------------------------------------------
            for candle in missing_candles:
                try:
                    close_price = float(candle["close"])

                    ema_short = EMAIndicator.calculate_live_ema(
                        current_price=close_price,
                        previous_ema=ema_short,
                        period=Settings.EMA_SHORT_PERIOD,
                    )

                    ema_long = EMAIndicator.calculate_live_ema(
                        current_price=close_price,
                        previous_ema=ema_long,
                        period=Settings.EMA_LONG_PERIOD,
                    )

                    signal, relation = EMAIndicator.detect_crossover(
                        previous_relation=relation,
                        ema_short=ema_short,
                        ema_long=ema_long,
                    )

                    if signal:
                        # Keep EMA values here for logs/runtime/debug.
                        # Repository will store only timestamp, signal, price.
                        recovered_crossovers.append(
                            {
                                "timestamp": candle["timestamp"],
                                "signal": signal,
                                "ema_short": round(
                                    float(ema_short),
                                    6,
                                ),
                                "ema_long": round(
                                    float(ema_long),
                                    6,
                                ),
                                "price": close_price,
                            }
                        )

                    last_close = close_price

                except Exception as candle_ex:
                    logger.exception(
                        f"Replay candle failed | {instrument_key}: {candle_ex}"
                    )

            latest_candle_timestamp = missing_candles[-1]["timestamp"]

            ema_state = {
                "ema_short": round(
                    float(ema_short),
                    6,
                ),
                "ema_long": round(
                    float(ema_long),
                    6,
                ),
                "last_close": float(last_close),
                "relation": relation,
            }

            # --------------------------------------------------
            # Update compact document metadata only.
            # EMA values are not persisted in compact Mongo format.
            # --------------------------------------------------
            UpstoxRepository.update_recovered_ema_state(
                instrument_key=instrument_key,
                trading_date=trading_date,
                ema_short=ema_state["ema_short"],
                ema_long=ema_state["ema_long"],
                last_price=ema_state["last_close"],
                relation=ema_state["relation"],
                candle_timestamp=latest_candle_timestamp,
            )

            # --------------------------------------------------
            # Save recovered crossovers in compact format.
            #
            # Repository stores only:
            # {
            #   "timestamp": "...",
            #   "signal": "BULLISH/BEARISH",
            #   "price": 121.40
            # }
            #
            # Duplicate protection is handled in repository.
            # --------------------------------------------------
            UpstoxRepository.save_recovered_crossovers(
                instrument_key=instrument_key,
                trading_date=trading_date,
                crossovers=recovered_crossovers,
            )

            result = {
                "instrument_key": instrument_key,
                "ema_state": ema_state,
                "crossovers": recovered_crossovers,
                "candle_count": len(missing_candles),
            }

            logger.info(
                f"Recovery complete | "
                f"{instrument_key} | "
                f"FetchedCandles={len(candles)} | "
                f"ReplayedCandles={len(missing_candles)} | "
                f"RecoveredCrosses={len(recovered_crossovers)} | "
                f"EMA9={ema_short:.6f} | "
                f"EMA21={ema_long:.6f} | "
                f"Relation={relation}"
            )

            return result

        except Exception as ex:
            logger.exception(
                f"Instrument recovery failed | "
                f"{strike_doc.get('instrument_key')}: {ex}"
            )

            return None

    @classmethod
    def should_run_recovery(cls):
        """
        Determine whether startup recovery should run.

        Recovery required:
        - ENABLE_INTRADAY_RECOVERY is true
        - Current time is during market hours
        """

        try:
            recovery_enabled = getattr(
                Settings,
                "ENABLE_INTRADAY_RECOVERY",
                True,
            )

            if not recovery_enabled:
                return False

            now = now().time()

            return Settings.MARKET_START_TIME <= now < Settings.MARKET_END_TIME

        except Exception as ex:
            logger.exception(f"Failed checking recovery window: {ex}")
            return False
