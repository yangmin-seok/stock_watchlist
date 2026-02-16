from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from stockwatch.data import ForeignFlowSummary, RankedForeignFlowItem
from stockwatch.rules import RuleResult


@dataclass
class TriggeredItem:
    ticker: str
    name: str
    rule_result: RuleResult
    foreign_flow: ForeignFlowSummary


def format_number(value: float, unit: str) -> str:
    if unit == "value":
        eok = value / 100_000_000
        return f"{eok:,.1f}억원"
    return f"{value:,.0f}주"


def format_signed_won(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.0f}원"


def make_subject(triggered: Iterable[TriggeredItem], alert_date: str) -> str:
    items = list(triggered)
    if not items:
        return f"[StockWatch] {alert_date} Watchlist/외국인수급 리포트"
    names = ", ".join(item.name for item in items[:3])
    suffix = "" if len(items) <= 3 else f" 외 {len(items) - 3}건"
    return f"[StockWatch] {alert_date} Watchlist {names}{suffix} + 외국인수급"


def make_watchlist_body(triggered: Iterable[TriggeredItem], alert_date: str) -> list[str]:
    items = list(triggered)
    lines: list[str] = [f"StockWatch EOD 알림 ({alert_date})", ""]

    if not items:
        lines.extend(["[Watchlist] 조건 충족 종목 없음", ""])
        return lines

    lines.extend(["[Watchlist] 종가가 이동평균선 이하인 종목", ""])
    for idx, item in enumerate(items, start=1):
        flow = item.foreign_flow
        lines.append(f"{idx}. {item.name} ({item.ticker})")
        lines.append(f"   - Trigger: {item.rule_result.rule_id}")
        lines.append(f"   - Detail: {item.rule_result.message}")
        lines.append(
            f"   - 최근 {flow.window_trading_days}영업일 외국인 순매수: {format_number(flow.net_sum, flow.unit)}"
        )
        if flow.buy_sum is not None and flow.sell_sum is not None:
            lines.append(f"   - 외국인 매수합: {format_number(flow.buy_sum, flow.unit)}")
            lines.append(f"   - 외국인 매도합: {format_number(flow.sell_sum, flow.unit)}")
        lines.append(f"   - 연속 순매수 일수: {flow.streak_net_buy_days}일")
        lines.append("")

    lines.append("(중복 방지를 위해 같은 날짜/종목/룰 조합은 1회만 발송됩니다.)")
    lines.append("")
    return lines


def make_ranking_body(
    ranking: Iterable[RankedForeignFlowItem],
    *,
    top_n: int,
    universe_top_n: int,
    window_trading_days: int,
    unit: str,
) -> list[str]:
    rows = list(ranking)
    lines: list[str] = [
        f"[KOSPI 시총 상위 {universe_top_n}개 중 외국인 순매수 상위 {top_n}] 최근 {window_trading_days}영업일",
        f"(표시: 종목명 | 현재가(전일대비) | 외국인 순매수[{ '거래대금' if unit == 'value' else '거래량' }])",
        "",
    ]

    for idx, item in enumerate(rows, start=1):
        lines.append(
            f"{idx:>3}. {item.name} ({item.ticker}) | {item.close:,.0f}원 ({format_signed_won(item.close_change)}) | {format_number(item.net_sum, unit)}"
        )

    lines.append("")
    return lines


def make_body(
    triggered: Iterable[TriggeredItem],
    ranking: Iterable[RankedForeignFlowItem],
    alert_date: str,
    *,
    ranking_top_n: int,
    ranking_universe_top_n: int,
    ranking_window_trading_days: int,
    ranking_unit: str,
) -> str:
    lines = make_watchlist_body(triggered, alert_date)
    lines.extend(
        make_ranking_body(
            ranking,
            top_n=ranking_top_n,
            universe_top_n=ranking_universe_top_n,
            window_trading_days=ranking_window_trading_days,
            unit=ranking_unit,
        )
    )
    return "\n".join(lines)
