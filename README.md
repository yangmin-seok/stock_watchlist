# stock_watchlist
종가 기준 Watchlist MA 조건 + KOSPI 시총 상위 1000개 중 외국인/기관 수급 상위 100 랭킹 메일 프로젝트.

## 현재 전략(요청 반영)
1. **Watchlist**
   - 룰은 1개만 사용: `종가 <= 이동평균선(MA)`
   - 예: MA60 기준으로 종가가 이동평균선 아래(또는 동일)일 때 트리거
2. **시장 리포트**
   - KOSPI 시가총액 상위 1000개 종목을 유니버스로 사용
   - 최근 1달(기본 20영업일) 순매수 기준으로 외국인/기관 각각 상위 100개 정렬
   - 메일을 2회 발송:
     - 1차: 외국인 수급 리포트
     - 2차: 기관 수급 리포트
   - 메일에 `종목명 | 현재가(전일대비) | 순매수(최근 5일)` 포함
   - 최근 5일 일별 수급 중 `recent_days_bold_threshold` 이상 값은 `**굵게**` 표시

## 프로젝트 구조
```text
stock_watchlist/
  requirements.txt
  .env.example
  config.yaml
  watchlist.yaml
  run.py
  stockwatch/
    __init__.py
    data.py
    rules.py
    notifier.py
    state.py
    formatters.py
```

## 설정
### 1) 환경변수
`.env.example`를 복사해서 `.env` 생성:
```env
GMAIL_USER=yourname@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
ALERT_TO=receiver@gmail.com
```
- `ALERT_TO`는 `a@x.com,b@y.com` 형태로 복수 수신자 가능

### 2) `config.yaml`
- 기본 동작 파라미터 + 랭킹 파라미터
- `ranking.top_n: 100` (최종 출력 개수)
- `ranking.universe_top_n: 1000` (시총 유니버스 개수)
- `ranking.window_trading_days: 20` (최근 1달 근사)
- `ranking.recent_days: 5` (괄호로 표기할 최근 일수)
- `ranking.recent_days_bold_threshold: 10000000000` (거래대금 기준 100억원, 절대값 이상 bold)

### 3) `watchlist.yaml`
- watchlist 종목별 `ma_below_or_touch` 룰 정의

## 실행
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py --dry-run
python run.py
```

옵션:
- `--strict`: 특정 종목 실패 시 즉시 중단

## 동작 흐름
1. watchlist 로드
2. 종목별 OHLCV 조회 후 `ma_below_or_touch` 판정
3. 트리거된 watchlist 종목의 외국인 수급 요약 계산
4. KOSPI 시총 상위 1000개 추출(유니버스)
5. 유니버스에서 최근 20영업일 순매수 상위 100개를 외국인/기관 각각 계산
6. 최근 5일 수급 내역을 괄호로 표기하고 threshold 이상은 bold 처리
7. 메일 2회 발송(외국인/기관)
8. watchlist 트리거만 SQLite 중복 방지 기록


## 자동 실행(크론)
평일 장 마감 후 자동 실행하려면 아래 스크립트를 사용하세요.

```bash
# 기본: 평일 16:10(KST) 실행 등록
bash scripts/setup_cron.sh install

# 시간 지정(예: 평일 22:00)
bash scripts/setup_cron.sh install 22:00

# 등록 제거
bash scripts/setup_cron.sh remove
```

- 크론 등록 시 실행 명령: `python run.py`
- 로그 파일: `logs/stockwatch_cron.log`
- `PYTHON_BIN` 환경변수로 파이썬 경로를 강제할 수 있습니다.


## 자동 실행(크론)
평일 장 마감 후 자동 실행하려면 아래 스크립트를 사용하세요.

```bash
# 기본: 평일 16:10(KST) 실행 등록
bash scripts/setup_cron.sh install

# 시간 지정(예: 평일 18:05)
bash scripts/setup_cron.sh install 18:05

# 등록 제거
bash scripts/setup_cron.sh remove
```

- 크론 등록 시 실행 명령: `python run.py`
- 로그 파일: `logs/stockwatch_cron.log`
- `PYTHON_BIN` 환경변수로 파이썬 경로를 강제할 수 있습니다.

## SMTP 인증 오류(535) 트러블슈팅
- `Username and Password not accepted` 오류가 나면 일반 계정 비밀번호가 아니라 **Google 앱 비밀번호(16자리)** 를 사용해야 합니다.
- Google 계정에서 2단계 인증을 켠 후 앱 비밀번호를 생성해 `GMAIL_APP_PASSWORD`에 넣으세요.
- 코드에서 공백은 자동 제거되지만, 값 자체가 앱 비밀번호가 아니면 인증 실패합니다.
