from __future__ import annotations

from dataclasses import dataclass
import html
import re
from typing import Iterable

from stockwatch.data import ForeignFlowSummary, RankedForeignFlowItem
from stockwatch.rules import RuleResult

RECENT_SUM_HIGHLIGHT_THRESHOLD_VALUE = 30_000_000_000  # 300억원


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


def format_recent_sum(values: list[float], unit: str) -> str:
    if not values:
        return "-"
    return format_number(float(sum(values)), unit)




def emphasize_recent_sum(token: str, *, recent_sum_value: float, unit: str, recent_days: int) -> str:
    should_emphasize = (
        unit == "value"
        and recent_days >= 5
        and abs(recent_sum_value) >= RECENT_SUM_HIGHLIGHT_THRESHOLD_VALUE
    )
    if not should_emphasize:
        return token
    return f"★{token}★"

def format_rule_trigger(rule_id: str) -> str:
    if rule_id.startswith("ma") and rule_id.endswith("_below_or_touch"):
        window = rule_id[len("ma") : -len("_below_or_touch")]
        if window.isdigit():
            return f"{window}일 이동평균선 하회(또는 접촉)"
    return rule_id


def make_subject(triggered: Iterable[TriggeredItem], alert_date: str, flow_label: str) -> str:
    items = list(triggered)
    if not items:
        return f"[StockWatch] {alert_date} Watchlist/{flow_label} 리포트"
    names = ", ".join(item.name for item in items[:3])
    suffix = "" if len(items) <= 3 else f" 외 {len(items) - 3}건"
    return f"[StockWatch] {alert_date} Watchlist {names}{suffix} + {flow_label}"


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
        lines.append(f"   - 조건: {format_rule_trigger(item.rule_result.rule_id)}")
        lines.append(f"   - 설명: {item.rule_result.message}")
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
    investor_label: str,
    top_n: int,
    universe_top_n: int,
    window_trading_days: int,
    unit: str,
    recent_days: int,
    recent_days_bold_threshold: float,
) -> list[str]:
    rows = list(ranking)
    lines: list[str] = [
        f"[KOSPI 시총 상위 {universe_top_n}개 중 {investor_label} 순매수 상위 {top_n}] 최근 {window_trading_days}영업일",
        f"(표시: 종목명 | 현재가(전일대비) | {investor_label} 순매수[{ '거래대금' if unit == 'value' else '거래량' }] | 최근 {recent_days}일 합)",
        "",
    ]

    for idx, item in enumerate(rows, start=1):
        recent_sum_value = float(sum(item.recent_daily_nets)) if item.recent_daily_nets else 0.0
        recent_sum = format_recent_sum(item.recent_daily_nets, unit=unit)
        recent_sum = emphasize_recent_sum(
            recent_sum,
            recent_sum_value=recent_sum_value,
            unit=unit,
            recent_days=recent_days,
        )
        lines.append(
            f"{idx:>3}. {item.name} ({item.ticker}) | {item.close:,.0f}원 ({format_signed_won(item.close_change)}) | {format_number(item.net_sum, unit)} (최근 {recent_days}일 합 {recent_sum})"
        )

    lines.append("")
    return lines


def make_body(
    triggered: Iterable[TriggeredItem],
    ranking: Iterable[RankedForeignFlowItem],
    alert_date: str,
    *,
    investor_label: str,
    ranking_top_n: int,
    ranking_universe_top_n: int,
    ranking_window_trading_days: int,
    ranking_unit: str,
    ranking_recent_days: int,
    ranking_recent_days_bold_threshold: float,
) -> str:
    lines = make_watchlist_body(triggered, alert_date)
    lines.extend(
        make_ranking_body(
            ranking,
            investor_label=investor_label,
            top_n=ranking_top_n,
            universe_top_n=ranking_universe_top_n,
            window_trading_days=ranking_window_trading_days,
            unit=ranking_unit,
            recent_days=ranking_recent_days,
            recent_days_bold_threshold=ranking_recent_days_bold_threshold,
        )
    )
    return "\n".join(lines)


HIGHLIGHT_TOKEN_PATTERN = re.compile(r"★([^★]+)★")


def make_html_body(text_body: str) -> str:
    escaped = html.escape(text_body)
    highlighted = HIGHLIGHT_TOKEN_PATTERN.sub(
        lambda m: f'<span style="color:#d32f2f;font-weight:700;">{m.group(1)}</span>',
        escaped,
    )
    rendered = highlighted.replace("\n", "<br>\n")
    return (
        '<html><body style="font-family:Arial,sans-serif;font-size:14px;line-height:1.45;">'
        f"{rendered}"
        "</body></html>"
    )
