# stock_watchlist
종가 기준 Watchlist MA 조건 + KOSPI 시총 상위 1000개 중 외국인 수급 상위 100 랭킹 메일 프로젝트.

## 현재 전략(요청 반영)
1. **Watchlist**
   - 룰은 1개만 사용: `종가 <= 이동평균선(MA)`
   - 예: MA60 기준으로 종가가 이동평균선 아래(또는 동일)일 때 트리거
2. **시장 리포트**
   - KOSPI 시가총액 상위 1000개 종목을 유니버스로 사용
   - 최근 1달(기본 20영업일) 외국인 순매수 기준으로 상위 100개 정렬
   - 메일에 `종목명 | 현재가(전일대비) | 외국인 순매수` 포함

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
5. 유니버스에서 최근 20영업일 외국인 순매수 상위 100개를 내림차순 정렬
6. 메일 본문에 watchlist 결과 + 100개 랭킹(현재가/전일대비 포함) 표시
7. watchlist 트리거만 SQLite 중복 방지 기록

## SMTP 인증 오류(535) 트러블슈팅
- `Username and Password not accepted` 오류가 나면 일반 계정 비밀번호가 아니라 **Google 앱 비밀번호(16자리)** 를 사용해야 합니다.
- Google 계정에서 2단계 인증을 켠 후 앱 비밀번호를 생성해 `GMAIL_APP_PASSWORD`에 넣으세요.
- 코드에서 공백은 자동 제거되지만, 값 자체가 앱 비밀번호가 아니면 인증 실패합니다.
