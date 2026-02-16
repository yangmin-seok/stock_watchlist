# stock_watchlist
종가 기준 Watchlist MA 조건 + KOSPI 상위 400 외국인 수급 랭킹 메일 프로젝트.

## 현재 전략(요청 반영)
1. **Watchlist**
   - 룰은 1개만 사용: `종가 <= 이동평균선(MA)`
   - 예: MA60 기준으로 종가가 이동평균선 아래(또는 동일)일 때 트리거
2. **시장 리포트**
   - KOSPI 시가총액 상위 400개 종목 대상
   - 최근 1달(기본 20영업일) 외국인 순매수 기준 내림차순 정렬
   - 메일에 `종목명 | 현재가 | 외국인 순매수` 포함

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
- `ranking.top_n: 400`
- `ranking.window_trading_days: 20` (최근 1달 근사)

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
4. KOSPI 시총 상위 400개 추출
5. 상위 400개 종목의 최근 20영업일 외국인 순매수 계산 후 내림차순 정렬
6. 메일 본문에 watchlist 결과 + 400개 랭킹 포함
7. watchlist 트리거만 SQLite 중복 방지 기록
