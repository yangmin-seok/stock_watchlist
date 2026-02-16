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


def evaluate_ma_touch(df: pd.DataFrame, rule_id: str, window: int, tolerance_pct: float) -> RuleResult:
    df = _ensure_ma(df, window)
    ma_col = f"ma{window}"
    working = df.dropna(subset=[ma_col])
    if working.empty:
        return RuleResult(
            rule_id=rule_id,
            triggered=False,
            message=f"Not enough data for MA{window} touch evaluation",
        )

    today = working.iloc[-1]
    close = float(today["종가"])
    ma = float(today[ma_col])
    distance_pct = abs(close - ma) / ma * 100
    triggered = distance_pct <= tolerance_pct

    return RuleResult(
        rule_id=rule_id,
        triggered=triggered,
        message=(
            f"MA{window} touch check: close={close:,.0f}, ma={ma:,.2f}, "
            f"distance={distance_pct:.3f}% (threshold={tolerance_pct:.3f}%)"
        ),
    )


def evaluate_ma_cross(df: pd.DataFrame, rule_id: str, window: int, direction: str) -> RuleResult:
    df = _ensure_ma(df, window)
    ma_col = f"ma{window}"
    working = df.dropna(subset=[ma_col]).iloc[-2:]
    if len(working) < 2:
        return RuleResult(rule_id=rule_id, triggered=False, message="Not enough data for cross evaluation")

    yesterday = working.iloc[0]
    today = working.iloc[1]

    y_close = float(yesterday["종가"])
    y_ma = float(yesterday[ma_col])
    t_close = float(today["종가"])
    t_ma = float(today[ma_col])

    if direction == "up":
        triggered = y_close < y_ma and t_close >= t_ma
    elif direction == "down":
        triggered = y_close > y_ma and t_close <= t_ma
    else:
        raise ValueError(f"Unsupported direction: {direction}. Use 'up' or 'down'.")

    return RuleResult(
        rule_id=rule_id,
        triggered=triggered,
        message=(
            f"MA{window} cross-{direction}: y_close={y_close:,.0f}, y_ma={y_ma:,.2f}, "
            f"t_close={t_close:,.0f}, t_ma={t_ma:,.2f}"
        ),
    )


def evaluate_rule(df: pd.DataFrame, rule: dict, default_tolerance_pct: float) -> RuleResult:
    rule_type = rule["type"]
    rule_id = rule["id"]
    window = int(rule.get("window", 60))

    if rule_type == "ma_touch":
        tolerance = float(rule.get("tolerance_pct", default_tolerance_pct))
        return evaluate_ma_touch(df, rule_id, window, tolerance)
    if rule_type == "ma_cross":
        direction = str(rule.get("direction", "up"))
        return evaluate_ma_cross(df, rule_id, window, direction)

    raise ValueError(f"Unsupported rule type: {rule_type}")
