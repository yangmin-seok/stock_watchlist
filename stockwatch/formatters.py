from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from stockwatch.data import ForeignFlowSummary
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


def make_subject(triggered: Iterable[TriggeredItem], alert_date: str) -> str:
    items = list(triggered)
    if not items:
        return f"[StockWatch] {alert_date} 트리거 없음"
    names = ", ".join(item.name for item in items[:3])
    suffix = "" if len(items) <= 3 else f" 외 {len(items) - 3}건"
    return f"[StockWatch] {alert_date} {names}{suffix}"


def make_body(triggered: Iterable[TriggeredItem], alert_date: str) -> str:
    items = list(triggered)
    if not items:
        return f"{alert_date} 기준 트리거가 없습니다."

    lines: list[str] = [
        f"StockWatch EOD 알림 ({alert_date})",
        "",
        "아래 종목에서 조건이 충족되어 알림을 보냅니다.",
        "",
    ]

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
    return "\n".join(lines)
