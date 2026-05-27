"""
SEC EDGAR 내부자 거래 어댑터 (architecture_plan.md §6.1)

"기업 내부자는 자사주 거래 시 지체 없이 SEC의 EDGAR 시스템에
 Form 3, Form 4, Form 5 양식을 제출해야 할 법적 의무를 지닌다."

구현 전략:
─────────────────────────────────────────────────────────────────────
  기본(무료): EDGAR EFTS Full-Text Search API (키 불필요)
    https://efts.sec.gov/LATEST/search-index (Lucene 쿼리)

  고급(sec-api.io): SEC_API_KEY 설정 시 파싱된 트랜잭션 데이터 조회
    POST https://api.sec-api.io
    Authorization: {SEC_API_KEY}
    Lucene: formType:"4" AND ticker:AAPL AND transactionType:S
─────────────────────────────────────────────────────────────────────

파싱 대상 필드 (Form 4):
  - reportingOwnerName: 내부자 이름 (CEO, CFO, Director 등)
  - transactionType: S(매도)/P(매수)/A(보상)/F(몰수)
  - transactionShares: 거래 수량
  - transactionPricePerShare: 체결 단가
  - isDerivativeTransaction: 파생상품 여부 (옵션 행사 등)
  - sharesOwnedAfterTransaction: 거래 후 보유 잔량
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── 설정 상수 ─────────────────────────────────────────────────────────────────
_SEC_API_URL = "https://api.sec-api.io"
_EDGAR_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions"

_REQUEST_TIMEOUT = 10.0          # 초
_INSIDER_LOOKBACK_DAYS = 90      # 최근 90일 Form 4 조회


class SecEdgarAdapter:
    """
    SEC EDGAR Form 4 내부자 거래 데이터 어댑터.
    SEC_API_KEY 유무에 따라 sec-api.io 또는 EDGAR 무료 API 선택.
    """

    def __init__(self) -> None:
        self._api_key = settings.SEC_API_KEY
        self._use_secapi = bool(self._api_key)

    async def get_insider_transactions(
        self,
        ticker: str,
        days_back: int = _INSIDER_LOOKBACK_DAYS,
    ) -> dict[str, Any]:
        """
        특정 종목의 최근 내부자 거래(Form 4)를 조회·파싱.

        Args:
            ticker:    US 주식 티커 (예: "AAPL")
            days_back: 조회 기간 (일, 기본 90일)

        Returns:
            {
              "ticker": str,
              "signal": "STRONG_SELL" | "MODERATE_SELL" | "NEUTRAL" | "BUY" | "NO_DATA",
              "filings": [
                {
                  "filed_at": str,       # ISO8601
                  "reporter_name": str,
                  "reporter_title": str,
                  "transaction_type": str,   # S/P/A/F
                  "shares_traded": float,
                  "price_per_share": float,
                  "total_value_usd": float,
                  "is_derivative": bool,
                  "shares_owned_after": float,
                }
              ],
              "summary": str,             # LLM 프롬프트 주입용 자연어 요약
              "fetched_at": str,
            }
        """
        ticker_upper = ticker.upper()
        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")

        try:
            if self._use_secapi:
                raw = await self._fetch_via_secapi(ticker_upper, start_date, end_date)
            else:
                raw = await self._fetch_via_edgar_efts(ticker_upper, start_date, end_date)
        except Exception as exc:
            logger.warning(
                "SecEdgar fetch failed | ticker=%s use_secapi=%s error=%s",
                ticker_upper, self._use_secapi, exc,
            )
            return _empty_result(ticker_upper)

        filings = _parse_filings(raw, self._use_secapi)
        signal = _classify_signal(filings)
        summary = _build_sec_summary(ticker_upper, filings, signal)

        return {
            "ticker": ticker_upper,
            "signal": signal,
            "filings": filings,
            "summary": summary,
            "fetched_at": now.isoformat(),
        }

    # ── sec-api.io 경로 ───────────────────────────────────────────────────────

    async def _fetch_via_secapi(
        self, ticker: str, start_date: str, end_date: str
    ) -> dict:
        """
        sec-api.io EDGAR Full-Text Search API.
        Lucene 쿼리: formType:"4" AND ticker:{TICKER} AND transactionType:S
        정렬: 최신순 (filedAt desc)
        """
        # 매도(S) + 매수(P) + 공시 전체를 가져와서 클라이언트에서 필터링
        query_string = (
            f'formType:"4" AND ticker:{ticker} '
            f'AND periodOfReport:[{start_date} TO {end_date}]'
        )
        payload = {
            "query": {
                "query_string": {
                    "query": query_string,
                    "default_operator": "AND",
                }
            },
            "from": "0",
            "size": "20",
            "sort": [{"filedAt": {"order": "desc"}}],
        }
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(
                _SEC_API_URL,
                json=payload,
                headers={
                    "Authorization": self._api_key,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ── EDGAR 무료 API 경로 ───────────────────────────────────────────────────

    async def _fetch_via_edgar_efts(
        self, ticker: str, start_date: str, end_date: str
    ) -> dict:
        """
        EDGAR EFTS(ElasticSearch Full-Text Search) 무료 API.
        https://efts.sec.gov/LATEST/search-index
        """
        params = {
            "q": f'"{ticker}"',
            "forms": "4",
            "dateRange": "custom",
            "startdt": start_date,
            "enddt": end_date,
        }
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(
                _EDGAR_EFTS_URL,
                params=params,
                headers={"User-Agent": "investment-platform contact@example.com"},
            )
            resp.raise_for_status()
            return resp.json()


# ── 파싱 함수들 ───────────────────────────────────────────────────────────────

def _parse_filings(raw: dict, is_secapi: bool) -> list[dict]:
    """
    응답 페이로드에서 Form 4 트랜잭션 데이터 파싱.

    sec-api.io: hits → filing → nonDerivativeTable / derivativeTable
    EDGAR EFTS:  hits.hits → _source (기본 메타데이터만 제공)
    """
    filings = []

    if is_secapi:
        # sec-api.io 응답: {"filings": [...], "total": {...}}
        for f in raw.get("filings", []):
            filings.extend(_parse_secapi_filing(f))
    else:
        # EDGAR EFTS 응답: {"hits": {"hits": [...], "total": {...}}}
        for hit in raw.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            if src:
                filings.append(_parse_efts_hit(src))

    return filings


def _parse_secapi_filing(filing: dict) -> list[dict]:
    """sec-api.io 단일 Form 4 파일링 → 트랜잭션 리스트로 변환."""
    results = []
    owner = filing.get("reportingOwner", {})
    rel = owner.get("relationship", {})

    base = {
        "filed_at": filing.get("filedAt", "")[:10],
        "reporter_name": owner.get("name", "Unknown"),
        "reporter_title": rel.get("officerTitle") or (
            "Director" if rel.get("isDirector") else "Other"
        ),
        "is_derivative": False,
    }

    # 비파생상품 트랜잭션 (일반 주식 매수/매도)
    non_deriv = filing.get("nonDerivativeTable", {}).get("transactions", [])
    for tx in non_deriv:
        amounts = tx.get("amounts", {})
        shares = float(amounts.get("shares", 0) or 0)
        price = float(amounts.get("pricePerShare", 0) or 0)
        acq_disp = amounts.get("acquiredDisposedCode", "")
        tx_type = tx.get("transactionCoding", {}).get("transactionType", "")

        filings_entry = {
            **base,
            "transaction_type": tx_type or ("S" if acq_disp == "D" else "P"),
            "shares_traded": shares,
            "price_per_share": price,
            "total_value_usd": round(shares * price, 2),
            "is_derivative": False,
            "shares_owned_after": float(
                tx.get("postTransactionAmounts", {})
                .get("sharesOwnedFollowingTransaction", 0) or 0
            ),
        }
        results.append(filings_entry)

    # 파생상품 트랜잭션 (옵션 행사 등)
    deriv = filing.get("derivativeTable", {}).get("transactions", [])
    for tx in deriv:
        amounts = tx.get("amounts", {})
        shares = float(amounts.get("shares", 0) or 0)
        price = float(amounts.get("pricePerShare", 0) or 0)
        tx_type = tx.get("transactionCoding", {}).get("transactionType", "")

        filings_entry = {
            **base,
            "transaction_type": tx_type,
            "shares_traded": shares,
            "price_per_share": price,
            "total_value_usd": round(shares * price, 2),
            "is_derivative": True,
            "shares_owned_after": 0.0,
        }
        results.append(filings_entry)

    return results


def _parse_efts_hit(src: dict) -> dict:
    """
    EDGAR EFTS 히트 → 기본 메타데이터 (거래 상세 없음).
    무료 API는 상세 트랜잭션 파싱 불가 — 메타만 반환.
    """
    return {
        "filed_at": src.get("file_date", src.get("period_of_report", ""))[:10],
        "reporter_name": src.get("entity_name", "Unknown"),
        "reporter_title": "Insider",
        "transaction_type": "UNKNOWN",
        "shares_traded": 0.0,
        "price_per_share": 0.0,
        "total_value_usd": 0.0,
        "is_derivative": False,
        "shares_owned_after": 0.0,
    }


# ── 시그널 분류 ───────────────────────────────────────────────────────────────

def _classify_signal(filings: list[dict]) -> str:
    """
    최근 내부자 거래 패턴으로 매도 시그널 분류.

    분류 기준 (총 매도 금액 기반):
      STRONG_SELL:   $5M 이상 순매도
      MODERATE_SELL: $1M~$5M 순매도
      NEUTRAL:       $1M 미만 순매도 또는 데이터 부족
      BUY:           순매수 포지션
      NO_DATA:       공시 없음
    """
    if not filings:
        return "NO_DATA"

    # 비파생상품 일반 주식 거래만 시그널 계산에 반영
    real_trades = [f for f in filings if not f.get("is_derivative")]
    if not real_trades:
        return "NEUTRAL"

    net_value = 0.0
    for f in real_trades:
        tx = f.get("transaction_type", "")
        val = f.get("total_value_usd", 0.0)
        if tx == "S":
            net_value -= val   # 매도: 음수
        elif tx == "P":
            net_value += val   # 매수: 양수

    if net_value < -5_000_000:
        return "STRONG_SELL"
    elif net_value < -1_000_000:
        return "MODERATE_SELL"
    elif net_value > 0:
        return "BUY"
    else:
        return "NEUTRAL"


# ── 자연어 요약 생성 ──────────────────────────────────────────────────────────

def _build_sec_summary(
    ticker: str, filings: list[dict], signal: str
) -> str:
    """LLM 프롬프트 주입용 내부자 거래 요약 텍스트 생성."""
    signal_emoji = {
        "STRONG_SELL": "🔴 강력 매도 시그널",
        "MODERATE_SELL": "🟠 중간 매도 시그널",
        "NEUTRAL": "⚪ 중립",
        "BUY": "🟢 매수 시그널",
        "NO_DATA": "⚫ 공시 없음",
    }.get(signal, "⚪ 중립")

    lines = [
        f"[SEC EDGAR Form 4 내부자 거래 — {ticker}]",
        f"시그널: {signal_emoji}",
    ]

    # 매도/매수 건 요약 (비파생만)
    sells = [f for f in filings if f.get("transaction_type") == "S" and not f.get("is_derivative")]
    buys = [f for f in filings if f.get("transaction_type") == "P" and not f.get("is_derivative")]

    if sells:
        total_sell_val = sum(f.get("total_value_usd", 0) for f in sells)
        top_sell = max(sells, key=lambda x: x.get("total_value_usd", 0))
        lines.append(
            f"  내부자 매도: {len(sells)}건 | "
            f"총 ${total_sell_val:,.0f} | "
            f"최대 거래: {top_sell.get('reporter_name','?')} "
            f"{top_sell.get('shares_traded',0):,.0f}주 @ ${top_sell.get('price_per_share',0):.2f}"
        )

    if buys:
        total_buy_val = sum(f.get("total_value_usd", 0) for f in buys)
        lines.append(
            f"  내부자 매수: {len(buys)}건 | 총 ${total_buy_val:,.0f}"
        )

    if not sells and not buys:
        lines.append("  최근 90일 내 주요 내부자 거래 없음")

    lines.append(
        "  ※ 내부자 거래는 선행 지표이나 단독 투자 판단 근거로 사용 불가"
    )
    return "\n".join(lines)


def _empty_result(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "signal": "NO_DATA",
        "filings": [],
        "summary": f"[SEC EDGAR — {ticker}] 데이터 조회 불가 (API 오류 또는 키 미설정)",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
