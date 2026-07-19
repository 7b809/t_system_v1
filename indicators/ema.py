import pandas as pd

from core.logger import get_logger

logger = get_logger(__name__)


class EMAIndicator:

    @staticmethod
    def calculate_historical_ema(
        candles: list, short_period: int = 9, long_period: int = 21
    ) -> pd.DataFrame:
        """
        Calculate historical EMA values
        using all available candles.

        Returns dataframe containing:
        ema_short
        ema_long
        """

        try:

            if not candles:
                raise ValueError("No candles available for EMA calculation.")

            df = pd.DataFrame(candles)

            if "close" not in df.columns:
                raise ValueError("'close' column missing in candle data.")

            df["ema_short"] = df["close"].ewm(span=short_period, adjust=False).mean()

            df["ema_long"] = df["close"].ewm(span=long_period, adjust=False).mean()

            logger.info(
                f"Historical EMA calculated "
                f"| Candles={len(df)} "
                f"| EMA{short_period}/{long_period}"
            )

            return df

        except Exception as ex:

            logger.exception(f"Failed historical EMA calculation: {ex}")

            raise

    @staticmethod
    def calculate_live_ema(
        current_price: float, previous_ema: float, period: int
    ) -> float:
        """
        Incremental EMA calculation.

        Formula:

        EMA =
        (Price × Multiplier) +
        (Previous EMA × (1 - Multiplier))
        """

        try:

            multiplier = 2 / (period + 1)

            new_ema = (current_price * multiplier) + (previous_ema * (1 - multiplier))

            return round(new_ema, 6)

        except Exception as ex:

            logger.exception(f"Failed live EMA calculation: {ex}")

            raise

    @staticmethod
    def get_latest_state(
        candles: list, short_period: int = 9, long_period: int = 21
    ) -> dict:
        """
        Build runtime EMA state from
        historical candles.

        Returns:

        {
            ema_short,
            ema_long,
            relation,
            last_close
        }
        """

        try:

            df = EMAIndicator.calculate_historical_ema(
                candles, short_period, long_period
            )

            latest = df.iloc[-1]

            ema_short = float(latest["ema_short"])

            ema_long = float(latest["ema_long"])

            last_close = float(latest["close"])

            relation = "ABOVE" if ema_short > ema_long else "BELOW"

            state = {
                "ema_short": ema_short,
                "ema_long": ema_long,
                "last_close": last_close,
                "relation": relation,
            }

            logger.info(
                f"Latest EMA state built "
                f"| EMA9={ema_short:.2f} "
                f"| EMA21={ema_long:.2f} "
                f"| Relation={relation}"
            )

            return state

        except Exception as ex:

            logger.exception(f"Failed to build EMA state: {ex}")

            raise

    @staticmethod
    def detect_crossover(previous_relation: str, ema_short: float, ema_long: float):
        """
        Detect crossover.

        Returns:

        BULLISH
        BEARISH
        None
        """

        try:

            current_relation = "ABOVE" if ema_short > ema_long else "BELOW"

            signal = None

            if previous_relation == "BELOW" and current_relation == "ABOVE":
                signal = "BULLISH"

            elif previous_relation == "ABOVE" and current_relation == "BELOW":
                signal = "BEARISH"

            if signal:

                logger.info(
                    f"{signal} crossover detected "
                    f"| EMA9={ema_short:.2f} "
                    f"| EMA21={ema_long:.2f}"
                )

            return signal, current_relation

        except Exception as ex:

            logger.exception(f"Failed crossover detection: {ex}")

            raise

    @staticmethod
    def extract_crossovers(candles: list, short_period: int = 9, long_period: int = 21):
        """
        Extract all historical crossovers.

        Returns:

        [
            {
                timestamp,
                signal,
                short_ema,
                long_ema,
                price
            }
        ]
        """

        try:

            df = EMAIndicator.calculate_historical_ema(
                candles, short_period, long_period
            )

            crossovers = []

            for i in range(1, len(df)):

                prev_short = df.iloc[i - 1]["ema_short"]
                prev_long = df.iloc[i - 1]["ema_long"]

                curr_short = df.iloc[i]["ema_short"]
                curr_long = df.iloc[i]["ema_long"]

                signal = None

                if prev_short < prev_long and curr_short > curr_long:
                    signal = "BULLISH"

                elif prev_short > prev_long and curr_short < curr_long:
                    signal = "BEARISH"

                if signal:

                    crossovers.append(
                        {
                            "timestamp": df.iloc[i]["timestamp"],
                            "signal": signal,
                            "short_ema": round(float(curr_short), 6),
                            "long_ema": round(float(curr_long), 6),
                            "price": float(df.iloc[i]["close"]),
                        }
                    )

            logger.info(
                f"Historical crossover scan " f"completed | Found={len(crossovers)}"
            )

            return crossovers

        except Exception as ex:

            logger.exception(f"Failed extracting historical " f"crossovers: {ex}")

            raise
