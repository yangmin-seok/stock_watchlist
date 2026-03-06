from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

from stockwatch.data import StockDataClient
from stockwatch.formatters import TriggeredItem, make_body, make_html_body, make_subject
from stockwatch.notifier import MailAuthenticationError, send_email
from stockwatch.rules import evaluate_rule
from stockwatch.state import AlertStateStore


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)




def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_krx_settings(config: dict) -> tuple[bool, str | None, str | None, str]:
    krx_cfg = config.get("krx", {})

    enable_default = bool(krx_cfg.get("enable_login", False))
    krx_enable_login = _parse_bool(os.getenv("KRX_ENABLE_LOGIN"), default=enable_default)

    krx_login_id = os.getenv("KRX_LOGIN_ID")
    krx_login_pw = os.getenv("KRX_LOGIN_PW")

    fail_policy = str(os.getenv("KRX_LOGIN_FAIL_POLICY") or krx_cfg.get("login_fail_policy", "continue")).strip().lower()
    if fail_policy not in {"continue", "raise"}:
        raise ValueError("KRX_LOGIN_FAIL_POLICY must be one of: continue, raise")

    return krx_enable_login, krx_login_id, krx_login_pw, fail_policy

def _split_recipients(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="EOD stock watchlist alert runner")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--watchlist", default="watchlist.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Do not send email / write state")
    parser.add_argument("--strict", action="store_true", help="Fail fast on per-ticker errors")
    parser.add_argument("--quiet", action="store_true", help="Reduce progress logs")
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = load_yaml(args.config)
    watchlist_cfg = load_yaml(args.watchlist)

    timezone = config["timezone"]
    now = datetime.now(ZoneInfo(timezone))
    alert_date = now.strftime("%Y-%m-%d")

    defaults = config["defaults"]
    ranking_cfg = config["ranking"]

    krx_enable_login, krx_login_id, krx_login_pw, krx_login_fail_policy = _resolve_krx_settings(config)

    client = StockDataClient(
        timezone=timezone,
        rate_limit_sec=float(config.get("rate_limit_sec", 0.0)),
        krx_enable_login=krx_enable_login,
        krx_login_id=krx_login_id,
        krx_login_pw=krx_login_pw,
        krx_login_fail_policy=krx_login_fail_policy,
    )
    state = AlertStateStore(config.get("state_db_path", "state.db"))

    triggered_items: list[TriggeredItem] = []
    errors: list[str] = []

    watchlist_items = watchlist_cfg.get("watchlist", [])
    total_watchlist = len(watchlist_items)

    for idx, item in enumerate(watchlist_items, start=1):
        ticker = item["ticker"]
        name = item.get("name", ticker)

        try:
            if not args.quiet:
                print(f"[watchlist {idx}/{total_watchlist}] {ticker} {name}")
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
                    print(f"  - rule {rule['id']} not triggered")
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

    ranking_top_n = int(ranking_cfg["top_n"])
    ranking_universe_top_n = int(ranking_cfg.get("universe_top_n", ranking_top_n))
    ranking_unit = str(ranking_cfg.get("unit", "value"))
    ranking_window_days = int(ranking_cfg["window_trading_days"])
    ranking_recent_days = int(ranking_cfg.get("recent_days", 5))
    ranking_bold_threshold = float(ranking_cfg.get("recent_days_bold_threshold", 0))

    if not args.quiet:
        print("[ranking] foreign+institution start")
    ranking_map = client.build_kospi_flow_rankings(
        top_n=ranking_top_n,
        universe_top_n=ranking_universe_top_n,
        unit=ranking_unit,
        calendar_lookback_days=int(ranking_cfg["calendar_lookback_days"]),
        window_trading_days=ranking_window_days,
        recent_days=ranking_recent_days,
        investors=("foreign", "institution"),
        progress_label="all",
        progress_every=100,
    )
    foreign_ranking = ranking_map["foreign"]
    institution_ranking = ranking_map["institution"]

    foreign_subject = make_subject(triggered_items, alert_date, flow_label="외국인수급")
    foreign_body = make_body(
        triggered_items,
        foreign_ranking,
        alert_date,
        investor_label="외국인",
        ranking_top_n=ranking_top_n,
        ranking_universe_top_n=ranking_universe_top_n,
        ranking_window_trading_days=ranking_window_days,
        ranking_unit=ranking_unit,
        ranking_recent_days=ranking_recent_days,
        ranking_recent_days_bold_threshold=ranking_bold_threshold,
    )

    institution_subject = make_subject(triggered_items, alert_date, flow_label="기관수급")
    institution_body = make_body(
        triggered_items,
        institution_ranking,
        alert_date,
        investor_label="기관",
        ranking_top_n=ranking_top_n,
        ranking_universe_top_n=ranking_universe_top_n,
        ranking_window_trading_days=ranking_window_days,
        ranking_unit=ranking_unit,
        ranking_recent_days=ranking_recent_days,
        ranking_recent_days_bold_threshold=ranking_bold_threshold,
    )

    foreign_html_body = make_html_body(foreign_body)
    institution_html_body = make_html_body(institution_body)

    if errors:
        warning_block = "\n[경고] 일부 watchlist 종목 처리 중 오류:\n" + "\n".join(
            f"- {message}" for message in errors
        )
        foreign_body += warning_block
        institution_body += warning_block
        foreign_html_body = make_html_body(foreign_body)
        institution_html_body = make_html_body(institution_body)

    if args.dry_run:
        print("=" * 80)
        print(foreign_subject)
        print()
        print(foreign_body)
        print("=" * 80)
        print(institution_subject)
        print()
        print(institution_body)
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
                subject=foreign_subject,
                body=foreign_body,
                html_body=foreign_html_body,
            )
            send_email(
                smtp_host=smtp_cfg["host"],
                smtp_port=int(smtp_cfg["port"]),
                use_starttls=bool(smtp_cfg.get("use_starttls", True)),
                user=gmail_user,
                app_password=gmail_app_password,
                to_addr=to_addr,
                subject=institution_subject,
                body=institution_body,
                html_body=institution_html_body,
            )
    except MailAuthenticationError as exc:
        print(f"[{alert_date}] {exc}")
        return 2

    for item in triggered_items:
        state.mark_sent(alert_date, item.ticker, item.rule_result.rule_id)

    print(
        f"[{alert_date}] Sent watchlist alerts={len(triggered_items)}, foreign ranking items={len(foreign_ranking)}, institution ranking items={len(institution_ranking)}, recipients={len(recipients)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
