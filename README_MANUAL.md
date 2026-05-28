# 📈 InvestAI — 개인 투자 서포트 비서 플랫폼 사용 매뉴얼

> **⚠️ 중요 고지**  
> 이 플랫폼은 실제 주식 매수·매도(Trading Execution)를 **절대 지원하지 않습니다.**  
> 사용자가 이미 보유 중인 자산 정보를 **직접 수동으로 입력**하면, 시장 데이터를 가져와  
> 현재가 반영 수익률 계산, 환차익/환차손 분리, AI 분석 리포트 등  
> **투자 분석 및 의사결정 서포트 기능만** 제공합니다.

---

## 목차

1. [시스템 구성 한눈에 보기](#1-시스템-구성-한눈에-보기)
2. [사전 준비 — 필수 도구 설치](#2-사전-준비--필수-도구-설치)
3. [환경 변수 설정 (.env)](#3-환경-변수-설정-env)
4. [데이터베이스 초기화](#4-데이터베이스-초기화)
5. [3개 터미널로 서버 실행하기](#5-3개-터미널로-서버-실행하기)
6. [핵심 기능 사용 설명서](#6-핵심-기능-사용-설명서)
   - 6-1. 회원가입 & 로그인
   - 6-2. 포트폴리오 생성 & 자산 수동 등록
   - 6-3. 다중 통화 수익률 평가
   - 6-4. AI 투자 비서 (Gemini 리포트)
   - 6-5. 밸류체인(공급망) 시각화 지도
   - 6-6. 관리자 기능 (Admin)
7. [API 문서 확인 방법](#7-api-문서-확인-방법)
8. [Celery 워커 모니터링 (Flower)](#8-celery-워커-모니터링-flower)
9. [자주 발생하는 오류 & 해결법](#9-자주-발생하는-오류--해결법)
10. [전체 실행 순서 요약 (Quick Start)](#10-전체-실행-순서-요약-quick-start)

---

## 1. 시스템 구성 한눈에 보기

```
┌─────────────────────────────────────────────────────────┐
│  브라우저  http://localhost:5173                          │
│  React + Vite (프론트엔드)                               │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP /api/v1/*  (Vite 프록시)
┌────────────────────────▼────────────────────────────────┐
│  FastAPI  http://localhost:8000                          │
│  (백엔드 API 서버)                                       │
└──────┬──────────────────┬──────────────────────────────┘
       │                  │
       ▼                  ▼
  PostgreSQL          Redis (캐시 & 메시지 브로커)
  :5432               :6379
                          │
              ┌───────────▼──────────────┐
              │  Celery Worker           │
              │  (AI 리포트, 대안 데이터  │
              │   공급망 리스크 분석)     │
              └──────────────────────────┘
```

| 컴포넌트 | 역할 | 포트 |
|---------|------|------|
| React/Vite | 사용자 UI (포트폴리오 대시보드, 지도) | 5173 |
| FastAPI | REST API, JWT 인증, DB 연동 | 8000 |
| PostgreSQL | 사용자·포트폴리오·보유 종목 영구 저장 | 5432 |
| Redis | Celery 브로커, AI 결과 캐시, 환율 캐시 | 6379 |
| Celery Worker | AI 리포트 생성, 대안 데이터 수집 비동기 처리 | — |
| Celery Beat | SEC/DART 데이터 주기 갱신 스케줄러 | — |
| Flower | Celery 모니터링 대시보드 | 5555 |

---

## 2. 사전 준비 — 필수 도구 설치

> **Mac (Apple Silicon / M1·M2·M3) 기준**으로 작성되었습니다.

### 2-1. Homebrew 설치 확인

터미널을 열고 아래 명령어를 입력하세요:

```bash
brew --version
```

`command not found`가 뜨면 Homebrew를 먼저 설치합니다:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2-2. PostgreSQL 설치 및 실행

```bash
# 설치
brew install postgresql@17

# 백그라운드 서비스로 실행 (Mac 재부팅 후에도 자동 시작)
brew services start postgresql@17

# 실행 확인 (State: started 로 표시되면 정상)
brew services list | grep postgresql
```

> 💡 처음 설치 직후에는 슈퍼유저 계정이 현재 Mac 로그인 사용자명과 동일하게 생성됩니다.

**데이터베이스 및 사용자 생성:**

```bash
# PostgreSQL 접속 (현재 Mac 사용자 계정으로 접속)
psql postgres

# 아래 명령어를 psql 프롬프트 안에서 순서대로 실행하세요
CREATE USER postgres WITH PASSWORD 'password';
CREATE DATABASE investment_db OWNER postgres;
GRANT ALL PRIVILEGES ON DATABASE investment_db TO postgres;

# 종료
\q
```

### 2-3. Redis 설치 및 실행

```bash
# 설치
brew install redis

# 백그라운드 서비스로 실행
brew services start redis

# 실행 확인
redis-cli ping
# → PONG 이 출력되면 정상
```

### 2-4. Node.js 설치 확인 (프론트엔드용)

```bash
node --version   # v18 이상 권장
npm --version
```

없다면:

```bash
brew install node
```

### 2-5. Python 가상환경 활성화 및 패키지 설치

```bash
# 1. 프로젝트 루트 디렉토리로 이동
cd ~/Documents/GitHub/Personal-investment-platform

# 2. 가상환경 활성화 (반드시 이 경로에서 실행)
source venv/bin/activate

# 가상환경이 활성화되면 터미널 프롬프트 앞에 (venv)가 붙습니다
# 예: (venv) chaeyeon@MacBook Personal-investment-platform %

# 3. 의존성 패키지 설치
pip install -r requirements.txt
```

#### ⚠️ Apple Silicon(M1/M2/M3) 비동기 오류 방지 — greenlet 수동 설치

Apple Silicon Mac에서 SQLAlchemy async 드라이버(asyncpg)를 사용할 때  
`greenlet` 관련 오류가 발생할 수 있습니다. 아래 명령어로 미리 설치해 두세요:

```bash
pip install greenlet
```

> **오류 메시지 예시:** `ImportError: cannot import name 'getcurrent' from 'greenlet'`  
> 위 명령어 한 줄로 해결됩니다.

### 2-6. 프론트엔드 의존성 설치

```bash
# frontend 디렉토리로 이동
cd frontend

# npm 패키지 설치
npm install

# 설치 완료 확인 (node_modules 폴더가 생성됩니다)
ls node_modules | head -5

# 다시 프로젝트 루트로 돌아오기
cd ..
```

---

## 3. 환경 변수 설정 (.env)

프로젝트 루트에 `.env` 파일을 생성합니다:

```bash
# 프로젝트 루트에서 실행
touch .env
```

아래 내용을 복사하여 `.env` 파일에 붙여넣고, **API 키 항목**을 본인 것으로 채웁니다:

```dotenv
# ── 데이터베이스 ─────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/investment_db

# ── 보안 키 (최소 32자 이상의 임의 문자열로 변경하세요) ──
SECRET_KEY=my-super-secret-key-that-is-at-least-32-characters-long

# ── Redis ────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# ── Gemini AI (필수: AI 리포트 기능 사용 시) ─────────────
# https://aistudio.google.com/app/apikey 에서 무료 발급
GEMINI_API_KEY=your_gemini_api_key_here

# ── 한국투자증권 KIS API (선택: 국내 주식 실시간 시세) ────
# https://apiportal.koreainvestment.com 에서 발급
KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ACCOUNT_NO=

# ── DART API (선택: AI 리포트 내 한국 기업 재무공시 연동) ─
# https://opendart.fss.or.kr 에서 무료 발급
DART_API_KEY=

# ── SEC API (선택: AI 리포트 내 미국 내부자 거래 데이터) ──
# https://sec-api.io 에서 발급 (무료 플랜 있음)
SEC_API_KEY=

# ── 디버그 모드 (개발 시 True) ───────────────────────────
DEBUG=True
```

> 💡 **최소 실행 요건:** `DATABASE_URL`, `SECRET_KEY`, `REDIS_URL`만 설정하면  
> 기본 포트폴리오 기능은 동작합니다. AI 리포트는 `GEMINI_API_KEY`가 필수입니다.

---

## 4. 데이터베이스 초기화

가상환경이 활성화된 상태에서 프로젝트 루트에서 실행합니다:

```bash
# 가상환경 활성화 확인
source venv/bin/activate

# Alembic 마이그레이션 실행 (테이블 생성)
alembic upgrade head
```

성공하면 아래와 같이 출력됩니다:

```
INFO  [alembic.runtime.migration] Running upgrade  -> 512ae099cb9b, create initial tables
INFO  [alembic.runtime.migration] Running upgrade 512ae099cb9b -> a1b2c3d4e5f6, create supply chain tables
```

> ⚠️ `alembic.ini`의 기본 DB URL은 `postgresql+asyncpg://postgres:password@localhost:5432/investment_db`입니다.  
> `.env`에서 설정한 값과 동일하게 유지하세요.

---

## 5. 3개 터미널로 서버 실행하기

백엔드, Celery 워커, 프론트엔드를 **각각 별도의 터미널 창**에서 실행해야 합니다.  
Mac에서는 `Cmd + T`로 새 탭을 열거나, iTerm2를 사용하면 편리합니다.

---

### 터미널 1 — 백엔드 (FastAPI 서버)

```bash
# 1. 프로젝트 루트로 이동
cd ~/Documents/GitHub/Personal-investment-platform

# 2. 가상환경 활성화
source venv/bin/activate

# 3. FastAPI 서버 실행
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

성공 시 출력:

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [...] using WatchFiles
INFO:     Started server process [...]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

브라우저에서 `http://localhost:8000/health` 를 열면:

```json
{"status": "ok", "version": "0.1.0", "allowed_origins": ["http://localhost:5173", ...]}
```

---

### 터미널 2 — Celery 워커 + Beat 스케줄러

```bash
# 1. 프로젝트 루트로 이동
cd ~/Documents/GitHub/Personal-investment-platform

# 2. 가상환경 활성화
source venv/bin/activate

# 3-A. Celery 워커 실행 (AI 리포트, 대안 데이터, 시장 데이터 큐 모두 처리)
celery -A app.worker.celery_app worker --loglevel=info -Q ai_reports,alternative_data,market_data,celery
```

> AI 리포트 기능을 사용하지 않는 경우 Celery 없이도 포트폴리오 등록·조회는 가능합니다.

Beat 스케줄러(SEC/DART 자동 갱신)까지 함께 실행하려면 **추가 터미널**을 하나 더 열고:

```bash
cd ~/Documents/GitHub/Personal-investment-platform
source venv/bin/activate

# Beat 스케줄러 (SEC 6시간, DART 매일 02:00 자동 갱신)
celery -A app.worker.celery_app beat --loglevel=info
```

---

### 터미널 3 — 프론트엔드 (React/Vite 개발 서버)

```bash
# 1. frontend 디렉토리로 이동
cd ~/Documents/GitHub/Personal-investment-platform/frontend

# 2. 개발 서버 실행
npm run dev
```

성공 시 출력:

```
  VITE v8.x.x  ready in XXX ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: http://192.168.x.x:5173/
```

브라우저에서 **`http://localhost:5173`** 을 열면 InvestAI 로그인 화면이 보입니다.

---

## 6. 핵심 기능 사용 설명서

---

### 6-1. 회원가입 & 로그인

1. 브라우저에서 `http://localhost:5173` 접속
2. 상단 탭에서 **회원가입** 선택
3. 이메일 / 비밀번호 / 이름 입력 후 가입
4. 자동으로 **로그인** 탭으로 이동 → 방금 만든 계정으로 로그인
5. 로그인 성공 시 포트폴리오 대시보드(`/dashboard`)로 이동

> **JWT 토큰 관리:**  
> - Access Token (60분 유효) → 브라우저 sessionStorage 저장  
> - Refresh Token (7일 유효) → 브라우저 localStorage 저장  
> - 탭을 닫으면 Access Token이 삭제되지만 Refresh Token으로 자동 재발급됩니다.

---

### 6-2. 포트폴리오 생성 & 자산 수동 등록

> **⚠️ 반드시 읽어주세요**  
> 이 플랫폼은 증권사 API를 통해 자동으로 보유 종목을 가져오지 않습니다.  
> 실제 거래 내역을 본인이 직접 입력해야 정확한 분석이 제공됩니다.

#### 포트폴리오 만들기

1. 대시보드 좌측 패널에서 포트폴리오 이름 입력 후 **`+`** 버튼 클릭
2. 예시: `미국 성장주`, `국내 가치주`, `ETF 포트폴리오`

#### 종목 수동 등록

포트폴리오 선택 후 **`+ 종목 수동 등록`** 버튼을 클릭하면 입력 폼이 나타납니다.

| 입력 항목 | 설명 | 입력 예시 |
|----------|------|----------|
| **티커** | 종목 심볼 (대소문자 무관, 자동 대문자 변환) | `AAPL`, `MSFT`, `TSLA` |
| **수량** | 현재 보유 수량 | `10`, `3.5` |
| **평균 매수 단가** | 매수 당시 평균 단가 (현지 통화 기준) | `185.50` |
| **통화** | 매수 통화 선택 | `USD`, `KRW`, `JPY`, `EUR`, `HKD` |
| **매수 당시 환율** | 매수일 기준 1 USD = ? KRW | `1350`, `1380` |
| **거래 시장** | 상장 거래소 선택 | `NASDAQ`, `NYSE`, `KRX` |

**종목별 티커 입력 형식:**

| 종목 유형 | 티커 형식 | 실제 예시 |
|----------|----------|----------|
| 미국 주식 (NASDAQ/NYSE) | 영문 심볼 그대로 | `AAPL`, `NVDA`, `MSFT` |
| 미국 ETF | 영문 심볼 그대로 | `QQQ`, `SPY`, `SCHD` |
| 한국 주식 (KOSPI) | 6자리 종목코드 `.KS` | `005930.KS` (삼성전자) |
| 한국 주식 (KOSDAQ) | 6자리 종목코드 `.KQ` | `035720.KQ` (카카오) |
| 한국 주식 (코드만) | 6자리 숫자만 입력 가능 | `005930` (삼성전자) |

**입력 예시 — 애플 10주를 $185에 매수했을 때:**

```
티커:          AAPL
수량:          10
평균 매수 단가: 185.00
통화:          USD
매수 당시 환율: 1350
거래 시장:     NASDAQ
```

**입력 예시 — 삼성전자 5주를 77,000원에 매수했을 때:**

```
티커:          005930.KS
수량:          5
평균 매수 단가: 77000
통화:          KRW
매수 당시 환율: 1380   ← KRW 자산이지만 필드는 비워두지 말고 입력
거래 시장:     KRX
```

---

### 6-3. 다중 통화 수익률 평가

종목을 등록하면 시스템이 자동으로 현재가를 조회하여 아래 항목을 계산합니다.

#### 수익률 계산 방식

플랫폼은 수익률을 **순수 주가 수익**과 **환율 수익**으로 분리하여 보여줍니다.

```
───────────────────────────────────────────────────────
설정값 정의:
  P0 = 매수 평단가 (현지 통화)
  P1 = 현재가     (현지 통화)
  E0 = 매수 당시 환율 (1 USD = E0 KRW)
  E1 = 현재 환율  (실시간 조회)
  Q  = 보유 수량

계산:
  원화 투자원금    = P0 × Q × E0
  현재 원화 평가액 = P1 × Q × E1

  순수 주가 수익률 = (P1 - P0) / P0
  환율 수익률      = (E1 - E0) / E0
  복합 총 수익률   = (1 + 주가수익률) × (1 + 환율수익률) - 1
───────────────────────────────────────────────────────
```

#### 대시보드 상단 요약 카드

| 카드 | 내용 |
|------|------|
| **현재 평가금액** | 모든 종목의 현재 원화 환산 총액 |
| **투자 원금** | 매수 당시 환율 기준 원화 원금 합계 |
| **총 수익률** | 주가 변동 + 환율 변동 복합 수익률 |
| **평가 손익** | 평가금액 - 원금 (원화 기준) |

#### 종목별 카드

각 종목 카드에는 다음이 표시됩니다:
- 현재가 (현지 통화 기준)
- 총 수익률 배지 (초록 = 수익, 빨강 = 손실)

> 💡 **환율 데이터 소스:**  
> 1차: yfinance → 2차: exchangerate-api.com → 3차: 마지막 캐시값 (5분 캐시)  
> 모든 소스 실패 시에도 마지막으로 성공한 환율값을 사용합니다.

---

### 6-4. AI 투자 비서 (Gemini 리포트)

> **필요 조건:** `.env`에 `GEMINI_API_KEY`가 설정되어 있고 Celery 워커가 실행 중이어야 합니다.

AI 리포트는 단순한 LLM 호출이 아닙니다. 아래 3단계 파이프라인을 거칩니다:

#### AI 리포트 생성 파이프라인

```
사용자가 "AI 리포트 요청" 클릭
     │
     ▼
[단계 1: ML 최적화 — 10~25%]
  PyPortfolioOpt으로 포트폴리오 최적 비중 계산
  • 최소 변동성 포트폴리오
  • 샤프 지수 최대화 포트폴리오
  • 등비중 포트폴리오
  → yfinance로 3년치 과거 시세 조회 → 공분산 행렬 계산
     │
     ▼
[단계 2: 대안 데이터 주입 — 25~40%]
  US 주식 → SEC EDGAR Form 4 내부자 거래 시그널
    (STRONG_SELL / MODERATE_SELL / NEUTRAL / BUY / NO_DATA)
  KR 주식 → DART 재무공시 (매출액, 영업이익, ROE, 부채비율 등)
  → Redis 캐시에서 즉시 조회 (Beat 스케줄러가 미리 갱신)
     │
     ▼
[단계 3: Gemini 호출 — 40~90%]
  ML 최적화 수치 + 대안 데이터 + 포트폴리오 현황을
  컨텍스트로 주입한 프롬프트 → Gemini 2.0 Flash 호출
  → 자연어 투자 분석 리포트 생성
     │
     ▼
결과: Redis에 저장 → 프론트엔드 폴링으로 수신
```

#### 사용 방법

현재 AI 리포트 요청은 **백엔드 API**를 통해 직접 호출하거나,  
FastAPI의 자동 문서(`/docs`)에서 테스트할 수 있습니다:

1. 브라우저에서 `http://localhost:8000/docs` 접속
2. **`POST /api/v1/ai/reports/portfolio/{portfolio_id}`** 클릭 → Try it out
3. 포트폴리오 UUID 입력 후 Execute
4. 응답으로 받은 `task_id` 복사
5. **`GET /api/v1/ai/reports/tasks/{task_id}`** 로 폴링 → `status: "SUCCESS"` 확인

```json
// 리포트 요청 본문 예시
{
  "user_question": "포트폴리오 리밸런싱 시점이 되었나요? 현재 구성의 위험 요소는?"
}

// 결과 응답 예시
{
  "status": "SUCCESS",
  "result": {
    "report": "...(Gemini가 생성한 자연어 분석 리포트)...",
    "ml_optimization_status": "SUCCESS",
    "alternative_data_status": "sec:2 dart:1",
    "usage": {
      "total_tokens": 15420,
      "cached_tokens": 8200
    }
  }
}
```

> 💡 **Gemini 암시적 캐싱:**  
> 동일한 포트폴리오로 반복 요청 시, 공통 컨텍스트 부분이 자동 캐싱되어  
> 두 번째 요청부터 속도가 빠르고 토큰 비용이 절감됩니다.

---

### 6-5. 밸류체인(공급망) 시각화 지도

상단 내비게이션에서 **`공급망 지도`** 를 클릭하면 Leaflet 기반 세계 지도가 열립니다.

#### 지도 구성 요소

**노드(원형 마커) — 공급망 참여 주체:**

| 색상 | 리스크 레벨 | 의미 |
|------|------------|------|
| 🟢 초록 | LOW | 안정적 공급망 노드 |
| 🟠 주황 | MEDIUM | 주의가 필요한 노드 |
| 🔴 빨강 | HIGH | 고위험 노드 (지정학적 긴장, 자연재해 등) |
| 🟣 보라 | CRITICAL | 즉각 대응 필요 (공급 중단 위험) |

**노드 유형 (클릭 시 팝업에 표시):**

| 아이콘 | 유형 | 설명 |
|--------|------|------|
| 🏢 | COMPANY | 상장 기업 본사 |
| 🏭 | FACTORY | 핵심 생산 공장 |
| ⚓ | PORT | 항구 / 물류 게이트웨이 |
| 📦 | LOGISTICS_HUB | 물류 허브 / 배송 센터 |
| ⛏ | RAW_MATERIAL | 원자재 생산지 |

**에지(선) — 공급망 의존 관계:**
- 선 두께가 굵을수록 의존도(`dependency_score`)가 높음
- 파란 실선: 의존도 40% 이상
- 파란 점선: 의존도 40% 미만 (약한 연결)
- 에지 클릭 시 팝업: 관계 유형, 의존도 %, 연간 거래액

#### 티커 필터 사용법

특정 기업 관련 공급망만 보고 싶을 때:

```
티커 필터 입력창에: AAPL, TSMC, NVDA
→ [필터 적용] 클릭
→ 해당 기업들과 연관된 노드·에지만 표시
```

#### 지정학적 리스크 AI 분석 패널

지도 오른쪽 패널에서 뉴스 텍스트를 입력하면  
Gemini AI가 공급망 파급 효과를 분석합니다:

```
입력 예시:
"대만 해협 긴장 고조로 인해 TSMC의 주요 반도체 생산시설에 
 조업 중단 우려가 제기되고 있습니다. 특히 첨단 3nm 공정 라인의
 가동 차질이 예상되며..."

→ [AI 리스크 분석 요청] 클릭
→ Task ID가 표시됨
→ Celery가 백그라운드에서 분석 처리 (결과는 Redis에 저장)
```

---

### 6-6. 관리자 기능 (Admin)

관리자 계정(role=ADMIN)에서만 상단 내비게이션에 **관리자** 메뉴가 표시됩니다.

**관리자 계정 생성 방법 (초기 설정):**

FastAPI `/docs`에서 직접 수행하거나, psql에서 직접 업데이트:

```sql
-- psql 접속 후 관리자 권한 부여
psql -U postgres investment_db

-- 특정 사용자를 관리자로 승격
UPDATE users SET role = 'ADMIN' WHERE email = 'admin@example.com';
\q
```

**관리자 API 엔드포인트 (`/api/v1/admin/`):**

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /admin/users` | 전체 사용자 목록 조회 (활성/비활성 필터 가능) |
| `GET /admin/users/{id}` | 특정 사용자 상세 조회 |
| `DELETE /admin/users/{id}` | **소프트 딜리트** (is_active=False, DB에서 삭제되지 않음) |
| `PATCH /admin/users/{id}/reactivate` | 비활성 사용자 재활성화 |

> ⚠️ 사용자 삭제는 **논리적 삭제(Soft Delete)** 방식입니다.  
> 데이터베이스에서 실제로 삭제되지 않으며, `is_active` 컬럼만 `False`로 변경됩니다.  
> 이메일은 비활성 계정이라도 재사용이 불가합니다.

---

## 7. API 문서 확인 방법

FastAPI는 자동으로 대화형 API 문서를 생성합니다.  
백엔드가 실행 중인 상태에서 브라우저로 접속하세요:

| 문서 유형 | URL | 특징 |
|----------|-----|------|
| **Swagger UI** | `http://localhost:8000/docs` | 직접 API 테스트 가능 (추천) |
| **ReDoc** | `http://localhost:8000/redoc` | 읽기 전용, 보기 좋음 |

**Swagger에서 인증이 필요한 API 테스트하는 방법:**

1. `POST /api/v1/auth/login` 으로 로그인 → `access_token` 복사
2. 우상단 **Authorize 🔒** 버튼 클릭
3. `Bearer {복사한_토큰}` 입력 (예: `Bearer eyJhbGci...`)
4. 이후 자물쇠 아이콘이 잠긴 API도 자유롭게 테스트 가능

---

## 8. Celery 워커 모니터링 (Flower)

Celery 작업 현황을 웹 대시보드로 확인할 수 있습니다.

```bash
# 새 터미널을 열고
cd ~/Documents/GitHub/Personal-investment-platform
source venv/bin/activate

celery -A app.worker.celery_app flower --port=5555
```

브라우저에서 `http://localhost:5555` 접속:
- 활성 워커 목록 확인
- 대기 중 / 처리 중 / 완료된 작업 확인
- AI 리포트 생성 진행 상황 실시간 모니터링

---

## 9. 자주 발생하는 오류 & 해결법

### 🔴 `ImportError: cannot import name 'getcurrent' from 'greenlet'`

**원인:** Apple Silicon Mac에서 greenlet 버전 충돌  
**해결:**
```bash
source venv/bin/activate
pip install greenlet --force-reinstall
```

---

### 🔴 `sqlalchemy.exc.OperationalError: connection refused (port 5432)`

**원인:** PostgreSQL 서버가 실행되지 않은 상태  
**해결:**
```bash
brew services start postgresql@17
# 상태 확인
brew services list | grep postgresql
```

---

### 🔴 `redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379`

**원인:** Redis 서버가 실행되지 않은 상태  
**해결:**
```bash
brew services start redis
redis-cli ping   # PONG이 출력되면 정상
```

---

### 🔴 `CORS error` — 프론트엔드에서 백엔드 API 호출 실패

**원인:** 백엔드가 실행되지 않았거나 포트가 다름  
**해결:**
1. 터미널 1에서 FastAPI가 8000번 포트로 실행 중인지 확인
2. 프론트엔드 개발 서버가 `http://localhost:5173`으로 실행 중인지 확인  
   (다른 포트로 열면 CORS 차단될 수 있음)
3. Vite 프록시 설정 확인: `frontend/vite.config.ts`의 `/api` → `http://localhost:8000`

---

### 🔴 `alembic.util.exc.CommandError: Can't locate revision identified by...`

**원인:** 마이그레이션 상태 불일치  
**해결:**
```bash
# 현재 마이그레이션 상태 확인
alembic current

# 강제로 최신 버전으로 올리기
alembic upgrade head
```

---

### 🔴 AI 리포트 요청 시 `Task pending` 상태에서 진행되지 않음

**원인:** Celery 워커가 실행되지 않은 상태  
**해결:**
```bash
# 터미널 2에서 Celery 워커 실행 확인
# 아래 명령어로 새로 시작
cd ~/Documents/GitHub/Personal-investment-platform
source venv/bin/activate
celery -A app.worker.celery_app worker --loglevel=info -Q ai_reports,alternative_data,market_data,celery
```

---

### 🔴 yfinance 시세 조회 실패 — `No price data for {ticker}`

**원인:** 잘못된 티커 심볼 입력  
**해결:**
- 미국 주식: `AAPL`, `MSFT` (정확한 영문 심볼)
- 한국 주식 KOSPI: `005930.KS` (.KS 접미사 필수)
- 한국 주식 KOSDAQ: `035720.KQ` (.KQ 접미사 필수)

---

### 🔴 `ModuleNotFoundError` — 패키지를 찾을 수 없음

**원인:** 가상환경이 활성화되지 않은 상태에서 실행  
**해결:**
```bash
# 가상환경 활성화 (프롬프트 앞에 (venv)가 붙어야 함)
source venv/bin/activate
```

---

## 10. 전체 실행 순서 요약 (Quick Start)

```bash
# ── 사전 준비 (최초 1회) ─────────────────────────────────────────

# 인프라 시작
brew services start postgresql@17
brew services start redis

# 프로젝트 루트로 이동
cd ~/Documents/GitHub/Personal-investment-platform

# 가상환경 활성화
source venv/bin/activate

# 패키지 설치 (최초 1회)
pip install -r requirements.txt
pip install greenlet          # Apple Silicon 필수

# 프론트엔드 패키지 설치 (최초 1회)
cd frontend && npm install && cd ..

# .env 파일 생성 및 API 키 설정 (최초 1회)
# → 섹션 3 참고

# DB 마이그레이션 (최초 1회)
alembic upgrade head


# ── 매일 실행 (터미널 3개 열기) ────────────────────────────────

# [터미널 1] 백엔드
cd ~/Documents/GitHub/Personal-investment-platform
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# [터미널 2] Celery 워커
cd ~/Documents/GitHub/Personal-investment-platform
source venv/bin/activate
celery -A app.worker.celery_app worker --loglevel=info -Q ai_reports,alternative_data,market_data,celery

# [터미널 3] 프론트엔드
cd ~/Documents/GitHub/Personal-investment-platform/frontend
npm run dev


# ── 브라우저에서 접속 ────────────────────────────────────────────
# 서비스 URL:    http://localhost:5173
# API 문서:      http://localhost:8000/docs
# Celery 모니터: http://localhost:5555  (Flower 실행 시)
```

---

## 부록 — 서비스 종료 방법

실행 중인 각 터미널에서 `Ctrl + C`를 눌러 종료합니다.  
PostgreSQL과 Redis는 컴퓨터를 껐다가 켜도 자동 실행됩니다.  
자동 실행을 원하지 않으면:

```bash
brew services stop postgresql@17
brew services stop redis
```

---

<div align="center">

**이 플랫폼은 투자 분석 지원 목적으로만 사용됩니다.**  
**실제 매수/매도 기능은 제공하지 않습니다.**

Made with ❤️ | FastAPI · React · Gemini AI · Leaflet

</div>
