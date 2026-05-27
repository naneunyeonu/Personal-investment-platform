"""
포트폴리오 ML 최적화 서비스 (architecture_plan.md §5)

LLM 수리적 환각(Hallucination) 차단 설계:
─────────────────────────────────────────────────────────────────────
  Gemini 호출 이전에 PyPortfolioOpt 수치 연산을 선행 실행.
  AI는 "수학적 모델 시뮬레이션 결과에 따르면..." 형태로 데이터 기반 브리핑.
─────────────────────────────────────────────────────────────────────

최적화 전략 (architecture_plan.md §5.1~5.2):
  1. 최소 변동성 포트폴리오  (MVP): min σ²(w)
  2. 최대 샤프 비율 포트폴리오(MSR): max [E(Rp) - Rf] / σ(Rp)
  3. 목표 리스크 내 최대 수익 (ER):  max E(Rp) s.t. σ ≤ target
  4. 계층적 리스크 패리티     (HRP): 클러스터링 기반 균등 위험 배분

공분산 추정: Ledoit-Wolf 수축 추정 → 표본 오차 보정, 코너 솔루션 완화
"""

import asyncio
from typing import Any

import numpy as np
import pandas as pd

from app.services.ml.historical_data import fetch_historical_prices


# ── 공개 API ─────────────────────────────────────────────────────────────────

async def run_portfolio_optimization(
    tickers: list[str],
    current_weights: dict[str, float],
    period_years: int = 3,
    risk_free_rate: float = 0.035,     # 한국 기준금리 3.5% (2025년 기준)
) -> dict[str, Any]:
    """
    포트폴리오 ML 최적화 실행 (architecture_plan.md §5).

    Args:
        tickers:         최적화 대상 티커 목록 (최소 2개)
        current_weights: 현재 KRW 기준 비중 {ticker: float}, 합계 ≈ 1.0
        period_years:    과거 데이터 기간 (기본 3년)
        risk_free_rate:  무위험 이자율 (샤프 비율 계산용)

    Returns:
        {
          "status": "success" | "partial" | "failed",
          "tickers": [...],
          "current_weights": {...},
          "min_volatility": {"weights": {...}, "expected_annual_return": float, ...},
          "max_sharpe":     {"weights": {...}, "expected_annual_return": float, ...},
          "max_return":     {"weights": {...}, "expected_annual_return": float, ...},
          "hrp":            {"weights": {...}, "expected_annual_return": float, ...},
          "current_performance": {"expected_annual_return": float, "annual_volatility": float, "sharpe_ratio": float},
          "covariance_period_years": float,
          "risk_free_rate": float,
          "summary": str,    # LLM 프롬프트 컨텍스트용 자연어 요약
        }
    """
    # 단일 종목은 분산 최적화 불가
    if len(tickers) < 2:
        return _single_asset_result(tickers)

    # 1단계: 과거 종가 데이터 수집
    price_df = await fetch_historical_prices(tickers, period_years)

    if price_df.empty:
        return _failed_result("과거 시세 데이터를 가져올 수 없습니다 (yfinance 조회 실패).")

    available_tickers = list(price_df.columns)
    if len(available_tickers) < 2:
        return _failed_result(
            f"데이터 수집 성공 종목이 1개 이하입니다 (성공: {available_tickers})."
        )

    # 2단계: 일간 수익률 계산
    returns = price_df.pct_change().dropna()
    if len(returns) < 30:
        return _failed_result(
            f"공분산 추정에 필요한 최소 관측치(30일)가 부족합니다 ({len(returns)}일)."
        )

    # 3단계: 블로킹 최적화 연산 → asyncio.to_thread로 실행 (CPU 바운드)
    available_weights = {
        t: current_weights.get(t, 1.0 / len(available_tickers))
        for t in available_tickers
    }
    total_w = sum(available_weights.values())
    if total_w > 0:
        available_weights = {t: w / total_w for t, w in available_weights.items()}

    result = await asyncio.to_thread(
        _optimize_sync,
        returns,
        available_tickers,
        available_weights,
        risk_free_rate,
    )
    return result


# ── 동기 최적화 핵심 로직 (asyncio.to_thread에서 실행) ──────────────────────

def _optimize_sync(
    returns: pd.DataFrame,
    tickers: list[str],
    current_weights: dict[str, float],
    risk_free_rate: float,
) -> dict[str, Any]:
    """
    PyPortfolioOpt 4가지 최적화 실행.
    CPU 바운드 블로킹 함수 — Celery 워커 asyncio.to_thread에서 실행.
    """
    from pypfopt import EfficientFrontier, HRPOpt, expected_returns, risk_models

    # ── 수익률 / 공분산 추정 ──────────────────────────────────────────────
    mu = expected_returns.mean_historical_return(
        returns,
        returns_data=True,
        frequency=252,
    )
    # Ledoit-Wolf 수축 추정: 과적합(Overfitting) 방지, 코너 솔루션 완화
    try:
        S = risk_models.CovarianceShrinkage(
            returns, returns_data=True, frequency=252
        ).ledoit_wolf()
    except Exception:
        # fallback: 표본 공분산
        S = risk_models.sample_cov(returns, returns_data=True, frequency=252)

    results: dict[str, Any] = {
        "status": "success",
        "tickers": tickers,
        "current_weights": current_weights,
        "covariance_period_years": round(len(returns) / 252, 1),
        "risk_free_rate": risk_free_rate,
    }

    # ── 1. 최소 변동성 포트폴리오 (MVP) ─────────────────────────────────
    try:
        ef_mv = EfficientFrontier(mu, S, weight_bounds=(0, 1))
        ef_mv.min_volatility()
        w_mv = ef_mv.clean_weights()
        ret_mv, vol_mv, sr_mv = ef_mv.portfolio_performance(
            risk_free_rate=risk_free_rate, verbose=False
        )
        results["min_volatility"] = {
            "weights": dict(w_mv),
            "expected_annual_return": round(float(ret_mv), 4),
            "annual_volatility": round(float(vol_mv), 4),
            "sharpe_ratio": round(float(sr_mv), 4),
        }
    except Exception as e:
        results["min_volatility"] = {"error": str(e)}

    # ── 2. 최대 샤프 비율 포트폴리오 (MSR) ──────────────────────────────
    try:
        ef_ms = EfficientFrontier(mu, S, weight_bounds=(0, 1))
        ef_ms.max_sharpe(risk_free_rate=risk_free_rate)
        w_ms = ef_ms.clean_weights()
        ret_ms, vol_ms, sr_ms = ef_ms.portfolio_performance(
            risk_free_rate=risk_free_rate, verbose=False
        )
        results["max_sharpe"] = {
            "weights": dict(w_ms),
            "expected_annual_return": round(float(ret_ms), 4),
            "annual_volatility": round(float(vol_ms), 4),
            "sharpe_ratio": round(float(sr_ms), 4),
        }
    except Exception as e:
        results["max_sharpe"] = {"error": str(e)}

    # ── 3. 목표 리스크 내 최대 수익 포트폴리오 (ER) ──────────────────────
    #    현재 포트폴리오 변동성의 120% 이내로 제약
    try:
        current_vol = _calc_portfolio_vol(returns, current_weights, tickers)
        target_vol = min(float(current_vol) * 1.2, 0.50)   # 최대 50% 변동성 cap
        target_vol = max(target_vol, 0.05)                  # 최소 5% (너무 낮으면 solver 실패)
        ef_er = EfficientFrontier(mu, S, weight_bounds=(0, 1))
        ef_er.efficient_risk(target_volatility=target_vol)
        w_er = ef_er.clean_weights()
        ret_er, vol_er, sr_er = ef_er.portfolio_performance(
            risk_free_rate=risk_free_rate, verbose=False
        )
        results["max_return"] = {
            "weights": dict(w_er),
            "expected_annual_return": round(float(ret_er), 4),
            "annual_volatility": round(float(vol_er), 4),
            "sharpe_ratio": round(float(sr_er), 4),
            "target_volatility": round(target_vol, 4),
        }
    except Exception as e:
        results["max_return"] = {"error": str(e)}

    # ── 4. 계층적 리스크 패리티 (HRP) ────────────────────────────────────
    #    클러스터링으로 자산 간 위험 균등 배분 → 코너 솔루션 문제 없음
    try:
        hrp = HRPOpt(returns)
        hrp.optimize()
        w_hrp = hrp.clean_weights()
        ret_hrp, vol_hrp, sr_hrp = hrp.portfolio_performance(
            risk_free_rate=risk_free_rate, verbose=False
        )
        results["hrp"] = {
            "weights": dict(w_hrp),
            "expected_annual_return": round(float(ret_hrp), 4),
            "annual_volatility": round(float(vol_hrp), 4),
            "sharpe_ratio": round(float(sr_hrp), 4),
        }
    except Exception as e:
        results["hrp"] = {"error": str(e)}

    # ── 5. 현재 포트폴리오 성과 기준선 ──────────────────────────────────
    try:
        results["current_performance"] = _calc_portfolio_performance(
            mu, S, current_weights, tickers, risk_free_rate
        )
    except Exception as e:
        results["current_performance"] = {"error": str(e)}

    # ── 6. LLM 프롬프트 주입용 자연어 요약 생성 ────────────────────────
    results["summary"] = _build_optimization_summary(results)

    # 결과가 하나도 없으면 partial
    has_any = any(
        k in results and "error" not in results[k]
        for k in ("min_volatility", "max_sharpe", "hrp")
    )
    if not has_any:
        results["status"] = "partial"

    return results


# ── 내부 계산 헬퍼 ────────────────────────────────────────────────────────────

def _calc_portfolio_vol(
    returns: pd.DataFrame,
    weights: dict[str, float],
    tickers: list[str],
) -> float:
    """연간 포트폴리오 변동성 계산."""
    w_arr = np.array([weights.get(t, 0.0) for t in tickers], dtype=float)
    total = w_arr.sum()
    if total > 0:
        w_arr = w_arr / total
    cov_ann = returns.cov().values * 252
    port_var = float(w_arr @ cov_ann @ w_arr)
    return float(np.sqrt(max(port_var, 0.0)))


def _calc_portfolio_performance(
    mu: pd.Series,
    S: pd.DataFrame,
    weights: dict[str, float],
    tickers: list[str],
    risk_free_rate: float,
) -> dict[str, float]:
    """현재 포트폴리오 성과 지표 (수익률·변동성·샤프)."""
    w_arr = np.array([weights.get(t, 0.0) for t in tickers], dtype=float)
    total = w_arr.sum()
    if total > 0:
        w_arr = w_arr / total

    port_return = float(mu.values @ w_arr)
    port_var = float(w_arr @ S.values @ w_arr)
    port_vol = float(np.sqrt(max(port_var, 0.0)))
    sharpe = (port_return - risk_free_rate) / port_vol if port_vol > 1e-9 else 0.0

    return {
        "expected_annual_return": round(port_return, 4),
        "annual_volatility": round(port_vol, 4),
        "sharpe_ratio": round(sharpe, 4),
    }


# ── 자연어 요약 생성 (LLM 프롬프트 주입용) ──────────────────────────────────

def _build_optimization_summary(results: dict) -> str:
    """
    ML 최적화 결과를 Gemini 프롬프트 컨텍스트용 구조화 텍스트로 변환.

    AI는 이 텍스트를 기반으로 수학적 근거가 있는 자연어 브리핑을 생성함.
    "수학적 모델 시뮬레이션 결과에 따르면..." 형태의 응답 유도.
    """
    lines = [
        "[ML 포트폴리오 최적화 시뮬레이션 결과 — PyPortfolioOpt]",
        f"▸ 분석 기간: {results.get('covariance_period_years', '?')}년 일간 수익률 (공분산 행렬 Ledoit-Wolf 수축 추정)",
        f"▸ 무위험 이자율 기준: {results.get('risk_free_rate', 0.035)*100:.1f}%",
        "",
    ]

    # 현재 포트폴리오
    curr = results.get("current_performance", {})
    if "error" not in curr and curr:
        lines += [
            "▶ 현재 포트폴리오 성과 (기준선)",
            f"  • 예상 연 수익률: {curr.get('expected_annual_return',0)*100:+.2f}%",
            f"  • 연간 변동성(σ): {curr.get('annual_volatility',0)*100:.2f}%",
            f"  • 샤프 비율:      {curr.get('sharpe_ratio',0):.3f}",
            "",
        ]

    # 최소 변동성 (MVP)
    mv = results.get("min_volatility", {})
    if "error" not in mv and "weights" in mv:
        top3 = _top3_weights(mv["weights"])
        lines += [
            "▶ 시뮬레이션 ① 최소 변동성 포트폴리오 (MVP)",
            f"  • 예상 연 수익률: {mv.get('expected_annual_return',0)*100:+.2f}%",
            f"  • 연간 변동성(σ): {mv.get('annual_volatility',0)*100:.2f}%  ← 리스크 최소화",
            f"  • 샤프 비율:      {mv.get('sharpe_ratio',0):.3f}",
            f"  • 권장 상위 비중: {top3}",
            "",
        ]

    # 최대 샤프 비율 (MSR)
    ms = results.get("max_sharpe", {})
    if "error" not in ms and "weights" in ms:
        top3 = _top3_weights(ms["weights"])
        lines += [
            "▶ 시뮬레이션 ② 최대 샤프 비율 포트폴리오 (MSR)",
            f"  • 예상 연 수익률: {ms.get('expected_annual_return',0)*100:+.2f}%",
            f"  • 연간 변동성(σ): {ms.get('annual_volatility',0)*100:.2f}%",
            f"  • 샤프 비율:      {ms.get('sharpe_ratio',0):.3f}  ← 위험 대비 수익 최대",
            f"  • 권장 상위 비중: {top3}",
            "",
        ]

    # 목표 리스크 내 최대 수익 (ER)
    er = results.get("max_return", {})
    if "error" not in er and "weights" in er:
        top3 = _top3_weights(er["weights"])
        lines += [
            "▶ 시뮬레이션 ③ 목표 리스크 내 최대 수익 포트폴리오",
            f"  • 예상 연 수익률: {er.get('expected_annual_return',0)*100:+.2f}%  ← 수익 최대화",
            f"  • 연간 변동성(σ): {er.get('annual_volatility',0)*100:.2f}%",
            f"  • 목표 변동성 한도: {er.get('target_volatility',0)*100:.2f}%",
            f"  • 권장 상위 비중: {top3}",
            "",
        ]

    # HRP
    hrp = results.get("hrp", {})
    if "error" not in hrp and "weights" in hrp:
        top3 = _top3_weights(hrp["weights"])
        lines += [
            "▶ 시뮬레이션 ④ 계층적 리스크 패리티 (HRP)",
            f"  • 예상 연 수익률: {hrp.get('expected_annual_return',0)*100:+.2f}%",
            f"  • 연간 변동성(σ): {hrp.get('annual_volatility',0)*100:.2f}%",
            f"  • 샤프 비율:      {hrp.get('sharpe_ratio',0):.3f}",
            f"  • 권장 상위 비중: {top3}  ← 클러스터링 기반 균등 배분",
            "",
        ]

    lines += [
        "※ 본 시뮬레이션은 과거 수익률 기반 수리적 최적화 결과이며,",
        "  미래 수익을 보장하지 않습니다. 투자 결정의 책임은 투자자 본인에게 있습니다.",
    ]

    return "\n".join(lines)


def _top3_weights(weights: dict[str, float]) -> str:
    """비중 상위 3개 종목을 문자열로 반환."""
    top = sorted(weights.items(), key=lambda x: x[1], reverse=True)[:3]
    return ", ".join(f"{t}: {w*100:.1f}%" for t, w in top if w > 0.005)


# ── 실패 케이스 헬퍼 ──────────────────────────────────────────────────────────

def _single_asset_result(tickers: list[str]) -> dict[str, Any]:
    return {
        "status": "failed",
        "reason": "단일 종목 — 분산 최적화 불가",
        "tickers": tickers,
        "summary": (
            "현재 포트폴리오는 단일 종목으로 구성되어 분산 최적화를 수행할 수 없습니다.\n"
            "2종목 이상 보유 시 ML 기반 자산 배분 최적화가 자동 실행됩니다."
        ),
    }


def _failed_result(reason: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "reason": reason,
        "summary": f"ML 최적화 미수행: {reason}",
    }
