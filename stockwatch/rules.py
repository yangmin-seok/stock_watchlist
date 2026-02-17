from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class RuleResult:
    rule_id: str
    triggered: bool
    message: str


def _ensure_ma(df: pd.DataFrame, window: int) -> pd.DataFrame:
    ma_col = f"ma{window}"
    if ma_col not in df.columns:
        df = df.copy()
        df[ma_col] = df["종가"].rolling(window=window).mean()
    return df


def evaluate_ma_below_or_touch(df: pd.DataFrame, rule_id: str, window: int) -> RuleResult:
    df = _ensure_ma(df, window)
    ma_col = f"ma{window}"
    working = df.dropna(subset=[ma_col])
    if working.empty:
        return RuleResult(rule_id=rule_id, triggered=False, message=f"Not enough data for MA{window} evaluation")

    today = working.iloc[-1]
    close = float(today["종가"])
    ma = float(today[ma_col])
    triggered = close <= ma

    relation = "이하" if triggered else "초과"
    return RuleResult(
        rule_id=rule_id,
        triggered=triggered,
        message=(
            f"종가({close:,.0f}원)가 {window}일 이동평균({ma:,.0f}원) {relation}입니다."
        ),
    )


def evaluate_rule(df: pd.DataFrame, rule: dict) -> RuleResult:
    rule_type = rule["type"]
    rule_id = rule["id"]
    window = int(rule.get("window", 60))

    if rule_type == "ma_below_or_touch":
        return evaluate_ma_below_or_touch(df, rule_id, window)

    raise ValueError(f"Unsupported rule type: {rule_type}")
