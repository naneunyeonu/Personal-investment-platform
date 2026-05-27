# AI 기반 개인 투자 서포트 비서 플랫폼 구축을 위한 아키텍처 및 요구사항 심층 분석 보고서

## 1. 서론: 차세대 핀테크 플랫폼의 진화와 개인 투자 비서의 아키텍처적 의의

과거 밀레니얼 세대의 폭발적인 호응을 이끌어낸 미국 실리콘밸리의 핀테크 기업 로빈후드(Robinhood)와 국내의 토스증권 등은 기존 증권업계의 복잡한 사용자 인터페이스를 혁신하고 수수료 무료 정책을 전면에 내세우며 시장의 판도를 바꾸는 메기 효과를 일으켰다.¹ 이러한 1세대 혁신 플랫폼들은 모바일 트레이딩 시스템(MTS)의 직관성과 접근성을 극대화하는 데 성공했으나, 현대의 개인 투자자들이 직면한 본질적인 문제인 '정보 과부하(Information Overload)'를 해결하는 데에는 여전히 한계를 보이고 있다. 수백만 건의 금융 뉴스와 실시간으로 쏟아지는 글로벌 공시 데이터 속에서, 투자자는 여전히 파편화된 정보를 직접 수집하고 해석하는 데 막대한 시간을 소모하고 있다. 따라서 사용자가 제안한 '웹 환경 기반의 AI 개인 투자 서포트 비서 플랫폼'은 단순한 거래 수단의 제공을 넘어 정보의 수집, 분석, 통찰 도출 과정을 자동화하려는 매우 시의적절하고 고도화된 전략적 목표를 지니고 있다.

본 보고서는 사용자가 명시한 파이썬(Python), FastAPI, PostgreSQL이라는 현대적인 백엔드 기술 스택을 기반으로, 관리자 권한 제어, 다중 통화 포트폴리오 관리, 거대 언어 모델(LLM)을 활용한 자동화 리포트 생성, 그리고 머신러닝 기반의 포트폴리오 최적화 등 복잡한 요구사항들을 통합하기 위한 종합적인 소프트웨어 아키텍처 청사진이다. 특히, 후속 작업으로 예정된 인공지능(Claude) 기반의 '바이브 코딩(Vibe Coding)' 프로세스가 환각 현상 없이 정확한 코드를 생성할 수 있도록, 초기 기획안에서 누락되기 쉬운 데이터베이스 무결성 로직, 거대 언어 모델의 지연 시간 방어 아키텍처, 그리고 대안 데이터(Alternative Data) 파이프라인의 명세를 극한의 깊이로 보완하고 구조화하여 제시한다.

---

## 2. 코어 인프라 및 데이터베이스 아키텍처의 설계와 보안

사용자가 지정한 FastAPI와 PostgreSQL의 조합은 비동기 입출력(I/O) 처리와 데이터의 관계적 무결성을 동시에 확보할 수 있는 금융 데이터 플랫폼의 표준적인 백엔드 구성이다. FastAPI는 비동기 서버 게이트웨이 인터페이스(ASGI)인 Uvicorn 위에서 구동되어 높은 동시성을 자랑하며, 파이썬 기반의 데이터 검증 라이브러리인 Pydantic을 통해 외부 API로부터 유입되는 정형 및 비정형 금융 데이터를 안전하게 직렬화한다.² 그러나 이러한 프레임워크의 장점을 극대화하기 위해서는 관리자 권한 통제와 사용자 데이터 관리에 있어 치밀한 데이터베이스 스키마 설계가 선행되어야 한다.

### 2.1. 인증(Authentication) 및 엄격한 역할 기반 접근 제어(RBAC)

사용자의 두 번째 요구사항인 '사용자 별 로그인 기능과 관리자 계정의 격리'를 구현하기 위해서는 JSON Web Tokens(JWT) 기반의 상태 비저장(Stateless) 인증 아키텍처를 도입해야 한다. python-jose 라이브러리를 활용하여 JWT를 인코딩 및 디코딩하고, passlib를 통해 사용자의 비밀번호를 데이터베이스에 단방향 해싱하여 저장하는 방식이 필수적이다.² 인증 시스템 설계에서 가장 핵심적인 부분은 관리자(Admin)에게 부여된 '사용자 퇴출 권한'의 논리적 한계 설정이다. 관리자는 오직 사용자를 데이터베이스에서 삭제시키는 단일 권한만을 소유하며, 이외의 자산 조회나 거래 기능은 일반 사용자와 동일하게 동작해야 한다.

이를 프론트엔드 환경에서 완벽히 격리하기 위해서는 백엔드 FastAPI에서 발행하는 JWT 페이로드 내부에 role 스코프(Scope)를 명시하고, 관리자 전용 라우터(Router) 엔드포인트에 Depends 의존성 주입을 통해 해당 스코프를 검증하는 로직을 필수적으로 추가해야 한다. 클라이언트 측 웹 환경(예: React 또는 Vue.js)에서는 이 role 값을 기반으로 라우트 가드(Route Guard)를 설정하여, 관리자 계정으로 로그인했을 때만 접근 가능한 숨겨진 관리자 대시보드 페이지를 동적으로 렌더링하도록 설계해야 보안 사고를 원천 차단할 수 있다.

### 2.2. 사용자 퇴출 프로세스와 논리적 삭제(Soft Delete) 아키텍처

관리자가 사용자를 'DB에서 삭제(퇴출)'시키는 기능을 구현함에 있어, 데이터베이스 관점의 물리적 삭제(Hard Delete, `DELETE FROM Users WHERE user_id = X`) 방식은 금융 시스템 설계에서 절대적으로 지양해야 할 치명적인 안티 패턴이다.³ 만약 특정 사용자의 계정이 물리적으로 증발할 경우, 해당 사용자가 과거에 작성한 포트폴리오 벤치마크 데이터, 매수 및 매도 체결 이력, 환율 변환 트랜잭션 기록 등이 의존하고 있는 외부 키(Foreign Key) 제약 조건이 연쇄적으로 붕괴되어 데이터베이스 전체의 참조 무결성(Referential Integrity)이 파괴된다.

따라서 기획 의도인 '퇴출'을 시스템적으로 안전하게 구현하기 위해서는 SQLAlchemy ORM(Object-Relational Mapping)을 활용한 논리적 삭제(Soft Delete) 아키텍처를 도입해야 한다.² 이는 사용자 테이블에 상태를 나타내는 불리언(Boolean) 컬럼이나 삭제 일시를 기록하는 타임스탬프 컬럼을 추가하는 방식으로 작동한다. 관리자가 퇴출 버튼을 누르면 물리적 레코드가 삭제되는 것이 아니라 해당 상태 컬럼의 값이 변경되며, 시스템의 모든 조회 쿼리(Query)는 이 컬럼이 활성화된 레코드만을 반환하도록 전역 필터를 적용받는다. 이를 통해 겉으로는 사용자가 플랫폼에서 완전히 추방된 것처럼 기능하면서도, 백엔드에는 익명화된 거래 데이터가 영구 보존되어 향후 머신러닝 최적화 엔진의 백테스팅을 위한 귀중한 데이터 자산으로 활용될 수 있다.

| 테이블 명 (Table) | 핵심 컬럼 (Columns) | 데이터 타입 (PostgreSQL) | 제약조건 및 시스템 논리 |
|---|---|---|---|
| Users | user_id | UUID | Primary Key, 난수화된 고유 식별자 |
| | role | VARCHAR | USER 또는 ADMIN 구분, JWT 페이로드 연동 |
| | is_active | BOOLEAN | 논리적 삭제 플래그: False 전환 시 로그인 불가 및 퇴출 처리² |
| Portfolios | portfolio_id | UUID | Primary Key, 포트폴리오 그룹핑 |
| | user_id | UUID | Foreign Key (Users), 계정 비활성화 시에도 기록 유지 |
| Transactions | tx_id | UUID | Primary Key, 개별 매수/매도 이력 보관 |
| | execution_exchange_rate | NUMERIC | 체결 당시 환율 저장 (다중 통화 수익률 계산용) |

---

## 3. 벤치마크 통합 및 다중 통화 포트폴리오 엔진 설계

로빈후드나 토스증권이 밀레니얼 세대의 막대한 트래픽을 감당하며 성공할 수 있었던 근본적인 이유는 단순히 수수료를 없앴기 때문만이 아니라, 복잡한 재무 수치를 사용자 친화적인 직관적 인터페이스와 실시간 데이터 동기화 기술로 풀어냈기 때문이다.¹ 사용자가 요구한 보유 종목 추적, 평단가 계산, 현재가 조회 및 원화/달러 변환 기능을 완벽히 구현하기 위해서는 단순한 외부 API 호출을 넘어선 독자적인 자산 평가 엔진이 백엔드에 위치해야 한다.

### 3.1. 국내 및 해외 주식 시장 데이터 파이프라인 연동

포트폴리오의 실시간 현재가를 반영하기 위해서는 타겟 시장에 따라 이원화된 데이터 수집 전략이 필수적이다. 미국 주식 등 글로벌 금융 데이터의 경우 파이썬 데이터 과학 생태계의 표준으로 자리 잡은 yfinance와 pandas-datareader 라이브러리의 결합이 압도적인 효율성을 제공한다.⁴ 이 도구들은 종목의 시초가, 고가, 저가, 종가, 거래량 등의 시계열 데이터를 판다스 데이터프레임(Pandas DataFrame) 객체로 즉각 반환하여, 시스템이 부가적인 전처리 없이 곧바로 통계 분석과 머신러닝 파이프라인에 데이터를 주입할 수 있도록 돕는다.⁷ 다만 야후 파이낸스의 데이터는 API 한도 초과(Rate Limit)나 IP 차단의 위험이 상존하므로⁵, 실시간 호가 연동을 위해서는 Alpaca Broker API와 같이 안정적인 기관급 웹소켓(WebSocket) 스트리밍을 제공하는 솔루션을 병행하여 백업 파이프라인으로 구성해야 한다.³

국내 주식의 경우, 시세 및 체결 데이터를 연동하기 위해 한국투자증권의 KIS Developers 오픈 API를 벤치마킹 데이터 소스로 활용하는 것이 가장 권장된다.⁸ KIS API는 파이썬 환경에서 Oauth2 기반의 접근 토큰을 발급받아 장내 주식 및 채권의 실시간 체결가와 호가를 매우 낮은 지연 시간으로 조회할 수 있는 인터페이스를 제공한다.⁸ 이처럼 이원화된 글로벌 및 로컬 파이프라인은 FastAPI 내부의 어댑터 패턴(Adapter Pattern)을 통해 단일한 인터페이스로 추상화되어야만 향후 데이터 벤더가 변경되더라도 코어 시스템의 붕괴를 막을 수 있다.

### 3.2. 환율 데이터와 다중 통화(Multi-Currency) 회계 처리

보유 종목에 대한 원화와 달러 변환 기능은 시스템 설계에서 가장 복잡한 회계 알고리즘을 요구하는 영역이다. 투자자가 과거 특정 시점에 매수한 해외 주식의 정확한 현재 수익률을 계산하기 위해서는 단순한 주가 상승분(Capital Gain)뿐만 아니라, 매수 시점과 현재 시점 간의 환율 변동으로 인한 환차익 또는 환차손(Exchange Rate Gain/Loss)을 독립적으로 분리하여 계산할 수 있어야 한다.

이를 위해 데이터베이스의 Transactions 테이블에는 매수 체결 단가와 더불어 반드시 '체결 당시의 환율(Execution Exchange Rate)'이 함께 기록되어야 한다. 시스템은 한국은행 OpenAPI나 FRED(연방준비제도 경제 데이터) API를 일괄 작업(Batch Job)으로 매일 호출하여 기준 환율 테이블을 데이터베이스 내부에 동기화해야 한다. 사용자가 포트폴리오 대시보드에 접속하면, 시스템은 개별 종목의 체결 단가와 매수 당시 환율을 곱한 원금 총액과, 실시간 현재가와 실시간 환율을 곱한 현재 평가액을 비교 연산하여 순수 주가 변동에 의한 수익률과 환율 변동에 의한 수익률을 시각적으로 분리하여 제공한다. 이는 토스증권 등에서 제공하는 직관적 사용자 경험을 달성하는 핵심 백엔드 메커니즘이다.

---

## 4. 정보 과부하 해소를 위한 AI 비서 및 Gemini 최적화 아키텍처

본 플랫폼의 가장 큰 차별점은 사용자가 직접 각종 증권 사이트와 뉴스를 순회하며 정보를 수집하는 시간을 인공지능을 통해 획기적으로 줄이는 데 있다. 기업의 실적 발표(어닝스 콜), 증권사 애널리스트 리포트, 그리고 환율 변동과 같은 거시 경제 지표를 종합하여 개인화된 시장 리포트를 자동으로 작성하기 위해 구글의 Gemini API를 연동하는 것은 매우 강력한 접근이다. 그러나 거대 언어 모델의 본질적인 지연 시간(Latency) 제약과 토큰 비용 문제를 아키텍처 단계에서 제어하지 못한다면 서비스 상용화는 불가능에 가깝다.

### 4.1. LLM 대기 시간의 역학과 비동기 처리 큐(Task Queue)

개별 투자자의 포트폴리오를 기반으로 시장 리포트를 작성하는 작업은 수천에서 수만 단어의 텍스트를 인공지능 모델에 전송하고 처리 결과를 기다려야 하는 엄청난 컴퓨팅 부하를 유발한다. 생성형 AI 에이전트의 총 응답 지연 시간은 공급자 서버의 대기 시간, 모델이 프롬프트를 처리하고 첫 토큰을 내뱉는 데 걸리는 시간(Time To First Token), 그리고 모델의 생성 속도와 출력 토큰 수의 결합으로 계산되는 엄격한 물리적 한계를 지닌다.¹¹ 특히 입력 프롬프트의 길이가 길어질수록 TTFT는 기하급수적으로 증가하여, 10만 토큰의 문서를 주입할 경우 첫 응답을 받기까지 6.5초에서 8초 이상, 50만 토큰에 이를 경우 최대 24초에 달하는 지연이 발생한다.¹¹

FastAPI는 비동기 처리 프레임워크이지만, 메인 이벤트 루프에서 이러한 장시간 대기 I/O 요청을 무방비하게 기다릴 경우 시스템 전체의 병목 현상이 발생하여 다른 사용자의 단순 시세 조회까지 마비된다. 따라서 AI 비서의 리포트 작성 기능은 반드시 **Celery와 같은 파이썬 기반 분산 작업 큐(Task Queue)와 Redis 기반의 메시지 브로커를 통해 백그라운드 워커(Background Worker) 노드로 오프로딩(Offloading) 되어야 한다.** 사용자가 요약 요청을 보내면 백엔드는 즉시 작업 ID를 반환하고, 백그라운드에서 Gemini API 통신을 마친 뒤 서버 센트 이벤트(Server-Sent Events, SSE)나 웹소켓을 통해 프론트엔드로 요약본을 밀어넣는 이벤트 주도(Event-Driven) 설계가 필수적이다.

### 4.2. 극단적 비용 절감을 위한 Gemini 컨텍스트 캐싱(Context Caching) 전략

기획자가 적극 고려 중인 '어닝스 콜 및 증권사 리포트 AI 자동 요약' 기능은 기업당 수백 페이지에 달하는 방대한 자연어 데이터를 포함한다. 수천 명의 사용자가 애플(AAPL)의 동일한 분기 실적 보고서를 기반으로 질문을 던질 때마다 매번 수만 토큰의 문서를 Gemini 모델에 반복 전송하는 것은 초과 비용의 주원인이 된다. 이를 방지하기 위해 구글이 제공하는 '컨텍스트 캐싱(Context Caching)' 기술을 시스템 아키텍처 중심에 배치해야 한다.¹²

컨텍스트 캐싱은 대규모 초기 컨텍스트를 캐시 객체로 모델 서버에 업로드해 두고 이후의 짧은 요청에서 이를 재활용하는 기술로, 스토리지 보존 시간(TTL) 기반의 과금이 추가되지만 입력 토큰 비용을 최대 90%까지 극적으로 할인해 준다.¹² 특히 100명의 사용자가 5만 토큰 분량의 동일한 기업 지식 베이스에 하루 15번씩 질의한다고 가정할 때, 캐싱을 적용하지 않으면 일 38달러의 비용이 발생하지만 캐싱을 적용하면 스토리지 비용을 포함해 일 1.37달러로 무려 96%의 비용을 절감할 수 있다는 명확한 경제적 이점이 존재한다.¹⁴

Gemini 생태계는 개발자의 편의를 위해 두 가지 캐싱 계층을 제공하며, 아키텍처 설계 시 목적에 맞게 혼용해야 한다.

- **암시적 캐싱(Implicit Caching)**: 시스템이 자동으로 접두사(Prefix) 유사도를 판별하여 비용을 절감해 주는 방식.¹² Gemini 2.5 Flash 모델 기준 1024 토큰 이상, Pro 모델 기준 4096 토큰 이상의 프롬프트에서 작동하므로¹³, 프롬프트를 구성할 때 항상 기업의 기본 정보와 AI의 역할(Persona) 지시문을 **프롬프트 맨 앞부분(Beginning)에 고정 배치**하고 사용자 개인의 보유 비중이나 질문을 맨 뒷부분에 추가하는 '프롬프트 구조화' 로직이 백엔드 코드에 반영되어야 한다.¹⁵

- **명시적 캐싱(Explicit Caching)**: 어닝스 콜 스크립트 전문과 같은 초거대 문서에 대해 수동으로 TTL을 지정하여 캐시 객체를 생성하는 방식.¹² 실적 발표 시즌에 다수의 사용자가 몰릴 때 백엔드 성능을 지탱하는 핵심 안전장치 역할을 수행한다.

| 기능적 요구사항 (Requirement) | 적용 대상 리소스 유형 | 권장 Gemini 캐싱 아키텍처 | 비용 절감 및 지연 시간 단축 효과 |
|---|---|---|---|
| 공통 지식 요약 | 분기별 어닝스 콜 대본, 증권사 리포트 전문, 거시 경제 및 환율 리포트 | 명시적 캐싱 (Explicit Caching) | 대형 문서를 TTL 1시간 단위 캐시 객체로 사전 로드하여 다수 사용자의 질의 응답 시 90% 수준의 토큰 비용 할인 보장 및 지연 시간 혁신적 제거.¹¹ |
| 개인화된 분석 리포트 | 사용자의 거래 이력, 개별 평단가 기준의 매도/매수 질문, 개인화 뉴스 피드 | 암시적 캐싱 (Implicit Caching) | 1024 토큰 이상의 기본 시스템 프롬프트(투자 비서 페르소나 및 경제 상식)를 프롬프트 상단에 배치하여 자동화된 비용 절감 혜택 유도.¹³ |

---

## 5. 포트폴리오의 진화: 머신러닝 기반 자동 최적화 파이프라인

사용자가 적극적으로 채택을 고려 중인 '머신러닝(ML)을 활용한 더 나은 인사이트 도출' 기능은 단순한 챗봇 형태의 비서를 넘어 전문 퀀트(Quant) 투자자 수준의 자산 배분 조언을 가능하게 하는 킬러 피처(Killer Feature)다. 거대 언어 모델은 자연어 처리와 추론에는 능하지만, 방대한 과거 수익률 배열을 기반으로 복잡한 공분산 행렬을 계산하여 최적의 비율을 도출하는 수리적 연산에는 치명적인 환각(Hallucination) 현상을 동반한다. 따라서 AI 비서의 조언에 수학적 신뢰성을 부여하기 위해서는 언어 모델 호출 이전에 검증된 머신러닝 파이프라인을 선행 구동시키는 **하이브리드 설계**가 요구된다.

### 5.1. 최적화 라이브러리의 도입과 수리적 모델링

이를 구현하기 위해 파이썬 생태계의 대표적인 오픈소스 포트폴리오 최적화 라이브러리인 **PyPortfolioOpt**와 **Riskfolio-Lib**의 백엔드 통합을 제안한다.¹⁶ 이 라이브러리들은 사이킷런(scikit-learn) 기반의 강력한 수치 연산 능력을 바탕으로 투자자의 포트폴리오를 다각도로 스트레스 테스트(Stress Test)하고 미세 조정(Fine-tune)할 수 있다.¹⁸

시스템이 구동되는 백엔드 파이프라인 프로세스는 다음과 같이 설계되어야 한다:
1. 사용자가 포트폴리오 탭에 진입하면, 시스템은 yfinance를 통해 해당 종목들의 과거 3년간 일간 변동성 데이터를 데이터프레임으로 추출한다.⁶
2. 추출된 데이터는 Riskfolio-Lib로 전달되어 4가지 주요 목적 함수(Objective Functions)에 대한 최적화를 수행한다:
   - **최소 위험(Minimum Risk)**: 전체 포트폴리오의 변동성을 가장 낮게 통제
   - **최대 수익률(Maximum Return)**: 가장 높은 기대 수익을 추구
   - **최대 효용 함수(Maximum Utility Function)**: 투자자의 주관적 효용 극대화
   - **최대 위험 조정 수익률(Maximum Risk Adjusted Return Ratio)**: 켈리 베팅 기준(Kelly Criterion) 기반

### 5.2. 블랙-리터만 모형과 계층적 클러스터링(HRP)의 융합

단순한 과거 수익률 기반의 평균-분산 최적화(Mean-Variance Optimization)는 특정 종목이 과거에 우연히 높은 수익을 기록했을 경우 해당 종목에 포트폴리오 비중을 극단적으로 몰아버리는 한계점이 존재한다.¹⁷ 이러한 코너 솔루션(Corner Solution) 문제를 극복하기 위해, 머신러닝 파이프라인은 자산 간의 상관관계를 머신러닝 클러스터링(Clustering) 기법으로 묶어 위험을 분산시키는 **계층적 리스크 패리티 알고리즘**이나 **블랙-리터만(Black-Litterman) 자산 배분 모델**을 차용해야 한다.¹⁷

백엔드 파이프라인이 이러한 복잡한 수리적 최적화 연산을 완료하여 정량적인 최적 비중 데이터를 산출하면, 이 JSON 데이터 객체는 최종적으로 Gemini API의 프롬프트에 주입된다. 이를 통해 AI 비서는 수학적 모델 시뮬레이션 결과에 기반한 논리적이고 빈틈없는 자연어 브리핑을 완성하게 된다.

---

## 6. 대안 데이터(Alternative Data) 추적 시스템 설계와 통합

기관 투자자와 개인 투자자 간의 정보 비대칭을 허물기 위해 기획자가 추가 기능으로 제시한 내부자 거래(Insider Trading) 추적, 기관 대량 매매(Block Trade) 감지, 그리고 전자공시시스템(DART) 기반 정보 수집은 개인 투자 비서의 정보력을 기관 수준으로 끌어올리는 핵심 동력이다.

### 6.1. SEC EDGAR 기반 내부자 거래 추적 파이프라인

기업 내부 사정에 정통한 최고경영자(CEO), 임원진, 그리고 대규모 지분을 보유한 대주주의 매매 동향은 향후 주가 방향성을 예측하는 선행 지표 역할을 한다. 미국의 경우 1934년 제정된 증권거래법(Securities Exchange Act of 1934) 제16조에 의거하여, 기업 내부자는 자사주 거래 시 지체 없이 증권거래위원회(SEC)의 EDGAR 시스템에 Form 3, Form 4, Form 5 양식을 제출하여 변경 사항을 공시해야 할 법적 의무를 지닌다.²¹

따라서 이 기능을 플랫폼에 이식하기 위해서는 새로운 Form 4 공시가 발표된 후 평균 300밀리초(ms) 이내에 데이터를 추출하고 색인하여 RESTful API 형식으로 제공하는 **sec-api.io** 또는 **eodhd.com**과 같은 전문 서드파티 인프라의 도입이 필수적이다.²⁴

### 6.2. DART API를 활용한 국내 상장기업 재무 공시 파싱 로직

미국 주식에 SEC 데이터가 있다면, 국내 상장기업 분석을 위해서는 금융감독원이 제공하는 **전자공시시스템(Open DART) API** 연동이 요구된다.²⁶ Open DART API는 특정 상장 기업의 현황, 지배구조 정보뿐만 아니라 분기 및 반기별 재무상태표(BS), 손익계산서(IS), 현금흐름표(CF), 포괄손익계산서(CIS) 등 핵심 재무제표 정보를 일괄적으로 제공한다.²⁷

---

## 7. 심층 지정학적 리스크 분석: 밸류체인(공급망) 시각화 지도 구축

초연결 사회의 금융 시장에서 특정 기업의 주가는 자체 실적만으로 결정되지 않는다. 부품을 조달하는 원자재 공급망(후방 산업)이나 완제품을 유통하는 물류망(전방 산업) 중 단 한 곳의 노드(Node)만 멈춰도 연쇄적인 파급 효과가 발생한다. 기획자가 제시한 '공급망 파급 효과 시각화 지도'는 이러한 지정학적, 물리적 리스크를 실시간으로 탐지하여 투자자에게 경고하는 고도화된 기능이다.

### 7.1. 공급망 매핑과 관계형 데이터베이스 구조

각 상장 기업 간의 매입/매출 의존도를 노드(개별 기업 또는 공장 위치)와 에지(기업 간의 물류 흐름 관계)의 그래프 구조로 변환하여 저장해야 한다. 방대한 데이터는 일반적인 RDBMS 테이블 구조만으로는 쿼리 속도 저하를 유발할 수 있으므로, FastAPI와 통신하는 별도의 **그래프 데이터베이스(예: Neo4j)** 레이어를 추가하는 것도 장기적으로 고려해 볼 만한 설계안이다.

### 7.2. 대화형 지도(Interactive Map) 및 네트워크 흐름 렌더링

수집된 밸류체인 데이터는 백엔드의 API를 통해 프론트엔드로 전달되어 시각적으로 직관적인 형태를 갖추게 된다. 공급망 시각화 대시보드를 구축하기 위해서는 React 생태계와 호환되는 **Leaflet.js**³⁴ 프레임워크나 더욱 고성능의 렌더링을 지원하는 **Mapbox API**³⁵ 라이브러리의 연동이 필수적이다.

---

## 8. 바이브 코딩(Vibe Coding)을 위한 시스템 명세와 프롬프팅 전략

본 문서에 담긴 아키텍처적 통찰과 보완된 설계안은 이어지는 거대 언어 모델(Claude 등)과의 대화형 코딩, 이른바 '바이브 코딩'을 성공적으로 수행하기 위한 절대적인 설계 명세서(Specification)로 작용한다.

**핵심 지시 사항:**

1. **데이터베이스 계층의 엄격성**: SQLAlchemy ORM을 활용하여 Users 모델을 생성할 때, 관리자의 물리적 DELETE 쿼리를 원천 차단하고 반드시 `is_active`를 `False`로 변이시키는 논리적 삭제(Soft Delete) 메서드만을 작성한다. Transactions 모델에는 `currency_code`와 `execution_exchange_rate` 컬럼을 필수로 포함한다.

2. **금융 데이터 수집 파이프라인의 모듈화**: FastAPI 라우터 내부에 yfinance나 KIS Developers API, DART API 호출 로직을 하드코딩하지 않는다. 의존성 주입(Dependency Injection)과 팩토리 패턴(Factory Pattern)을 활용하여 데이터 제공자를 추상화(Abstraction)하는 구조로 코드를 작성한다.

3. **Gemini API 비용 최적화 캐싱 메커니즘**: 
   - 대규모 문서 요약 시 → **명시적 캐싱(Explicit Caching)**: 특정 TTL(예: 1시간)을 명시한 캐시 객체 생성 코드 작성¹²
   - 개별 사용자 대화 세션 시 → **암시적 캐싱(Implicit Caching)**: 시스템 프롬프트를 요청 메시지의 가장 앞에 배치하여 1024 토큰 이상의 Prefix 유사도 조건 충족¹³

---

## 참고 자료

1. [이슈분석]카카오페이증권-토스증권의 벤치마킹 '로빈후드' - 전자신문, https://www.etnews.com/20201123000191
2. Building a Stock Market API with FastAPI and Python - C# Corner, https://www.c-sharpcorner.com/article/building-a-stock-market-api-with-fastapi-and-python/
3. Build Your Own Brokerage With FastAPI - Part 2 - Alpaca, https://alpaca.markets/learn/build-your-own-brokerage-with-fastapi-part-2
4. Yahoo Finance — pandas-datareader 0.10.0 documentation, https://pandas-datareader.readthedocs.io/en/latest/readers/yahoo.html
5. yfinance - PyPI, https://pypi.org/project/yfinance/
6. Using Pandas_DataReader to Collect Free, Historical Stock Market Price/Dividend Data, https://www.reddit.com/r/Python/comments/ut6xxu/
7. Finance Data with Python - Analytics Vidhya | Medium, https://medium.com/analytics-vidhya/finance-data-with-python-29e02ce1fae0
8. 한국투자증권 REST API, https://devthomas.tistory.com/95
9. API 문서 - KIS Developers, https://apiportal.koreainvestment.com/apiservice
10. Soju06/python-kis - GitHub, https://github.com/Soju06/python-kis
11. Architecting Low-Latency, Low-Cost AI Agents, https://the-rogue-marketing.github.io/architecting-low-latency-low-cost-ai-agents-with-prompt-caching-and-context-hydration/
12. Gemini API optimization and inference | Google AI for Developers, https://ai.google.dev/gemini-api/docs/optimization
13. Context caching - generateContent API - Google AI for Developers, https://ai.google.dev/gemini-api/docs/caching
14. Lowering Your Gemini API Bill: A Guide to Context Caching | Medium, https://rawheel.medium.com/lowering-your-gemini-api-bill-a-guide-to-context-caching-0e1f4d0cb3f8
15. Gemini 2.5 Models now support implicit caching - Google Developers Blog, https://developers.googleblog.com/gemini-2-5-models-now-support-implicit-caching/
16. Riskfolio-Lib 7.3, https://riskfolio-lib.readthedocs.io/
17. PyPortfolioOpt - GitHub, https://github.com/PyPortfolio/PyPortfolioOpt
18. skfolio: Portfolio Optimization in Python, https://skfolio.org/
19. Installation — PyPortfolioOpt 1.5.4 documentation, https://pyportfolioopt.readthedocs.io/
20. PyPortOptimization - PMC, https://pmc.ncbi.nlm.nih.gov/articles/PMC12370148/
21. Insider Trading Data Analysis - Edgar Online, https://www.edgar-online.com/data-products/insider-data
22. Insider Transactions Data Sets - SEC.gov, https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets
23. Securities and Exchange Commission - Insider Transactions Data Sets, https://catalog.data.gov/dataset/insider-transactions-data-sets
24. Insider Trading Data from SEC Form 3, 4, 5 Filings - SEC API, https://sec-api.io/docs/insider-ownership-trading-api
25. Insider Transactions API (Sec "Form 4") - EODHD, https://eodhd.com/financial-apis/insider-transactions-api
26. DART open API 이용해서 데이터 쉽게 수집하기 - 티스토리, https://saycode.tistory.com/11
27. OPENDART API를 활용하여 파이썬으로 기업 정보 검색하기, https://jgws.tistory.com/entry/
28. [파이썬 퀀트] 18강 - DART API를 이용해 공시정보 및 재무제표 수집하기 - YouTube, https://www.youtube.com/watch?v=MzesCjCQ4zQ
29. 파이썬으로 DART에서 재무제표 수집하기 - 네이버 프리미엄콘텐츠
30. [10분] OpenDartReader 재무제표 수집 - YouTube, https://www.youtube.com/watch?v=60T9JXp0Zhw
31. What is Supply Chain Mapping? - Sourcemap, https://www.sourcemap.com/blog/what-is-supply-chain-mapping
32. 7 Best Supply Chain Mapping Software Solutions in 2026 - Tradeverifyd, https://tradeverifyd.com/resources/best-supply-chain-mapping-software
33. How to use automated Supply Chain Map updates with Log-hub APIs?, https://log-hub.com/playbook-automated-supply-chain-map-updates/
34. SupplyChainVisualizer - GitHub, https://github.com/mariarodr1136/SupplyChainVisualizer
35. Data visualization techniques to tighten up your supply chain - Mapbox, https://www.mapbox.com/blog/data-visualization-techniques-to-tighten-up-your-supply-chain
