# services/ema_calculator.py

from typing import List, Dict, Any, Tuple, Optional
import pandas as pd
from core.config import settings
from core.logger import get_logger

logger = get_logger("ema_calculator")


class EMACalculator:
    """
    Utility class for calculating Short/Long EMAs and detecting crossovers
    from intraday candle data.
    """

    @staticmethod
    def calculate_ema_crosses(
        candles: List[List[Any]],
        short_period: int = settings.EMA_SHORT_PERIOD,
        long_period: int = settings.EMA_LONG_PERIOD,
    ) -> List[Dict[str, Any]]:
        """
        Calculates Short EMA and Long EMA from raw intraday candle arrays
        and returns all crossover events.

        Upstox Candle Format:
        [timestamp, open, high, low, close, volume, open_interest]

        Args:
            candles (List[List[Any]]): List of raw candle arrays from Upstox.
            short_period (int): Period for Short EMA (default: 9).
            long_period (int): Period for Long EMA (default: 21).

        Returns:
            List[Dict[str, Any]]: List of crossover events with timestamp, signal, and price.
        """
        if not candles or len(candles) < long_period:
            return []

        try:
            # 1. Load into DataFrame
            df = pd.DataFrame(
                candles,
                columns=["timestamp", "open", "high", "low", "close", "volume", "oi"],
            )

            # 2. Convert close to numeric and ensure chronological order (Oldest -> Newest)
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["timestamp"] = pd.to_datetime(df["timestamp"])

            # Upstox returns newest candles first, so we reverse it for EMA calculation
            df = df.sort_values(by="timestamp", ascending=True).reset_index(drop=True)

            # 3. Calculate EMAs
            df["short_ema"] = df["close"].ewm(span=short_period, adjust=False).mean()
            df["long_ema"] = df["close"].ewm(span=long_period, adjust=False).mean()

            # 4. Shift previous values to detect crossover points
            df["prev_short"] = df["short_ema"].shift(1)
            df["prev_long"] = df["long_ema"].shift(1)

            # Drop initial rows where shift or calculation is invalid
            df = df.dropna(subset=["prev_short", "prev_long"])

            crosses: List[Dict[str, Any]] = []

            # 5. Detect Crossovers
            for _, row in df.iterrows():
                prev_short = row["prev_short"]
                prev_long = row["prev_long"]
                curr_short = row["short_ema"]
                curr_long = row["long_ema"]

                # BULLISH Cross: Short EMA crosses above Long EMA
                if prev_short <= prev_long and curr_short > curr_long:
                    crosses.append(
                        {
                            "timestamp": row["timestamp"].isoformat(),
                            "signal": "BULLISH",
                            "price": float(row["close"]),
                            "short_ema": float(curr_short),
                            "long_ema": float(curr_long),
                        }
                    )

                # BEARISH Cross: Short EMA crosses below Long EMA
                elif prev_short >= prev_long and curr_short < curr_long:
                    crosses.append(
                        {
                            "timestamp": row["timestamp"].isoformat(),
                            "signal": "BEARISH",
                            "price": float(row["close"]),
                            "short_ema": float(curr_short),
                            "long_ema": float(curr_long),
                        }
                    )

            return crosses

        except Exception as e:
            logger.error(f"Error calculating EMA crosses: {e}")
            return []


# Module level instance export
ema_calculator = EMACalculator()
