#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   scripts/setup_cron.sh install [HH:MM]
#   scripts/setup_cron.sh remove
# Default schedule: weekdays 16:10 (Asia/Seoul)

ACTION="${1:-install}"
TIME_KST="${2:-16:10}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"
LOG_FILE="${LOG_DIR}/stockwatch_cron.log"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "python3를 찾을 수 없습니다. PYTHON_BIN 환경변수를 지정하세요." >&2
  exit 1
fi

if ! command -v crontab >/dev/null 2>&1; then
  echo "crontab 명령이 없습니다. cron 패키지를 설치한 뒤 다시 시도하세요." >&2
  exit 1
fi

if [[ ! "${TIME_KST}" =~ ^([01]?[0-9]|2[0-3]):([0-5][0-9])$ ]]; then
  echo "시간 형식 오류: ${TIME_KST} (예: 16:10)" >&2
  exit 1
fi

hour="${TIME_KST%:*}"
minute="${TIME_KST#*:}"
# Remove leading zeros for cron compatibility.
hour="$((10#${hour}))"
minute="$((10#${minute}))"

mkdir -p "${LOG_DIR}"

CRON_MARK="# stock_watchlist_auto_run"
CRON_CMD="${minute} ${hour} * * 1-5 cd ${REPO_DIR} && ${PYTHON_BIN} run.py >> ${LOG_FILE} 2>&1 ${CRON_MARK}"

current_cron="$(crontab -l 2>/dev/null || true)"
filtered_cron="$(printf '%s\n' "${current_cron}" | sed "/${CRON_MARK//\//\\/}/d")"

case "${ACTION}" in
  install)
    new_cron="${filtered_cron}"
    if [[ -n "${new_cron}" ]]; then
      new_cron+=$'\n'
    fi
    new_cron+="${CRON_CMD}"
    printf '%s\n' "${new_cron}" | crontab -
    echo "크론 등록 완료: 평일 ${hour}:$(printf '%02d' "${minute}") KST"
    echo "로그 파일: ${LOG_FILE}"
    ;;
  remove)
    printf '%s\n' "${filtered_cron}" | crontab -
    echo "크론 제거 완료: ${CRON_MARK}"
    ;;
  *)
    echo "알 수 없는 동작: ${ACTION} (install/remove)" >&2
    exit 1
    ;;
esac
