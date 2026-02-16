# stock_watchlist
외국인 수급 + 이동평균 룰(EOD) 기반 메일 알림 미니 프로젝트.

## MVP 목표
1. **Watchlist 감시(EOD)**
   - 종가 기준 MA60 터치 / 상향돌파 등 룰 평가
   - 트리거 발생 시 Gmail SMTP로 이메일 발송
2. **외국인 수급 리포트 포함**
   - 최근 N영업일 외국인 매수/매도/순매수 집계(value/volume)
   - 이메일 본문에 이유(룰 + 수급)를 함께 표시

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
`.env.example`를 복사해서 `.env`를 만든 뒤 값 입력:
```env
GMAIL_USER=yourname@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
ALERT_TO=receiver@gmail.com
```
- `ALERT_TO`는 `a@x.com,b@y.com` 형태로 다중 수신자 지정 가능

### 2) `config.yaml`
- timezone, SMTP, rate limit, default lookback/window, state DB 경로 지정
- 기본 SMTP는 `smtp.gmail.com:587` + STARTTLS

### 3) `watchlist.yaml`
- 종목, 룰, 외국인 수급 리포트 옵션 정의

## 실행
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py --dry-run
python run.py
```

옵션:
- `--strict`: 종목 1개 처리 실패 시 즉시 에러로 중단

## 동작 흐름
1. watchlist 로드
2. 종목별 OHLCV 조회 및 MA 룰 평가
3. 트리거가 있는 종목만 외국인 수급 요약 계산
4. 트리거 조합(date/ticker/rule) 중복 확인(SQLite)
5. 메일 발송 후 state 기록

## 운영 권장
- 한국 기준 **18:20 KST** 하루 1회 실행 권장(수급 데이터 반영 시점 고려)
- 예시 크론:
```cron
20 18 * * 1-5 /path/to/venv/bin/python /path/to/stock_watchlist/run.py >> /path/to/stock_watchlist/cron.log 2>&1
```
