from __future__ import annotations

import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from pykrx import stock

INVESTOR_COLUMN_CANDIDATES = {
    "foreign": ["외국인합계", "외국인", "외국인투자자"],
    "institution": ["기관합계", "기관", "기관투자자"],
}


# pykrx internally uses pandas.replace in a way that emits a FutureWarning in recent pandas.
warnings.filterwarnings(
    "ignore",
    message="Downcasting behavior in `replace` is deprecated",
    category=FutureWarning,
)


@dataclass
class ForeignFlowSummary:
    unit: str
    window_trading_days: int
    buy_sum: float | None
    sell_sum: float | None
    net_sum: float
    streak_net_buy_days: int


@dataclass
class RankedForeignFlowItem:
    ticker: str
    name: str
    close: float
    close_change: float
    net_sum: float
    recent_daily_nets: list[float]


class StockDataClient:
    def __init__(self, timezone: str, rate_limit_sec: float = 0.0):
        self.tz = ZoneInfo(timezone)
        self.rate_limit_sec = rate_limit_sec

    def _today_str(self) -> str:
        return datetime.now(self.tz).strftime("%Y%m%d")

    def _start_date_str(self, lookback_days: int) -> str:
        start = datetime.now(self.tz) - timedelta(days=lookback_days)
        return start.strftime("%Y%m%d")

    def _sleep(self) -> None:
        if self.rate_limit_sec > 0:
            time.sleep(self.rate_limit_sec)

    @staticmethod
    def _pick_investor_column(df: pd.DataFrame, investor: str) -> str:
        candidates = INVESTOR_COLUMN_CANDIDATES.get(investor)
        if not candidates:
            raise ValueError(f"Unsupported investor type: {investor}")
        for col in candidates:
            if col in df.columns:
                return col
        raise KeyError(
            f"No investor column found for investor={investor} in dataframe columns: {list(df.columns)}"
        )

    def get_ohlcv(self, ticker: str, calendar_lookback_days: int) -> pd.DataFrame:
        df = stock.get_market_ohlcv(
            self._start_date_str(calendar_lookback_days),
            self._today_str(),
            ticker,
        )
        self._sleep()
        if df.empty:
            raise ValueError(f"Empty OHLCV dataframe for ticker={ticker}")
        return df

    def _get_flow_df(
        self,
        ticker: str,
        calendar_lookback_days: int,
        unit: str,
        on: str | None = None,
    ) -> pd.DataFrame:
        start = self._start_date_str(calendar_lookback_days)
        end = self._today_str()
        if unit == "value":
            df = stock.get_market_trading_value_by_date(start, end, ticker, on=on)
        elif unit == "volume":
            df = stock.get_market_trading_volume_by_date(start, end, ticker, on=on)
        else:
            raise ValueError(f"Unsupported unit: {unit}. Use 'value' or 'volume'.")
        self._sleep()
        return df

    def _retry_empty_df(
        self,
        ticker: str,
        calendar_lookback_days: int,
        unit: str,
        on: str | None = None,
        retries: int = 2,
    ) -> pd.DataFrame:
        last_df = pd.DataFrame()
        for attempt in range(retries + 1):
            last_df = self._get_flow_df(ticker, calendar_lookback_days, unit=unit, on=on)
            if not last_df.empty:
                return last_df
            if attempt < retries:
                time.sleep(max(1.0, self.rate_limit_sec))
        return last_df

    def summarize_foreign_flow(
        self,
        ticker: str,
        unit: str,
        calendar_lookback_days: int,
        window_trading_days: int,
        include_buy_sell: bool,
    ) -> ForeignFlowSummary:
        net_df = self._retry_empty_df(ticker, calendar_lookback_days, unit=unit)
        if net_df.empty:
            raise ValueError(f"Empty foreign flow dataframe for ticker={ticker}, unit={unit}")

        foreign_col = self._pick_investor_column(net_df, investor="foreign")
        net_series = net_df[foreign_col].tail(window_trading_days)
        net_sum = float(net_series.sum())

        streak = 0
        for value in reversed(net_series.tolist()):
            if value > 0:
                streak += 1
            else:
                break

        buy_sum = None
        sell_sum = None
        if include_buy_sell:
            buy_df = self._retry_empty_df(ticker, calendar_lookback_days, unit=unit, on="매수")
            sell_df = self._retry_empty_df(ticker, calendar_lookback_days, unit=unit, on="매도")
            if not buy_df.empty and not sell_df.empty:
                buy_col = self._pick_investor_column(buy_df, investor="foreign")
                sell_col = self._pick_investor_column(sell_df, investor="foreign")
                buy_sum = float(buy_df[buy_col].tail(window_trading_days).sum())
                sell_sum = float(sell_df[sell_col].tail(window_trading_days).sum())

        return ForeignFlowSummary(
            unit=unit,
            window_trading_days=window_trading_days,
            buy_sum=buy_sum,
            sell_sum=sell_sum,
            net_sum=net_sum,
            streak_net_buy_days=streak,
        )

    def get_kospi_top_tickers(self, top_n: int) -> list[str]:
        market_cap = stock.get_market_cap_by_ticker(self._today_str(), market="KOSPI")
        self._sleep()
        if market_cap.empty:
            raise ValueError("Empty market cap dataframe for KOSPI")
        ranked = market_cap.sort_values(by="시가총액", ascending=False).head(top_n)
        return ranked.index.tolist()

    def get_latest_close_and_change(
        self,
        ticker: str,
        calendar_lookback_days: int = 20,
    ) -> tuple[float, float]:
        ohlcv = self.get_ohlcv(ticker=ticker, calendar_lookback_days=calendar_lookback_days)
        close = float(ohlcv.iloc[-1]["종가"])
        if len(ohlcv) < 2:
            return close, 0.0
        prev_close = float(ohlcv.iloc[-2]["종가"])
        return close, close - prev_close

    def summarize_investor_net(
        self,
        ticker: str,
        unit: str,
        calendar_lookback_days: int,
        window_trading_days: int,
        investor: str,
    ) -> float:
        net_df = self._retry_empty_df(ticker, calendar_lookback_days, unit=unit)
        if net_df.empty:
            return 0.0
        col = self._pick_investor_column(net_df, investor=investor)
        return float(net_df[col].tail(window_trading_days).sum())

    def summarize_recent_daily_investor_net(
        self,
        ticker: str,
        unit: str,
        calendar_lookback_days: int,
        recent_days: int,
        investor: str,
    ) -> list[float]:
        net_df = self._retry_empty_df(ticker, calendar_lookback_days, unit=unit)
        if net_df.empty:
            return []
        col = self._pick_investor_column(net_df, investor=investor)
        return [float(value) for value in net_df[col].tail(recent_days).tolist()]

    def build_kospi_flow_ranking(
        self,
        top_n: int,
        unit: str,
        calendar_lookback_days: int,
        window_trading_days: int,
        investor: str,
        universe_top_n: int | None = None,
        recent_days: int = 5,
    ) -> list[RankedForeignFlowItem]:
        universe_size = universe_top_n if universe_top_n is not None else top_n
        tickers = self.get_kospi_top_tickers(universe_size)
        ranking: list[RankedForeignFlowItem] = []

        for ticker in tickers:
            name = stock.get_market_ticker_name(ticker)
            close, close_change = self.get_latest_close_and_change(ticker)
            net_sum = self.summarize_investor_net(
                ticker=ticker,
                unit=unit,
                calendar_lookback_days=calendar_lookback_days,
                window_trading_days=window_trading_days,
                investor=investor,
            )
            recent_daily_nets = self.summarize_recent_daily_investor_net(
                ticker=ticker,
                unit=unit,
                calendar_lookback_days=calendar_lookback_days,
                recent_days=recent_days,
                investor=investor,
            )
            ranking.append(
                RankedForeignFlowItem(
                    ticker=ticker,
                    name=name,
                    close=close,
                    close_change=close_change,
                    net_sum=net_sum,
                    recent_daily_nets=recent_daily_nets,
                )
            )

        ranking.sort(key=lambda item: item.net_sum, reverse=True)
        return ranking[:top_n]
