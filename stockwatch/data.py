from __future__ import annotations

import logging
import time
import warnings
from typing import Literal

import requests
from requests.exceptions import JSONDecodeError as RequestsJSONDecodeError
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from pykrx import stock

from stockwatch.krx_auth import (
    LOGIN_FAILURE_CODE,
    LOGIN_SUCCESS_CODE,
    install_pykrx_session_wrappers,
    login_krx,
    mask_credential,
)

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
    def __init__(
        self,
        timezone: str,
        rate_limit_sec: float = 0.0,
        *,
        krx_enable_login: bool = False,
        krx_login_id: str | None = None,
        krx_login_pw: str | None = None,
        krx_login_fail_policy: Literal["continue", "raise"] = "continue",
    ):
        self.tz = ZoneInfo(timezone)
        self.rate_limit_sec = rate_limit_sec
        self._ohlcv_cache: dict[tuple[str, str, str], pd.DataFrame] = {}
        self._flow_cache: dict[tuple[str, str, str, str, str | None], pd.DataFrame] = {}
        self._ticker_name_cache: dict[str, str] = {}
        self._market_cap_cache: dict[tuple[str, str], pd.DataFrame] = {}
        self._session = requests.Session()
        install_pykrx_session_wrappers(self._session)
        self._logger = logging.getLogger(__name__)
        self._krx_enable_login = krx_enable_login
        self._krx_login_fail_policy = krx_login_fail_policy

        if self._krx_enable_login:
            self._configure_krx_login(krx_login_id=krx_login_id, krx_login_pw=krx_login_pw)


    def _configure_krx_login(self, krx_login_id: str | None, krx_login_pw: str | None) -> None:
        if not krx_login_id or not krx_login_pw:
            message = "KRX login enabled but missing credentials. Continue without authentication."
            if self._krx_login_fail_policy == "raise":
                raise RuntimeError(message)
            self._logger.warning(message)
            return

        try:
            result = login_krx(
                self._session,
                krx_login_id,
                krx_login_pw,
                logger=self._logger,
            )
        except Exception as exc:
            message = (
                "KRX login request failed for id=%s: %s"
                % (mask_credential(krx_login_id), exc)
            )
            if self._krx_login_fail_policy == "raise":
                raise RuntimeError(message) from exc
            self._logger.warning("%s; continuing in unauthenticated mode.", message)
            return

        if result.success and result.code == LOGIN_SUCCESS_CODE:
            self._logger.info(
                "KRX login succeeded with code=%s for id=%s",
                result.code,
                mask_credential(krx_login_id),
            )
            return

        if result.code == LOGIN_FAILURE_CODE:
            message = (
                "KRX login failed with code=%s for id=%s: %s"
                % (result.code, mask_credential(krx_login_id), result.message)
            )
        else:
            message = (
                "KRX login did not succeed (code=%s) for id=%s: %s"
                % (result.code, mask_credential(krx_login_id), result.message)
            )

        if self._krx_login_fail_policy == "raise":
            raise RuntimeError(message)
        self._logger.warning("%s; continuing in unauthenticated mode.", message)

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
        start = self._start_date_str(calendar_lookback_days)
        end = self._today_str()
        cache_key = (ticker, start, end)
        cached = self._ohlcv_cache.get(cache_key)
        if cached is not None:
            return cached

        df = stock.get_market_ohlcv(start, end, ticker)
        self._sleep()
        if df.empty:
            raise ValueError(f"Empty OHLCV dataframe for ticker={ticker}")
        self._ohlcv_cache[cache_key] = df
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
        cache_key = (ticker, start, end, unit, on)
        cached = self._flow_cache.get(cache_key)
        if cached is not None:
            return cached

        if unit == "value":
            df = stock.get_market_trading_value_by_date(start, end, ticker, on=on)
        elif unit == "volume":
            df = stock.get_market_trading_volume_by_date(start, end, ticker, on=on)
        else:
            raise ValueError(f"Unsupported unit: {unit}. Use 'value' or 'volume'.")
        self._sleep()
        if not df.empty:
            self._flow_cache[cache_key] = df
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
        last_exception: Exception | None = None
        for attempt in range(retries + 1):
            try:
                last_df = self._get_flow_df(ticker, calendar_lookback_days, unit=unit, on=on)
            except (RequestsJSONDecodeError, requests.RequestException, KeyError) as exc:
                last_exception = exc
                self._logger.warning(
                    "Flow fetch retryable error (ticker=%s, unit=%s, on=%s, attempt=%s/%s): %s: %s",
                    ticker,
                    unit,
                    on,
                    attempt + 1,
                    retries + 1,
                    type(exc).__name__,
                    exc,
                )
                if attempt < retries:
                    time.sleep(max(1.0, self.rate_limit_sec))
                continue
            if not last_df.empty:
                return last_df
            self._logger.info(
                "Flow fetch returned empty dataframe (ticker=%s, unit=%s, on=%s, attempt=%s/%s)",
                ticker,
                unit,
                on,
                attempt + 1,
                retries + 1,
            )
            if attempt < retries:
                time.sleep(max(1.0, self.rate_limit_sec))
        if last_exception is not None:
            raise ValueError(
                "Failed to fetch flow dataframe "
                f"(ticker={ticker}, unit={unit}, on={on}) after {retries + 1} attempts. "
                f"last_exception={type(last_exception).__name__}: {last_exception}"
            ) from last_exception
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
        market = "KOSPI"
        now = datetime.now(self.tz)
        max_fallback_days = 10
        required_cols = {"시가총액"}
        recommended_cols = {"종가", "거래량", "거래대금"}

        last_exception: Exception | None = None
        last_columns: list[str] = []
        attempted_dates: list[str] = []
        market_cap = pd.DataFrame()

        for offset in range(max_fallback_days):
            candidate_date = (now - timedelta(days=offset)).strftime("%Y%m%d")
            attempted_dates.append(candidate_date)
            cache_key = (candidate_date, market)
            market_cap = self._market_cap_cache.get(cache_key, pd.DataFrame())

            if market_cap.empty:
                try:
                    market_cap = stock.get_market_cap_by_ticker(candidate_date, market=market)
                    self._sleep()
                except KeyError as exc:
                    self._logger.warning(
                        "KeyError while fetching market cap (date=%s, market=%s): %s",
                        candidate_date,
                        market,
                        exc,
                    )
                    last_exception = exc
                    continue
                except Exception as exc:  # pragma: no cover - defensive branch
                    last_exception = exc
                    continue

            columns = set(market_cap.columns)
            if market_cap.empty or not required_cols.issubset(columns):
                last_columns = market_cap.columns.tolist()
                continue

            missing_recommended = recommended_cols - columns
            if missing_recommended:
                self._logger.info(
                    "Market cap dataframe missing recommended columns (date=%s, market=%s): %s",
                    candidate_date,
                    market,
                    sorted(missing_recommended),
                )

            self._market_cap_cache[cache_key] = market_cap
            break
        else:
            raise ValueError(
                "Failed to fetch valid KOSPI market cap dataframe "
                f"for last {max_fallback_days} days. "
                f"attempted_dates={attempted_dates}, "
                f"last_exception={last_exception!r}, last_columns={last_columns}"
            )

        ranked = market_cap.sort_values(by="시가총액", ascending=False).head(top_n)
        return ranked.index.tolist()

    def get_ticker_name(self, ticker: str) -> str:
        cached = self._ticker_name_cache.get(ticker)
        if cached is not None:
            return cached
        name = stock.get_market_ticker_name(ticker)
        self._ticker_name_cache[ticker] = name
        return name

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

    @staticmethod
    def _extract_investor_stats(
        net_df: pd.DataFrame,
        investor: str,
        window_trading_days: int,
        recent_days: int,
    ) -> tuple[float, list[float]]:
        if net_df.empty:
            return 0.0, []
        col = StockDataClient._pick_investor_column(net_df, investor=investor)
        series = net_df[col]
        net_sum = float(series.tail(window_trading_days).sum())
        recent_daily_nets = [float(value) for value in series.tail(recent_days).tolist()]
        return net_sum, recent_daily_nets

    def summarize_investor_net(
        self,
        ticker: str,
        unit: str,
        calendar_lookback_days: int,
        window_trading_days: int,
        investor: str,
    ) -> float:
        net_df = self._retry_empty_df(ticker, calendar_lookback_days, unit=unit)
        net_sum, _ = self._extract_investor_stats(
            net_df,
            investor=investor,
            window_trading_days=window_trading_days,
            recent_days=1,
        )
        return net_sum

    def summarize_recent_daily_investor_net(
        self,
        ticker: str,
        unit: str,
        calendar_lookback_days: int,
        recent_days: int,
        investor: str,
    ) -> list[float]:
        net_df = self._retry_empty_df(ticker, calendar_lookback_days, unit=unit)
        _, recent_daily_nets = self._extract_investor_stats(
            net_df,
            investor=investor,
            window_trading_days=1,
            recent_days=recent_days,
        )
        return recent_daily_nets

    def build_kospi_flow_ranking(
        self,
        top_n: int,
        unit: str,
        calendar_lookback_days: int,
        window_trading_days: int,
        investor: str,
        universe_top_n: int | None = None,
        recent_days: int = 5,
        progress_label: str | None = None,
        progress_every: int = 0,
    ) -> list[RankedForeignFlowItem]:
        rankings = self.build_kospi_flow_rankings(
            top_n=top_n,
            unit=unit,
            calendar_lookback_days=calendar_lookback_days,
            window_trading_days=window_trading_days,
            universe_top_n=universe_top_n,
            recent_days=recent_days,
            investors=(investor,),
            progress_label=progress_label,
            progress_every=progress_every,
        )
        return rankings[investor]

    def build_kospi_flow_rankings(
        self,
        top_n: int,
        unit: str,
        calendar_lookback_days: int,
        window_trading_days: int,
        universe_top_n: int | None = None,
        recent_days: int = 5,
        investors: tuple[str, ...] = ("foreign", "institution"),
        progress_label: str | None = None,
        progress_every: int = 0,
    ) -> dict[str, list[RankedForeignFlowItem]]:
        universe_size = universe_top_n if universe_top_n is not None else top_n
        tickers = self.get_kospi_top_tickers(universe_size)
        ranking_map: dict[str, list[RankedForeignFlowItem]] = {investor: [] for investor in investors}

        total = len(tickers)
        for idx, ticker in enumerate(tickers, start=1):
            if progress_label and progress_every > 0 and (idx == 1 or idx % progress_every == 0 or idx == total):
                print(f"[ranking:{progress_label}] {idx}/{total}")

            name = self.get_ticker_name(ticker)
            close, close_change = self.get_latest_close_and_change(ticker)
            net_df = self._retry_empty_df(ticker, calendar_lookback_days, unit=unit)

            for investor in investors:
                net_sum, recent_daily_nets = self._extract_investor_stats(
                    net_df,
                    investor=investor,
                    window_trading_days=window_trading_days,
                    recent_days=recent_days,
                )
                ranking_map[investor].append(
                    RankedForeignFlowItem(
                        ticker=ticker,
                        name=name,
                        close=close,
                        close_change=close_change,
                        net_sum=net_sum,
                        recent_daily_nets=recent_daily_nets,
                    )
                )

        for investor in investors:
            ranking_map[investor].sort(key=lambda item: item.net_sum, reverse=True)
            ranking_map[investor] = ranking_map[investor][:top_n]

        return ranking_map
