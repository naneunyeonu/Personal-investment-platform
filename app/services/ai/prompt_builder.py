"""
Gemini 프롬프트 구조화 빌더

암시적 캐싱(Implicit Caching) 설계 원칙 (architecture_plan.md §4.2):
─────────────────────────────────────────────────────────────────────
Gemini 2.5 Flash 기준, 1024 토큰 이상의 Prefix가 이전 요청과 동일하면
자동으로 캐시 히트 적용 → 입력 토큰 비용 대폭 절감.

구조 규칙:
  [1] SYSTEM_PERSONA (고정 Prefix) ← 항상 맨 앞 고정
  [2] MARKET_CONTEXT (경제 상식/시장 배경) ← 고정 Prefix 연장
  [3] PORTFOLIO_DATA (사용자별 가변 데이터) ← 뒤에 추가
  [4] USER_QUESTION (사용자 질문) ← 맨 뒤

[1]+[2]가 요청마다 동일하게 유지되어야 Prefix 유사도 조건 충족.
사용자별로 달라지는 [3][4]는 반드시 맨 뒤에 배치.
─────────────────────────────────────────────────────────────────────
"""

from dataclasses import dataclass
from decimal import Decimal

# ── 고정 시스템 페르소나 (암시적 캐싱 Prefix 역할) ─────────────────────────
# 이 문자열은 모든 사용자 요청에서 동일하게 유지되어야 함.
# 변경 시 캐시 무효화 → 최대한 안정적으로 유지.
INVESTMENT_ADVISOR_PERSONA = """
당신은 'ARIA(AI Research & Investment Advisor)'입니다.
CFA(공인재무분석사) 및 FRM(금융리스크관리사) 자격을 보유한 15년 경력의 퀀트 투자 전문가로,
대한민국 투자자를 위한 개인 맞춤형 포트폴리오 분석과 리스크 관리를 전문으로 합니다.
글로벌 자산운용사(AUM 5조 원 이상) 출신으로, 국내외 주식·채권·ETF·대체투자 전반에 걸친
실전 포트폴리오 운용 경험을 갖추고 있습니다.

[플랫폼 정의 및 핵심 제약]
이 플랫폼은 실제 주식 매수/매도(Trading Execution)를 지원하지 않는 분석/서포트 전용 플랫폼입니다.
사용자는 보유 중인 자산(종목 티커, 수량, 매수 평단가, 매수 당시 환율)을 직접 수동 등록하며,
플랫폼은 외부 시장 데이터를 연동하여 현재가 반영, 환율 변환, AI 리포트 등 투자 분석 기능만을 제공합니다.
어떠한 경우에도 실제 매수/매도 주문 체결 관련 안내나 권유는 제공하지 않습니다.

[핵심 분석 원칙]
1. 분석 전용: 실제 매수/매도 주문을 체결하거나 권유하는 행위는 절대 하지 않습니다.
   모든 분석은 투자 참고 자료로만 활용됩니다.
2. 수치 기반: 모든 의견은 반드시 수리적으로 계산된 데이터에 근거합니다.
   활용 지표: 수익률(%), 변동성(σ), 샤프 비율, 최대 낙폭(MDD), 베타(β), 상관계수(ρ)
3. 다중 통화 인식: 원화(KRW)와 달러(USD) 자산을 구분하여
   순수 주가 수익률(price_return)과 환율 변동 수익률(fx_return)을 항상 분리하여 설명합니다.
   총 수익률 = (1 + price_return) × (1 + fx_return) - 1
4. 리스크 우선: 수익 가능성과 함께 반드시 리스크 요인(변동성, 유동성, 집중도, 시장/신용 리스크)을 병기합니다.
5. 한국어 응답: 모든 응답은 명확하고 친절한 한국어로 작성하되, 금융 전문 용어는 한글+영문 병기합니다.
6. 데이터 한계 인정: yfinance 또는 KIS API 데이터 기준이며, 지연/오류 가능성을 인지합니다.

[응답 형식 표준]
■ 핵심 요약 (3줄 이내)
■ 포트폴리오 성과 분석
  - 수익률 분해: 주가 기여 vs 환율 기여
  - 섹터/지역 집중도 분석
■ 리스크 평가
  - 주요 리스크 요인 (최대 3개)
  - 개선 방향 제언 (분석 관점, 매매 권유 아님)
■ 면책 고지 (필수 포함)
  "본 분석은 투자 참고 자료이며 실제 투자 결정의 책임은 투자자 본인에게 있습니다."

[분석 가능 영역]
- 포트폴리오 수익률 분해 및 기여도 분석
- 섹터/지역 배분 검토 및 집중 리스크 경고
- 개별 종목 기본 분석 (PER, PBR, ROE 등 펀더멘털)
- 거시경제 지표 연동 분석 (금리, 환율, 유가)
- 내부자 거래 패턴 해석 (SEC Form 4, DART 공시)
- 포트폴리오 최적화 결과 해설 (ML 모델 산출값 기반)

[절대 금지 사항]
- "지금 당장 사세요/파세요" 같은 단정적 매매 권유 표현
- 특정 가격 목표치(Target Price)의 단정적 제시
- 검증되지 않은 수익률 보장 주장
- 개인 정보(주민번호, 계좌번호 등) 요청
- 플랫폼 범위를 벗어난 실제 주문 체결 안내

[핵심 금융 분석 프레임워크]
▶ 수익률 분해 공식 (다중 통화 포트폴리오):
  - 원화 투자원금: P0 × Q × E0 (매수 단가 × 수량 × 매수 당시 환율)
  - 현재 원화 평가액: P1 × Q × E1 (현재가 × 수량 × 현재 환율)
  - 주가 수익률: (P1 - P0) / P0
  - 환율 수익률: (E1 - E0) / E0
  - 복합 총 수익률: (1 + 주가수익률) × (1 + 환율수익률) - 1
  - KRW 자산: E0 = E1 = 1.0 → 환율 수익률 = 0

▶ 포트폴리오 최적화 기준:
  - 최소 분산 포트폴리오(MVP): min σ²(w) s.t. Σwi=1
  - 최대 샤프 비율(MSR): max [E(Rp) - Rf] / σ(Rp)
  - 블랙-리터만 모형: 시장 균형 수익률 + 투자자 뷰 결합
  - 계층적 리스크 패리티(HRP): 클러스터링 기반 위험 균등 배분

▶ 리스크 지표 해석 기준:
  - 연간 변동성 < 15%: 저위험 / 15~25%: 중위험 / 25% 이상: 고위험
  - 샤프 비율 < 0.5: 불량 / 0.5~1.0: 양호 / 1.0 이상: 우수
  - 최대 낙폭(MDD) < 10%: 안정 / 10~30%: 주의 / 30% 이상: 고위험
  - 베타(β) < 0.8: 방어적 / 0.8~1.2: 시장 중립 / 1.2 이상: 공격적

▶ 섹터 분류 (GICS 기준):
  정보기술, 헬스케어, 금융, 임의소비재, 필수소비재,
  산업재, 에너지, 소재, 유틸리티, 부동산, 통신서비스

▶ 거시경제 지표 연동:
  - 금리 상승 환경: 성장주 밸류에이션 압박, 배당주·가치주 상대적 유리
  - 달러 강세: 수출 기업 실적 개선, 원자재 수입 비용 상승
  - 유가 상승: 에너지 섹터 수혜, 항공·화학 비용 부담
  - VIX 30 이상: 시장 공포 구간, 방어적 자산 비중 확대 고려

[데이터 소스 신뢰도]
- yfinance (Yahoo Finance): 글로벌 주식 시세, 15~20분 지연 가능
- KIS Developers API: 국내 주식 실시간 시세
- SEC EDGAR Form 4: 미국 내부자 거래 공시 (300ms 이내 업데이트)
- Open DART API: 국내 상장기업 재무제표 및 공시
- 환율: yfinance KRW=X → exchangerate-api.com fallback (5분 캐시)
""".strip()

MARKET_CONTEXT_TEMPLATE = """
[현재 시장 환경]
- 기준 환율: 1 USD = {usd_krw:.0f} KRW
- 환율 출처: {rate_source}
- 분석 기준 시각: {analysis_time}

[플랫폼 정책]
이 플랫폼은 실제 주문 체결 기능이 없는 분석/서포트 전용 플랫폼입니다.
모든 데이터는 사용자가 수동으로 입력한 보유 내역과 실시간 시세를 기반으로 합니다.
""".strip()


@dataclass
class PortfolioContext:
    """프롬프트에 주입될 포트폴리오 데이터 구조체."""
    portfolio_name: str
    total_cost_krw: Decimal
    total_value_krw: Decimal
    total_return_pct: Decimal
    price_contribution_krw: Decimal
    fx_contribution_krw: Decimal
    usd_krw_rate: Decimal
    rate_source: str
    holdings_summary: list[dict]         # 종목별 요약
    optimization_result: dict | None     # ML 최적화 결과 (옵션)
    alternative_data: dict | None = None # 대안 데이터: SEC EDGAR + DART (옵션)


def build_portfolio_report_prompt(
    context: PortfolioContext,
    user_question: str,
    analysis_time: str,
) -> list[dict]:
    """
    암시적 캐싱 최적화 프롬프트 배열 생성.

    반환 구조 (순서 엄격 준수):
    [
        {"role": "user", "parts": [PERSONA + MARKET_CONTEXT]},  ← 고정 Prefix
        {"role": "model", "parts": ["알겠습니다. 분석을 시작하겠습니다."]},  ← 캐시 앵커
        {"role": "user", "parts": [PORTFOLIO_DATA + USER_QUESTION]},  ← 가변
    ]

    첫 번째 user 메시지의 PERSONA+MARKET_CONTEXT가 캐시 키로 작동.
    1024 토큰 이상 유지 시 Gemini 자동 캐시 히트.
    """
    # ── [1][2] 고정 Prefix (캐시 히트 대상) ───────────────────────────────
    market_ctx = MARKET_CONTEXT_TEMPLATE.format(
        usd_krw=float(context.usd_krw_rate),
        rate_source=context.rate_source,
        analysis_time=analysis_time,
    )
    fixed_prefix = f"{INVESTMENT_ADVISOR_PERSONA}\n\n{market_ctx}"

    # ── [3] 포트폴리오 데이터 (사용자별 가변) ─────────────────────────────
    holdings_text = _format_holdings(context.holdings_summary)
    opt_text = _format_optimization(context.optimization_result)
    alt_text = _format_alternative_data(context.alternative_data)

    portfolio_data = f"""
[포트폴리오: {context.portfolio_name}]

■ 전체 성과 요약
- 투자원금 (원화 환산): {context.total_cost_krw:,.0f} KRW
- 현재 평가액 (원화 환산): {context.total_value_krw:,.0f} KRW
- 미실현 손익: {context.total_value_krw - context.total_cost_krw:+,.0f} KRW
- 총 수익률: {context.total_return_pct:+.2f}%
  ├ 주가 변동 기여: {context.price_contribution_krw:+,.0f} KRW
  └ 환율 변동 기여 (환차익/환차손): {context.fx_contribution_krw:+,.0f} KRW

■ 보유 종목 상세
{holdings_text}
{opt_text}
{alt_text}
""".strip()

    # ── [4] 사용자 질문 (맨 뒤에 배치) ────────────────────────────────────
    final_user_message = f"{portfolio_data}\n\n[사용자 질문]\n{user_question}"

    # ── 프롬프트 배열 조립 ─────────────────────────────────────────────────
    return [
        {
            "role": "user",
            "parts": [fixed_prefix],
        },
        {
            # 캐시 앵커 역할 — 모델이 페르소나를 인지했음을 확인하는 짧은 응답
            "role": "model",
            "parts": ["안녕하세요! ARIA입니다. 포트폴리오 분석을 시작하겠습니다."],
        },
        {
            "role": "user",
            "parts": [final_user_message],
        },
    ]


def build_document_summary_prompt(
    document_text: str,
    document_type: str,
    ticker: str | None = None,
) -> list[dict]:
    """
    명시적 캐싱(Explicit Caching) 대상 — 초거대 문서 요약 프롬프트.
    어닝스 콜 대본, 증권사 리포트 등 대형 문서에 사용.
    실제 캐시 객체 생성은 gemini_service.py에서 처리.
    """
    fixed_prefix = INVESTMENT_ADVISOR_PERSONA
    ticker_context = f"대상 종목: {ticker}\n" if ticker else ""

    return [
        {
            "role": "user",
            "parts": [fixed_prefix],
        },
        {
            "role": "model",
            "parts": ["안녕하세요! ARIA입니다. 문서 분석을 시작하겠습니다."],
        },
        {
            "role": "user",
            "parts": [
                f"{ticker_context}"
                f"문서 유형: {document_type}\n\n"
                f"[문서 전문]\n{document_text}\n\n"
                "위 문서를 투자자 관점에서 핵심만 요약해 주세요. "
                "실적 하이라이트, 가이던스, 리스크 요인을 섹션별로 정리해 주세요."
            ],
        },
    ]


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _format_holdings(holdings: list[dict]) -> str:
    if not holdings:
        return "  (보유 종목 없음)"
    lines = []
    for h in holdings:
        price_r = h.get("price_return_pct", 0)
        fx_r = h.get("fx_return_pct", 0)
        total_r = h.get("total_return_pct", 0)
        lines.append(
            f"  • {h['ticker']} ({h.get('name', '-')})\n"
            f"    수량: {h['quantity']}, 평단: {float(h['avg_cost']):,.2f} {h['currency']}\n"
            f"    현재가: {float(h['current_price']):,.2f} | "
            f"주가수익률: {price_r:+.2f}% | 환수익률: {fx_r:+.2f}% | 총: {total_r:+.2f}%"
        )
    return "\n".join(lines)


def _format_optimization(opt_result: dict | None) -> str:
    if not opt_result:
        return ""
    return f"""

■ ML 포트폴리오 최적화 결과 (PyPortfolioOpt)
{opt_result.get('summary', '최적화 데이터 없음')}
""".strip()


def _format_alternative_data(alt_data: dict | None) -> str:
    """
    대안 데이터(Alternative Data) 프롬프트 섹션 생성.

    architecture_plan.md §6:
      - SEC EDGAR Form 4: 내부자 거래 패턴 → 선행 지표 해석
      - DART 재무공시: 핵심 재무지표 → AI의 펀더멘털 분석 기반

    AI가 "내부자 매도 시그널이 감지되었으므로..." 형태의 근거 있는 브리핑 생성.
    """
    if not alt_data:
        return ""

    sections = []

    # SEC EDGAR 내부자 거래 데이터
    sec_data: dict = alt_data.get("sec_insider", {})
    if sec_data:
        sections.append("\n■ 대안 데이터 (Alternative Data)")
        for ticker, sec_info in sec_data.items():
            summary = sec_info.get("summary", "")
            if summary:
                sections.append(summary)

    # DART 재무공시 데이터
    dart_data: dict = alt_data.get("dart_financials", {})
    if dart_data:
        if not sections:
            sections.append("\n■ 대안 데이터 (Alternative Data)")
        for ticker, dart_info in dart_data.items():
            summary = dart_info.get("summary", "")
            if summary:
                sections.append(summary)

    return "\n".join(sections) if sections else ""


# ─────────────────────────────────────────────────────────────────────────────
# 지정학적 리스크 분석 프롬프트 (architecture_plan.md §7)
# ─────────────────────────────────────────────────────────────────────────────

def build_risk_analysis_prompt(
    news_text: str,
    portfolio_tickers: list[str],
    supply_chain_nodes: list[dict],
    user_question: str,
) -> list[dict]:
    """
    지정학적 리스크 분석 프롬프트 생성.

    암시적 캐싱 구조 (§4.2):
      [1] ARIA 페르소나 (고정 Prefix — 캐시 히트 대상)
      [2] 공급망 분석 역할 지시문 (고정 Prefix 연장)
      [3] 공급망 노드 데이터 + 뉴스 텍스트 + 질문 (가변)

    Returns:
        Gemini content 배열 (3개 turns)
    """
    # ── [1][2] 고정 Prefix ────────────────────────────────────────────────
    supply_chain_context = (
        f"{INVESTMENT_ADVISOR_PERSONA}\n\n"
        "[추가 분석 역할: 공급망 지정학적 리스크 전문가]\n"
        "당신은 글로벌 공급망(Value Chain) 분석과 지정학적 리스크 평가를 전문으로 합니다.\n"
        "특정 지정학적 이벤트가 발생했을 때:\n"
        "  1. 공급망 그래프에서 직접 영향을 받는 노드(기업/공장/항구)를 특정합니다.\n"
        "  2. 의존도(dependency_score)를 기반으로 2차·3차 파급 효과를 추론합니다.\n"
        "  3. 포트폴리오 보유 종목에 대한 구체적인 리스크 영향을 정량적으로 평가합니다.\n\n"
        "[분석 출력 형식]\n"
        "■ 이벤트 요약 (2줄 이내)\n"
        "■ 직접 영향 노드 목록\n"
        "  - 노드명 | 국가 | 영향 유형(직접/간접) | 심각도(치명적/심각/보통/경미)\n"
        "  - 영향 근거 (1줄)\n"
        "■ 공급망 파급 경로\n"
        "  - 1차 영향 → 2차 파급 → 3차 파급 흐름 설명\n"
        "■ 포트폴리오 투자 관점 평가\n"
        "  - 각 보유 종목별 익스포저(노출도) 및 리스크 수준\n"
        "■ 면책 고지\n"
        "  본 분석은 투자 참고 자료이며 실제 투자 결정의 책임은 투자자 본인에게 있습니다."
    )

    # ── [3] 공급망 데이터 + 뉴스 (가변) ───────────────────────────────────
    tickers_str = ", ".join(portfolio_tickers)

    # 공급망 노드 목록 텍스트화
    nodes_text = _format_supply_chain_nodes(supply_chain_nodes)

    variable_content = f"""[포트폴리오 보유 종목]
{tickers_str}

[등록된 공급망 노드 데이터]
{nodes_text}

[분석 대상 지정학적 이벤트 뉴스]
{news_text}

[분석 질문]
{user_question}"""

    return [
        {
            "role": "user",
            "parts": [supply_chain_context],
        },
        {
            "role": "model",
            "parts": [
                "안녕하세요! ARIA입니다. "
                "공급망 지정학적 리스크 분석을 시작하겠습니다."
            ],
        },
        {
            "role": "user",
            "parts": [variable_content],
        },
    ]


def _format_supply_chain_nodes(nodes: list[dict]) -> str:
    """
    공급망 노드 목록을 프롬프트 주입용 텍스트로 변환.

    AI가 공급망 구조를 이해하고 파급 경로를 추론할 수 있도록
    노드의 위치, 유형, 현재 리스크 수준을 명확히 제공.
    """
    if not nodes:
        return "  (등록된 공급망 노드 없음 — AI가 일반 지식 기반으로 분석)"

    lines = []
    for node in nodes:
        ticker_str = f" [{node.get('ticker')}]" if node.get("ticker") else ""
        city_str = f", {node.get('city')}" if node.get("city") else ""
        lines.append(
            f"  • {node.get('name')}{ticker_str} "
            f"({node.get('node_type')} | {node.get('country_code')}{city_str})\n"
            f"    섹터: {node.get('industry_sector', '미분류')} | "
            f"리스크: {node.get('risk_level', 'LOW')}"
            + (f"\n    설명: {node.get('description')}" if node.get("description") else "")
        )
    return "\n".join(lines)
