"""
Open DART API 재무공시 어댑터 (architecture_plan.md §6.2)

"금융감독원이 제공하는 전자공시시스템(Open DART) API 연동.
 분기/반기별 재무상태표, 손익계산서, 현금흐름표 등 핵심 재무제표 정보 제공."

Open DART API 엔드포인트:
─────────────────────────────────────────────────────────────────────
  기업 코드 목록:  GET /api/corpCode.xml           → ZIP(CORPCODE.xml)
  재무제표:       GET /api/fnlttSinglAcntAll.json  → 단일회사 전체 재무제표
  기업 기본정보:  GET /api/company.json             → 기업명·업종·결산월
─────────────────────────────────────────────────────────────────────

corp_code 조회 방식:
  KRX 종목코드(6자리) → DART corp_code(8자리) 매핑이 필요.
  /api/corpCode.xml ZIP을 다운로드하여 XML 파싱 후 Redis 캐시(24h).
  이후 요청은 캐시 히트로 즉시 응답.

주요 재무지표 추출 (account_nm 기준):
  재무상태표(BS): 자산총계, 부채총계, 자본총계
  손익계산서(IS): 매출액, 영업이익, 당기순이익
→ 부채비율, ROE, 영업이익률 자동 계산
"""

import io
import logging
import zipfile
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree

import httpx

from app.adapters.retry import async_retry
from app.core.config import settings

logger = logging.getLogger(__name__)

_DART_BASE_URL = "https://opendart.fss.or.kr/api"
_REQUEST_TIMEOUT = 15.0    # DART API는 응답이 느릴 수 있음

# reprt_code: 사업보고서(11011) | 반기(11012) | 1분기(11013) | 3분기(11014)
_REPRT_CODE_ANNUAL = "11011"

# 연결재무제표(CFS) / 별도재무제표(OFS)
_FS_DIV_CONSOLIDATED = "CFS"


class DartAdapter:
    """
    Open DART API 어댑터.
    DART_API_KEY 미설정 시 모든 메서드가 empty_result 반환.
    """

    def __init__(self) -> None:
        self._api_key = settings.DART_API_KEY
        # corp_code 인메모리 캐시: {stock_code → corp_code}
        self._corp_code_map: dict[str, str] = {}

    # ── 공개 API ────────────────────────────────────────────────────────────

    async def get_financial_statements(
        self,
        ticker: str,
        year: int | None = None,
    ) -> dict[str, Any]:
        """
        KRX 종목 코드로 최신 연간 재무제표 조회.

        Args:
            ticker: KRX 6자리 종목코드 (예: "005930")
            year:   사업연도 (None 시 직전 연도 자동 사용)

        Returns:
            {
              "ticker": str,
              "corp_name": str,
              "bsns_year": str,
              "financials": {
                "total_assets": float,      # 자산총계 (백만원)
                "total_liabilities": float, # 부채총계
                "total_equity": float,      # 자본총계
                "revenue": float,           # 매출액
                "operating_income": float,  # 영업이익
                "net_income": float,        # 당기순이익
              },
              "ratios": {
                "debt_ratio_pct": float,    # 부채비율 (%)
                "roe_pct": float,           # ROE (%)
                "operating_margin_pct": float,  # 영업이익률 (%)
              },
              "summary": str,    # LLM 프롬프트 주입용 자연어 요약
              "fetched_at": str,
            }
        """
        if not self._api_key:
            return _empty_dart_result(ticker, "DART_API_KEY 미설정")

        # 종목코드만 처리 (시장 접미사 제거)
        stock_code = ticker.replace(".KS", "").replace(".KQ", "")
        if not (stock_code.isdigit() and len(stock_code) == 6):
            return _empty_dart_result(ticker, f"유효하지 않은 KRX 코드: {ticker}")

        bsns_year = str(year or (datetime.now().year - 1))

        # 1. stock_code → corp_code 변환
        corp_code = await self._get_corp_code(stock_code)
        if not corp_code:
            return _empty_dart_result(ticker, f"corp_code 조회 실패: {stock_code}")

        # 2. 재무제표 API 호출
        try:
            raw = await self._fetch_financial_statements(corp_code, bsns_year)
        except Exception as exc:
            logger.warning(
                "DART API 오류 | ticker=%s corp_code=%s year=%s error=%s",
                ticker, corp_code, bsns_year, exc,
            )
            return _empty_dart_result(ticker, f"API 오류: {exc}")

        # 3. 데이터 파싱 및 지표 계산
        corp_name, financials = _parse_financial_data(raw)
        if not financials:
            return _empty_dart_result(ticker, f"{bsns_year}년 재무데이터 없음")

        ratios = _calc_ratios(financials)
        summary = _build_dart_summary(stock_code, corp_name, bsns_year, financials, ratios)

        return {
            "ticker": stock_code,
            "corp_name": corp_name,
            "bsns_year": bsns_year,
            "financials": financials,
            "ratios": ratios,
            "summary": summary,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── 내부: corp_code 매핑 ─────────────────────────────────────────────────

    async def _get_corp_code(self, stock_code: str) -> str | None:
        """
        종목코드(6자리) → DART corp_code(8자리) 변환.
        인메모리 캐시 → DART ZIP 다운로드 순으로 시도.
        """
        if stock_code in self._corp_code_map:
            return self._corp_code_map[stock_code]

        # 캐시 미스: DART corpCode.xml ZIP 다운로드
        if not self._corp_code_map:
            await self._load_corp_code_map()

        return self._corp_code_map.get(stock_code)

    async def _load_corp_code_map(self) -> None:
        """
        DART corpCode.xml ZIP 다운로드 → stock_code → corp_code 매핑 구축.
        ZIP 내 CORPCODE.xml 파싱 (list 태그 반복).
        네트워크 일시 오류 시 최대 3회 재시도.
        """
        url = f"{_DART_BASE_URL}/corpCode.xml"
        try:
            resp = await async_retry(
                self._fetch_corp_code_zip,
                url,
                max_attempts=3,
                base_delay=2.0,  # DART는 응답이 느림 — 여유 있게 대기
            )

            with zipfile.ZipFile(io.BytesIO(resp)) as zf:
                xml_bytes = zf.read("CORPCODE.xml")

            root = ElementTree.fromstring(xml_bytes)
            count = 0
            for item in root.findall("list"):
                corp = item.findtext("corp_code", "").strip()
                stock = item.findtext("stock_code", "").strip()
                if corp and stock and len(stock) == 6:
                    self._corp_code_map[stock] = corp
                    count += 1

            logger.info("DART corp_code 매핑 로드 완료: %d개", count)

        except Exception as exc:
            logger.warning("DART corpCode.xml 로드 실패: %s", exc)

    async def _fetch_corp_code_zip(self, url: str) -> bytes:
        """DART corpCode.xml ZIP 단순 다운로드 (async_retry 대상 단위 함수)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params={"crtfc_key": self._api_key})
            resp.raise_for_status()
            return resp.content

    # ── 내부: 재무제표 API 호출 ──────────────────────────────────────────────

    async def _fetch_financial_statements(
        self, corp_code: str, bsns_year: str
    ) -> list[dict]:
        """
        DART fnlttSinglAcntAll API 호출 → 재무제표 항목 리스트 반환.
        연결재무제표(CFS) 우선, 없으면 별도재무제표(OFS).
        네트워크 일시 오류 시 최대 3회 재시도.
        """
        for fs_div in (_FS_DIV_CONSOLIDATED, "OFS"):
            try:
                data = await async_retry(
                    self._fetch_single_fs,
                    corp_code,
                    bsns_year,
                    fs_div,
                    max_attempts=3,
                    base_delay=2.0,
                )
                if data.get("status") == "000" and data.get("list"):
                    return data["list"]
            except Exception as exc:
                logger.warning(
                    "DART 재무제표 조회 실패 | corp_code=%s year=%s fs_div=%s error=%s",
                    corp_code, bsns_year, fs_div, exc,
                )

        return []

    async def _fetch_single_fs(
        self, corp_code: str, bsns_year: str, fs_div: str
    ) -> dict:
        """재무제표 단건 API 호출 (async_retry 대상 단위 함수)."""
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(
                f"{_DART_BASE_URL}/fnlttSinglAcntAll.json",
                params={
                    "crtfc_key": self._api_key,
                    "corp_code": corp_code,
                    "bsns_year": bsns_year,
                    "reprt_code": _REPRT_CODE_ANNUAL,
                    "fs_div": fs_div,
                },
            )
            resp.raise_for_status()
            return resp.json()


# ── 데이터 파싱 ───────────────────────────────────────────────────────────────

# 조회할 계정과목 (account_nm 기준 매핑)
_ACCOUNT_MAP = {
    "자산총계": "total_assets",
    "부채총계": "total_liabilities",
    "자본총계": "total_equity",
    "매출액": "revenue",
    "영업이익": "operating_income",
    "당기순이익": "net_income",
    # 일부 기업은 다른 계정과목명 사용
    "수익(매출액)": "revenue",
    "영업손익": "operating_income",
    "당기순이익(손실)": "net_income",
}


def _parse_financial_data(items: list[dict]) -> tuple[str, dict[str, float]]:
    """
    DART API 응답 리스트에서 핵심 재무지표 추출.
    단위: 원 (thstrm_amount 기준, 불필요 문자 제거)

    Returns:
        (corp_name, {metric_key: value_in_million_krw})
    """
    financials: dict[str, float] = {}
    corp_name = ""

    for item in items:
        if not corp_name and item.get("corp_code"):
            corp_name = item.get("corp_name", "") or item.get("corp_code", "")

        account_nm = item.get("account_nm", "").strip()
        metric_key = _ACCOUNT_MAP.get(account_nm)
        if not metric_key:
            continue

        # thstrm_amount: 당기 금액 (문자열, 콤마 포함 가능, 단위: 원)
        raw_val = str(item.get("thstrm_amount", "") or "").replace(",", "").strip()
        try:
            val_won = float(raw_val) if raw_val else 0.0
            # 백만원 단위로 변환
            financials[metric_key] = round(val_won / 1_000_000, 1)
        except ValueError:
            pass

    return corp_name, financials


def _calc_ratios(financials: dict[str, float]) -> dict[str, float]:
    """핵심 재무 비율 계산."""

    def safe_div(num: float, den: float) -> float:
        return round(num / den * 100, 2) if den and den != 0 else 0.0

    liabilities = financials.get("total_liabilities", 0)
    equity = financials.get("total_equity", 0)
    revenue = financials.get("revenue", 0)
    operating = financials.get("operating_income", 0)
    net = financials.get("net_income", 0)

    return {
        "debt_ratio_pct": safe_div(liabilities, equity),       # 부채비율 = 부채/자본
        "roe_pct": safe_div(net, equity),                       # ROE = 순이익/자본
        "operating_margin_pct": safe_div(operating, revenue),  # 영업이익률 = 영업이익/매출
    }


# ── 자연어 요약 생성 ──────────────────────────────────────────────────────────

def _build_dart_summary(
    ticker: str,
    corp_name: str,
    bsns_year: str,
    financials: dict[str, float],
    ratios: dict[str, float],
) -> str:
    """LLM 프롬프트 주입용 DART 재무공시 요약 텍스트."""

    def fmt_billion(val: float) -> str:
        """백만원 → 조/억 단위 자동 변환."""
        if abs(val) >= 1_000_000:
            return f"{val/1_000_000:.2f}조원"
        elif abs(val) >= 10_000:
            return f"{val/10_000:.0f}억원"
        else:
            return f"{val:,.0f}백만원"

    name_display = f"{corp_name}({ticker})" if corp_name else ticker

    lines = [
        f"[DART 재무공시 {bsns_year}년 사업보고서 — {name_display}]",
    ]

    if financials.get("revenue"):
        lines.append(
            f"  매출액: {fmt_billion(financials.get('revenue', 0))} | "
            f"영업이익: {fmt_billion(financials.get('operating_income', 0))} "
            f"(마진 {ratios.get('operating_margin_pct', 0):.1f}%)"
        )
    if financials.get("net_income"):
        lines.append(
            f"  당기순이익: {fmt_billion(financials.get('net_income', 0))} | "
            f"ROE: {ratios.get('roe_pct', 0):.1f}%"
        )
    if financials.get("total_assets"):
        lines.append(
            f"  자산총계: {fmt_billion(financials.get('total_assets', 0))} | "
            f"부채비율: {ratios.get('debt_ratio_pct', 0):.1f}%"
        )

    # 재무 건전성 간략 평가
    debt_ratio = ratios.get("debt_ratio_pct", 0)
    roe = ratios.get("roe_pct", 0)
    margin = ratios.get("operating_margin_pct", 0)

    health_notes = []
    if debt_ratio > 200:
        health_notes.append(f"⚠️ 부채비율 과도({debt_ratio:.0f}%)")
    elif debt_ratio < 50:
        health_notes.append(f"✅ 재무구조 안정({debt_ratio:.0f}%)")
    if roe < 5:
        health_notes.append(f"주의 ROE 저조({roe:.1f}%)")
    elif roe > 15:
        health_notes.append(f"✅ 우수 ROE({roe:.1f}%)")
    if margin < 0:
        health_notes.append(f"⚠️ 영업손실({margin:.1f}%)")

    if health_notes:
        lines.append(f"  재무 평가: {' | '.join(health_notes)}")

    return "\n".join(lines)


def _empty_dart_result(ticker: str, reason: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "corp_name": "",
        "bsns_year": "",
        "financials": {},
        "ratios": {},
        "summary": f"[DART — {ticker}] 데이터 없음: {reason}",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
