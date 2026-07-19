from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class StrikeState:
    """
    Runtime state for a strike instrument.

    Kept in memory after preload and
    continuously updated during live trading.
    """

    instrument_key: str
    strike: str
    option_type: str
    trading_symbol: str

    ema_short: float
    ema_long: float

    last_close: float
    relation: str

    current_candle: Optional[Dict[str, Any]] = field(default=None)

    def update_ema(
        self, ema_short: float, ema_long: float, last_close: float, relation: str
    ):
        """
        Update live EMA state.
        """

        try:

            self.ema_short = ema_short
            self.ema_long = ema_long
            self.last_close = last_close
            self.relation = relation

            logger.debug(
                f"EMA updated | "
                f"{self.instrument_key} | "
                f"EMA9={ema_short:.2f} | "
                f"EMA21={ema_long:.2f}"
            )

        except Exception as ex:

            logger.exception(
                f"Failed updating EMA state " f"{self.instrument_key}: {ex}"
            )

    def update_candle(self, candle: dict):
        """
        Update currently forming candle.
        """

        try:

            self.current_candle = candle

        except Exception as ex:

            logger.exception(f"Failed updating candle " f"{self.instrument_key}: {ex}")

    def clear_candle(self):
        """
        Clear active candle.
        """

        try:

            self.current_candle = None

        except Exception as ex:

            logger.exception(f"Failed clearing candle " f"{self.instrument_key}: {ex}")

    @property
    def is_bullish(self) -> bool:
        """
        EMA9 > EMA21
        """

        try:

            return self.ema_short > self.ema_long

        except Exception:

            return False

    @property
    def is_bearish(self) -> bool:
        """
        EMA9 < EMA21
        """

        try:

            return self.ema_short < self.ema_long

        except Exception:

            return False

    def to_dict(self) -> dict:
        """
        Convert runtime object to dict.
        """

        try:

            return {
                "instrument_key": self.instrument_key,
                "strike": self.strike,
                "option_type": self.option_type,
                "trading_symbol": self.trading_symbol,
                "ema_short": self.ema_short,
                "ema_long": self.ema_long,
                "last_close": self.last_close,
                "relation": self.relation,
                "current_candle": self.current_candle,
            }

        except Exception as ex:

            logger.exception(f"Failed converting state " f"{self.instrument_key}: {ex}")

            return {}

    @classmethod
    def from_preload(cls, doc: dict, ema_state: dict):
        """
        Create StrikeState from
        Mongo document and EMA preload data.
        """

        try:

            return cls(
                instrument_key=doc.get("instrument_key", ""),
                strike=str(doc.get("strike", "")),
                option_type=doc.get("type", ""),
                trading_symbol=doc.get("trading_symbol", ""),
                ema_short=ema_state.get("ema_short", 0.0),
                ema_long=ema_state.get("ema_long", 0.0),
                last_close=ema_state.get("last_close", 0.0),
                relation=ema_state.get("relation", "BELOW"),
            )

        except Exception as ex:

            logger.exception(f"Failed creating " f"StrikeState: {ex}")
            raise

    def __str__(self):
        """
        String representation.
        """

        return (
            f"StrikeState("
            f"{self.instrument_key}, "
            f"{self.strike} "
            f"{self.option_type}, "
            f"EMA9={self.ema_short:.2f}, "
            f"EMA21={self.ema_long:.2f}, "
            f"REL={self.relation})"
        )
