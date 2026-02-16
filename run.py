from __future__ import annotations

import argparse
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

from stockwatch.data import StockDataClient
from stockwatch.formatters import TriggeredItem, make_body, make_subject
from stockwatch.notifier import MailAuthenticationError, send_email
from stockwatch.rules import evaluate_rule
from stockwatch.state import AlertStateStore


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _split_recipients(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="EOD stock watchlist alert runner")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--watchlist", default="watchlist.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Do not send email / write state")
    parser.add_argument("--strict", action="store_true", help="Fail fast on per-ticker errors")
    args = parser.parse_args()

    load_dotenv()

    config = load_yaml(args.config)
    watchlist_cfg = load_yaml(args.watchlist)

    timezone = config["timezone"]
    now = datetime.now(ZoneInfo(timezone))
    alert_date = now.strftime("%Y-%m-%d")

    defaults = config["defaults"]
    ranking_cfg = config["ranking"]

    client = StockDataClient(timezone=timezone, rate_limit_sec=float(config.get("rate_limit_sec", 0.0)))
    state = AlertStateStore(config.get("state_db_path", "state.db"))

    triggered_items: list[TriggeredItem] = []
    errors: list[str] = []

    for item in watchlist_cfg.get("watchlist", []):
        ticker = item["ticker"]
        name = item.get("name", ticker)

        try:
            ohlcv = client.get_ohlcv(ticker, int(defaults["ohlcv_calendar_lookback_days"]))
            foreign_cfg = item.get("foreign_flow", {})
            foreign_unit = foreign_cfg.get("unit", "value")
            foreign_window = int(
                foreign_cfg.get("window_trading_days", defaults["foreign_window_trading_days"])
            )
            include_buy_sell = bool(foreign_cfg.get("include_buy_sell", True))

            for rule in item.get("rules", []):
                result = evaluate_rule(ohlcv, rule)
                if not result.triggered:
                    continue
                if state.was_sent(alert_date, ticker, result.rule_id):
                    continue

                foreign_summary = client.summarize_foreign_flow(
                    ticker=ticker,
                    unit=foreign_unit,
                    calendar_lookback_days=int(defaults["foreign_calendar_lookback_days"]),
                    window_trading_days=foreign_window,
                    include_buy_sell=include_buy_sell,
                )
                triggered_items.append(
                    TriggeredItem(
                        ticker=ticker,
                        name=name,
                        rule_result=result,
                        foreign_flow=foreign_summary,
                    )
                )

        except Exception as exc:
            message = f"[{ticker} {name}] {exc}"
            errors.append(message)
            if args.strict:
                raise

    ranking = client.build_kospi_foreign_flow_ranking(
        top_n=int(ranking_cfg["top_n"]),
        unit=str(ranking_cfg.get("unit", "value")),
        calendar_lookback_days=int(ranking_cfg["calendar_lookback_days"]),
        window_trading_days=int(ranking_cfg["window_trading_days"]),
    )

    subject = make_subject(triggered_items, alert_date)
    body = make_body(
        triggered_items,
        ranking,
        alert_date,
        ranking_top_n=int(ranking_cfg["top_n"]),
        ranking_window_trading_days=int(ranking_cfg["window_trading_days"]),
        ranking_unit=str(ranking_cfg.get("unit", "value")),
    )

    if errors:
        body += "\n[경고] 일부 watchlist 종목 처리 중 오류:\n"
        body += "\n".join(f"- {message}" for message in errors)

    if args.dry_run:
        print(subject)
        print()
        print(body)
        return 0

    gmail_user = os.getenv("GMAIL_USER")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")
    alert_to = os.getenv("ALERT_TO")
    if not gmail_user or not gmail_app_password or not alert_to:
        raise RuntimeError("Missing env vars: GMAIL_USER, GMAIL_APP_PASSWORD, ALERT_TO")

    recipients = _split_recipients(alert_to)
    smtp_cfg = config["smtp"]
    try:
        for to_addr in recipients:
            send_email(
                smtp_host=smtp_cfg["host"],
                smtp_port=int(smtp_cfg["port"]),
                use_starttls=bool(smtp_cfg.get("use_starttls", True)),
                user=gmail_user,
                app_password=gmail_app_password,
                to_addr=to_addr,
                subject=subject,
                body=body,
            )
    except MailAuthenticationError as exc:
        print(f"[{alert_date}] {exc}")
        return 2

    for item in triggered_items:
        state.mark_sent(alert_date, item.ticker, item.rule_result.rule_id)

    print(
        f"[{alert_date}] Sent watchlist alerts={len(triggered_items)}, ranking items={len(ranking)}, recipients={len(recipients)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
