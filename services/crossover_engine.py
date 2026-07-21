from datetime import datetime

from config.settings import Settings
from core.logger import get_logger
from db.repositories import UpstoxRepository
from indicators.ema import EMAIndicator
from services.preload_service import PreloadService
from services.candle_builder import CandleBuilder
from services.dashboard_state import DashboardState

logger = get_logger(__name__)


class CrossoverEngine:

    @staticmethod
    def get_trading_date(candle_timestamp: str) -> str:
        """
        Extract trading date from candle timestamp.

        Example:
        2026-07-21T09:15:00+05:30
        ->
        2026-07-21
        """

        try:
            return datetime.fromisoformat(candle_timestamp).date().isoformat()

        except Exception as ex:
            logger.exception(f"Failed extracting trading date: {ex}")

            DashboardState.update_scheduler_status(
                "CANDLE_TRADING_DATE_EXTRACTION_FAILED"
            )

            raise

    @classmethod
    def process_completed_candle(cls, instrument_key: str, candle: dict):
        """
        Process one completed 1-minute candle.

        New compact Mongo save behavior:

        MongoDB will save only:

        daily.<date>.status
        daily.<date>.total_crosses
        daily.<date>.crosses
        last_updated
        last_updated_date

        MongoDB will NOT save:

        candles
        today_candles
        ema_short
        ema_long
        last_price
        candle_timestamp
        latest_crosses
        crosses_today

        Runtime and dashboard still keep EMA values in memory.
        """

        try:
            state = PreloadService.get_runtime_by_key(instrument_key)

            if not state:
                logger.warning(f"Runtime state not found for {instrument_key}")

                DashboardState.update_scheduler_status(
                    "RUNTIME_STATE_NOT_FOUND_FOR_CANDLE"
                )

                return

            # --------------------------------------------------
            # Validate candle
            # --------------------------------------------------
            if not candle:
                logger.warning(f"Empty candle received | {instrument_key}")
                return

            if "close" not in candle or "timestamp" not in candle:
                logger.warning(
                    f"Invalid candle received | {instrument_key} | {candle}"
                )
                return

            close_price = float(candle["close"])

            prev_ema_short = float(state.ema_short)
            prev_ema_long = float(state.ema_long)
            prev_relation = state.relation

            # --------------------------------------------------
            # EMA Calculation
            # --------------------------------------------------
            ema_short = EMAIndicator.calculate_live_ema(
                current_price=close_price,
                previous_ema=prev_ema_short,
                period=Settings.EMA_SHORT_PERIOD,
            )

            ema_long = EMAIndicator.calculate_live_ema(
                current_price=close_price,
                previous_ema=prev_ema_long,
                period=Settings.EMA_LONG_PERIOD,
            )

            # --------------------------------------------------
            # Crossover Detection
            # --------------------------------------------------
            signal, relation = EMAIndicator.detect_crossover(
                previous_relation=prev_relation,
                ema_short=ema_short,
                ema_long=ema_long,
            )

            trading_date = cls.get_trading_date(candle["timestamp"])

            # --------------------------------------------------
            # IMPORTANT:
            # Candle storage removed for compact Mongo format.
            #
            # Old behavior:
            # - saved root candles
            # - saved daily.<date>.today_candles
            #
            # New behavior:
            # - do not save candle data to MongoDB
            # --------------------------------------------------

            # --------------------------------------------------
            # Update Runtime EMA State
            # --------------------------------------------------
            state.update_ema(
                ema_short=ema_short,
                ema_long=ema_long,
                last_close=close_price,
                relation=relation,
            )

            # --------------------------------------------------
            # Signal Status
            #
            # If crossover happened:
            #   BULLISH / BEARISH
            #
            # If no crossover on this candle:
            #   NO_CROSSOVER
            #
            # This value is saved to:
            # daily.<date>.status
            # --------------------------------------------------
            signal_status = signal if signal else "NO_CROSSOVER"

            # --------------------------------------------------
            # Update Compact Daily Status in Mongo
            #
            # Repository will save only:
            # daily.<date>.status
            # last_updated
            # last_updated_date
            #
            # ema_short, ema_long, last_price, candle_timestamp
            # are passed only for method compatibility.
            # Repository will ignore them.
            # --------------------------------------------------
            UpstoxRepository.update_live_ema_status(
                instrument_key=instrument_key,
                trading_date=trading_date,
                signal_status=signal_status,
                ema_short=ema_short,
                ema_long=ema_long,
                last_price=close_price,
                candle_timestamp=candle["timestamp"],
            )

            # --------------------------------------------------
            # Update Dashboard EMA State
            #
            # Dashboard still needs EMA values, relation,
            # last close, and candle time.
            # These are kept in memory only.
            # --------------------------------------------------
            DashboardState.update_ema_state(
                instrument_key=instrument_key,
                ema_short=ema_short,
                ema_long=ema_long,
                last_close=close_price,
                relation=relation,
                signal_status=signal_status,
                candle_timestamp=candle["timestamp"],
            )

            DashboardState.update_active_candle_count(
                CandleBuilder.get_total_active_candles()
            )

            # --------------------------------------------------
            # Save Crossover If Detected
            #
            # Internal crossover object includes EMA values because
            # dashboard latest_crossovers uses them.
            #
            # Repository will store only compact Mongo format:
            #
            # {
            #   "timestamp": "...",
            #   "signal": "BULLISH",
            #   "price": 121.40
            # }
            # --------------------------------------------------
            if signal and Settings.STORE_CROSSES:

                crossover = {
                    "timestamp": candle["timestamp"],
                    "signal": signal,
                    "ema_short": ema_short,
                    "ema_long": ema_long,
                    "price": close_price,
                }

                strike_val = getattr(state, "strike", "UNKNOWN")
                trading_symbol = getattr(state, "trading_symbol", "")

                UpstoxRepository.save_live_crossover_by_date(
                    instrument_key=instrument_key,
                    trading_date=trading_date,
                    strike=strike_val,
                    crossover_data=crossover,
                )

                # --------------------------------------------------
                # Dashboard Latest Crossover Update
                # --------------------------------------------------
                DashboardState.add_crossover(
                    instrument_key=instrument_key,
                    trading_date=trading_date,
                    crossover_data=crossover,
                    strike=strike_val,
                    trading_symbol=trading_symbol,
                )

                DashboardState.update_scheduler_status(f"{signal}_CROSSOVER_DETECTED")

                logger.info(
                    f"{signal} CROSS | "
                    f"{instrument_key} | "
                    f"Price={close_price:.2f} | "
                    f"EMA9={ema_short:.2f} | "
                    f"EMA21={ema_long:.2f}"
                )

            # --------------------------------------------------
            # Update root last_updated only
            # --------------------------------------------------
            UpstoxRepository.update_last_updated(instrument_key)

        except Exception as ex:
            logger.exception(f"Failed processing candle {instrument_key}: {ex}")

            DashboardState.update_scheduler_status("CANDLE_PROCESSING_FAILED")

    @classmethod
    def process_batch(cls, closed_candles: list):
        """
        Process multiple completed candles.

        closed_candles format:

        [
            (instrument_key, candle),
            (instrument_key, candle)
        ]
        """

        try:
            if not closed_candles:
                return

            processed = 0

            for instrument_key, candle in closed_candles:

                try:
                    cls.process_completed_candle(
                        instrument_key=instrument_key,
                        candle=candle,
                    )

                    processed += 1

                except Exception as ex:
                    logger.exception(f"Batch failed {instrument_key}: {ex}")

                    DashboardState.update_scheduler_status("CANDLE_BATCH_ITEM_FAILED")

            logger.info(f"Processed candles: {processed}")

            DashboardState.update_scheduler_status(
                f"CANDLE_BATCH_PROCESSED_{processed}"
            )

            DashboardState.update_active_candle_count(
                CandleBuilder.get_total_active_candles()
            )

        except Exception as ex:
            logger.exception(f"Batch processing failed: {ex}")

            DashboardState.update_scheduler_status("CANDLE_BATCH_PROCESSING_FAILED")

    @classmethod
    def flush_pending_candles(cls):
        """
        Flush all currently active candles.

        Used during:
        - websocket shutdown
        - market close cleanup
        - application shutdown

        This still processes the final candle for EMA/crossover detection,
        but does not store candle data in MongoDB.
        """

        try:
            active = CandleBuilder.get_all_active_candles()

            logger.info(f"Flushing {len(active)} active candles.")

            DashboardState.update_scheduler_status(
                f"FLUSHING_{len(active)}_ACTIVE_CANDLES"
            )

            for instrument_key in list(active.keys()):

                try:
                    candle = CandleBuilder.force_close_candle(instrument_key)

                    if candle:
                        cls.process_completed_candle(
                            instrument_key=instrument_key,
                            candle=candle,
                        )

                except Exception as ex:
                    logger.exception(f"Flush failed {instrument_key}: {ex}")

                    DashboardState.update_scheduler_status(
                        "ACTIVE_CANDLE_FLUSH_ITEM_FAILED"
                    )

            DashboardState.update_active_candle_count(
                CandleBuilder.get_total_active_candles()
            )

            DashboardState.update_scheduler_status("ACTIVE_CANDLE_FLUSH_COMPLETED")

        except Exception as ex:
            logger.exception(f"Flush pending candles failed: {ex}")

            DashboardState.update_scheduler_status("ACTIVE_CANDLE_FLUSH_FAILED")

    @classmethod
    def get_signal_summary(cls, instrument_key: str):
        """
        Get runtime signal summary for one instrument.

        This reads from in-memory PreloadService.RUNTIME_STATE.
        """

        try:
            state = PreloadService.get_runtime_by_key(instrument_key)

            if not state:
                return None

            return {
                "instrument_key": state.instrument_key,
                "strike": state.strike,
                "option_type": state.option_type,
                "trading_symbol": state.trading_symbol,
                "ema_short": state.ema_short,
                "ema_long": state.ema_long,
                "last_close": state.last_close,
                "relation": state.relation,
                "is_bullish": state.is_bullish,
                "is_bearish": state.is_bearish,
            }

        except Exception as ex:
            logger.exception(f"Signal summary failed {instrument_key}: {ex}")

            DashboardState.update_scheduler_status("SIGNAL_SUMMARY_FAILED")

            return None

    @classmethod
    def print_runtime_stats(cls):
        """
        Print runtime EMA engine stats.
        """

        try:
            runtime = PreloadService.get_runtime_state()

            total = len(runtime)
            bullish = 0
            bearish = 0

            for state in runtime.values():

                if state.is_bullish:
                    bullish += 1

                if state.is_bearish:
                    bearish += 1

            logger.info("=" * 60)
            logger.info("EMA ENGINE STATS")
            logger.info(f"Total Instruments : {total}")
            logger.info(f"Bullish Trend     : {bullish}")
            logger.info(f"Bearish Trend     : {bearish}")
            logger.info("=" * 60)

            DashboardState.update_active_candle_count(
                CandleBuilder.get_total_active_candles()
            )

        except Exception as ex:
            logger.exception(f"Runtime stats failed: {ex}")

            DashboardState.update_scheduler_status("RUNTIME_STATS_FAILED")