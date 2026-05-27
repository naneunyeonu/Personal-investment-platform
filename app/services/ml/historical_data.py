"""
과거 시세 데이터 수집 서비스 (ML 최적화 파이프라인 1단계)

architecture_plan.md §5.1:
  "사용자가 포트폴리오 탭에 진입하면, 시스템은 yfinance를 통해
   해당 종목들의 과거 3년간 일간 변동성 데이터를 데이터프레임으로 추출한다."

설계 원칙:
  - yfinance Ticker.history() API 사용 (single-ticker로 MultiIndex 이슈 회피)
  - 비동기 컨텍스트 호환: asyncio.to_thread()로 블로킹 I/O 오프로딩
  - 한국 주식 티커 자동 변환 (6자리 숫자 → .KS 접미사)
  - 데이터 누락(거래 정지일 등): forward-fill 처리 후 NaN 제거
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd


# ── 공개 API ─────────────────────────────────────────────────────────────────

async def fetch_historical_prices(
    tickers: list[str],
    period_years: int = 3,
) -> pd.DataFrame:
    """
    보유 종목들의 일간 종가(Close)를 DataFrame으로 반환.

    Args:
        tickers:      내부 티커 목록 (예: ["AAPL", "005930", "MSFT"])
        period_years: 과거 데이터 수집 기간 (기본 3년)

    Returns:
        pd.DataFrame:
          - 인덱스: DatetimeIndex (거래일)
          - 컬럼: 원본 티커명
          - 값: 일간 종가
          - 데이터가 없는 종목은 컬럼에서 제외
          - 종목 간 공통 기간만 포함 (dropna)

    Raises:
        없음 — 실패 시 빈 DataFrame 반환
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365 * period_years + 30)  # 여유 30일

    def _fetch_all_blocking() -> pd.DataFrame:
        """블로킹 yfinance 호출 — asyncio.to_thread에서 실행."""
        import yfinance as yf

        prices: dict[str, pd.Series] = {}
        for ticker in tickers:
            yf_symbol = _to_yf_ticker(ticker)
            try:
                obj = yf.Ticker(yf_symbol)
                hist = obj.history(
                    start=start_date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                    auto_adjust=True,
                )
                if hist.empty or "Close" not in hist.columns:
                    continue
                close = hist["Close"].dropna()
                if len(close) < 20:     # 데이터가 너무 적으면 제외 (최소 1개월)
                    continue
                prices[ticker] = close
            except Exception:
                pass  # 개별 종목 실패는 무시 (다른 종목 계속 수집)

        if not prices:
            return pd.DataFrame()

        df = pd.DataFrame(prices)
        df = df.ffill()         # 거래정지일 등 결측치 → 직전 종가로 채움
        df = df.dropna()        # 종목 간 공통 날짜만 유지
        return df

    return await asyncio.to_thread(_fetch_all_blocking)


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _to_yf_ticker(ticker: str) -> str:
    """
    내부 티커 코드를 yfinance 조회용 심볼로 변환.

    변환 규칙:
      - 이미 .KS / .KQ 접미사 → 그대로
      - 6자리 숫자 → {ticker}.KS  (KRX 코스피 기본)
      - 그 외 → 그대로 (US 주식, ETF 등)

    예:
      "005930"  → "005930.KS"
      "000660"  → "000660.KS"
      "AAPL"    → "AAPL"
      "005930.KS" → "005930.KS"
    """
    if ticker.endswith((".KS", ".KQ")):
        return ticker
    if ticker.isdigit() and len(ticker) == 6:
        return f"{ticker}.KS"
    return ticker
