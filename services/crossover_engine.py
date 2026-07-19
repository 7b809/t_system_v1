from datetime import datetime

from config.settings import Settings
from core.logger import get_logger
from db.repositories import UpstoxRepository
from indicators.ema import EMAIndicator
from services.preload_service import PreloadService
from services.candle_builder import CandleBuilder

logger = get_logger(__name__)


class CrossoverEngine:

    @staticmethod
    def get_trading_date(candle_timestamp: str) -> str:
        """
        Extract trading date from candle timestamp.
        """
        try:
            return datetime.fromisoformat(candle_timestamp).date().isoformat()
        except Exception as ex:
            logger.exception(f"Failed extracting trading date: {ex}")
            raise

    @classmethod
    def process_completed_candle(cls, instrument_key: str, candle: dict):
        """
        Process a completed 1-minute candle.
        """
        try:
            state = PreloadService.get_runtime_by_key(instrument_key)

            if not state:
                logger.warning(f"Runtime state not found for {instrument_key}")
                return

            close_price = float(candle["close"])
            prev_ema_short = float(state.ema_short)
            prev_ema_long = float(state.ema_long)
            prev_relation = state.relation

            # ----------------------------------
            # EMA Calculation
            # ----------------------------------
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

            # ----------------------------------
            # Crossover Detection
            # ----------------------------------
            signal, relation = EMAIndicator.detect_crossover(
                previous_relation=prev_relation, ema_short=ema_short, ema_long=ema_long
            )

            trading_date = cls.get_trading_date(candle["timestamp"])

            # ----------------------------------
            # Save Candle
            # ----------------------------------
            if Settings.STORE_MASTER_CANDLES:
                UpstoxRepository.append_candle(
                    instrument_key=instrument_key,
                    candle=candle,
                    trading_date=trading_date,
                )

            # ----------------------------------
            # Update Runtime
            # ----------------------------------
            state.update_ema(
                ema_short=ema_short,
                ema_long=ema_long,
                last_close=close_price,
                relation=relation,
            )

            # ----------------------------------
            # Signal Status
            # ----------------------------------
            signal_status = signal if signal else "NO_CROSSOVER"

            # ----------------------------------
            # Update Daily Status
            # ----------------------------------
            UpstoxRepository.update_live_ema_status(
                instrument_key=instrument_key,
                trading_date=trading_date,
                signal_status=signal_status,
                ema_short=ema_short,
                ema_long=ema_long,
                last_price=close_price,
                candle_timestamp=candle["timestamp"],
            )

            # ----------------------------------
            # Save Crossover
            # ----------------------------------
            if signal and Settings.STORE_CROSSES:
                # MODIFIED: Map crossover keys exactly to match database snapshot schema requirements
                crossover = {
                    "timestamp": candle["timestamp"],
                    "signal": signal,
                    "ema_short": ema_short,
                    "ema_long": ema_long,
                    "price": close_price,
                }

                # Retrieve strike string format from memory state safely
                strike_val = getattr(state, "strike", "UNKNOWN")

                # Triggers the updated dual-push logic into history and root latest_crosses array
                UpstoxRepository.save_live_crossover_by_date(
                    instrument_key=instrument_key,
                    trading_date=trading_date,
                    strike=strike_val,
                    crossover_data=crossover,
                )

                logger.info(
                    f"{signal} CROSS | "
                    f"{instrument_key} | "
                    f"Price={close_price:.2f} | "
                    f"EMA9={ema_short:.2f} | "
                    f"EMA21={ema_long:.2f}"
                )

            UpstoxRepository.update_last_updated(instrument_key)

        except Exception as ex:
            logger.exception(f"Failed processing candle {instrument_key}: {ex}")

    @classmethod
    def process_batch(cls, closed_candles: list):
        """
        Process multiple candles.
        """
        try:
            if not closed_candles:
                return

            processed = 0
            for instrument_key, candle in closed_candles:
                try:
                    cls.process_completed_candle(instrument_key, candle)
                    processed += 1
                except Exception as ex:
                    logger.exception(f"Batch failed {instrument_key}: {ex}")

            logger.info(f"Processed candles: {processed}")
        except Exception as ex:
            logger.exception(f"Batch processing failed: {ex}")

    @classmethod
    def flush_pending_candles(cls):
        """
        Flush all active candles before websocket shutdown.
        """
        try:
            active = CandleBuilder.get_all_active_candles()
            logger.info(f"Flushing {len(active)} active candles.")

            for instrument_key in list(active.keys()):
                try:
                    candle = CandleBuilder.force_close_candle(instrument_key)
                    if candle:
                        cls.process_completed_candle(instrument_key, candle)
                except Exception as ex:
                    logger.exception(f"Flush failed {instrument_key}: {ex}")
        except Exception as ex:
            logger.exception(f"Flush pending candles failed: {ex}")

    @classmethod
    def get_signal_summary(cls, instrument_key: str):
        """
        Get runtime signal summary.
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
            return None

    @classmethod
    def print_runtime_stats(cls):
        """
        Runtime monitoring stats.
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
        except Exception as ex:
            logger.exception(f"Runtime stats failed: {ex}")
