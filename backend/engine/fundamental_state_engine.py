import copy
import logging
from typing import Dict, Any, Optional, List, Union

from backend.engine.fundamental_engine import (
    get_fundamental_context,
    get_multi_fundamental_context,
    FUNDAMENTAL_METRIC_KEYS
)

logger = logging.getLogger(__name__)


def _classify_growth_metric(
    current: Optional[float],
    previous: Optional[float],
    raw_growth_rate: Optional[float]
) -> Dict[str, Any]:
    """
    개별 실적 지표(revenue, operating_profit, net_profit)에 대한 성장 상태 및 방향 산출.
    - 전년/당해 모두 양수(>0): status = 'COMPARABLE', direction = 'INCREASE' / 'DECREASE' / 'FLAT'
    - 기존 상태(TURNAROUND, DEFICIT_CONTINUATION, LOSS_WIDENING, NOT_COMPARABLE) 보존
    - 전년 흑자 -> 당해 적자: status = 'DEFICIT_TURNAROUND', direction = 'DECREASE'
    - NORMAL_GROWTH를 '좋은 성장'으로 해석하지 않고 객관적 'COMPARABLE' 및 방향만 반환
    """
    if current is None or previous is None or previous == 0:
        return {
            "raw_growth_rate": raw_growth_rate,
            "status": "NOT_COMPARABLE",
            "direction": "UNKNOWN"
        }

    # 1. 전년/당해 모두 양수인 비교 가능 상태 (COMPARABLE)
    if previous > 0 and current > 0:
        if current > previous:
            direction = "INCREASE"
        elif current < previous:
            direction = "DECREASE"
        else:
            direction = "FLAT"
        return {
            "raw_growth_rate": raw_growth_rate,
            "status": "COMPARABLE",
            "direction": direction
        }

    # 2. 전년 적자(previous < 0) 인 경우
    if previous < 0:
        if current > 0:
            return {
                "raw_growth_rate": raw_growth_rate,
                "status": "TURNAROUND",
                "direction": "INCREASE"
            }
        elif current <= previous:
            return {
                "raw_growth_rate": raw_growth_rate,
                "status": "LOSS_WIDENING",
                "direction": "DECREASE"
            }
        else:
            # current < 0 and current > previous
            return {
                "raw_growth_rate": raw_growth_rate,
                "status": "DEFICIT_CONTINUATION",
                "direction": "INCREASE"  # 적자 폭 축소
            }

    # 3. 전년 흑자(previous > 0) -> 당해 적자(current <= 0)
    return {
        "raw_growth_rate": raw_growth_rate,
        "status": "DEFICIT_TURNAROUND",
        "direction": "DECREASE"
    }


def _get_sign(val: Optional[float]) -> str:
    """
    수치의 부호만 객관적으로 반환 (절대 임계치 및 주관적 등급 금지)
    """
    if val is None:
        return "UNKNOWN"
    if val > 0:
        return "POSITIVE"
    if val < 0:
        return "NEGATIVE"
    return "ZERO"


def get_fundamental_state(
    ticker_or_context: Union[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    종목 티커 또는 fundamental_engine의 Context를 전달받아
    업종 정보 없이도 객관적인 사실 기반으로 판단 가능한 Fundamental State를 반환합니다.

    - 외부 API 호출 절대 금지
    - 원본 Context 수정 절대 금지
    - 주관적/가치평가 단어(GOOD/BAD/BUY/SELL/RISKY/CHEAP 등) 일체 배제
    """
    # 1. Context 확보 (외부 API 호출 금지, 메모리 캐시 조회)
    if isinstance(ticker_or_context, str):
        context = get_fundamental_context(ticker_or_context)
    elif isinstance(ticker_or_context, dict):
        context = ticker_or_context
    else:
        raise ValueError("Invalid input: must be ticker string or fundamental context dict")

    ticker = context.get("ticker", "")
    name = context.get("name", ticker)
    market = context.get("market", "UNKNOWN")
    asset_type = context.get("asset_type", "STOCK")
    data_state = context.get("status", "NO_FINANCE_DATA")

    # 2. SUCCESS가 아닌 경우 (NO_FINANCE_DATA / NOT_APPLICABLE) 안전 격리
    if data_state != "SUCCESS":
        return {
            "ticker": ticker,
            "name": name,
            "market": market,
            "asset_type": asset_type,
            "data_state": data_state,
            "data_quality": {
                "available_metric_count": 0,
                "missing_metric_count": len(FUNDAMENTAL_METRIC_KEYS),
                "coverage_ratio": 0.0
            },
            "earnings_state": {
                "status": "UNKNOWN",
                "operating_profit": None,
                "net_profit": None
            },
            "profitability": {
                "roe": {"value": None, "sign": "UNKNOWN"},
                "operating_margin": {"value": None, "sign": "UNKNOWN"},
                "net_margin": {"value": None, "sign": "UNKNOWN"}
            },
            "growth": {
                "revenue": {"raw_growth_rate": None, "status": "NOT_COMPARABLE", "direction": "UNKNOWN"},
                "operating_profit": {"raw_growth_rate": None, "status": "NOT_COMPARABLE", "direction": "UNKNOWN"},
                "net_profit": {"raw_growth_rate": None, "status": "NOT_COMPARABLE", "direction": "UNKNOWN"}
            },
            "valuation": {
                "per": None,
                "per_status": "UNKNOWN",
                "pbr": None,
                "pbr_status": "UNKNOWN",
                "eps": None,
                "bps": None
            },
            "balance_sheet": {
                "debt_ratio": None,
                "quick_ratio": None,
                "sector_adjustment_available": False
            },
            "summary_flags": []
        }

    # 3. SUCCESS 종목의 실제 latest annual actual 지표 추출
    annual_data = context.get("annual") or {}
    latest_actual = annual_data.get("latest_actual") or {}
    previous_actual = annual_data.get("previous_actual") or {}
    growth_info = annual_data.get("growth") or {}

    latest_metrics: Dict[str, Optional[float]] = latest_actual.get("metrics") or {}
    prev_metrics: Dict[str, Optional[float]] = previous_actual.get("metrics") or {}

    # 4. Data Quality 계산
    available_metric_count = sum(
        1 for k in FUNDAMENTAL_METRIC_KEYS if latest_metrics.get(k) is not None
    )
    total_metrics = len(FUNDAMENTAL_METRIC_KEYS)
    missing_metric_count = total_metrics - available_metric_count
    coverage_ratio = round((available_metric_count / total_metrics) * 100.0, 2)

    # 5. Earnings State (latest annual actual 기준)
    op = latest_metrics.get("operating_profit")
    np_val = latest_metrics.get("net_profit")

    if op is None or np_val is None:
        earnings_status = "UNKNOWN"
    elif op > 0 and np_val > 0:
        earnings_status = "PROFITABLE"
    elif op < 0:
        earnings_status = "OPERATING_LOSS"
    elif op >= 0 and np_val < 0:
        earnings_status = "NET_LOSS"
    else:
        earnings_status = "UNKNOWN"

    earnings_state = {
        "status": earnings_status,
        "operating_profit": op,
        "net_profit": np_val
    }

    # 6. Profitability Context (부호만 객관적으로 표현)
    profitability = {
        "roe": {
            "value": latest_metrics.get("roe"),
            "sign": _get_sign(latest_metrics.get("roe"))
        },
        "operating_margin": {
            "value": latest_metrics.get("operating_margin"),
            "sign": _get_sign(latest_metrics.get("operating_margin"))
        },
        "net_margin": {
            "value": latest_metrics.get("net_margin"),
            "sign": _get_sign(latest_metrics.get("net_margin"))
        }
    }

    # 7. Growth State
    growth = {
        "revenue": _classify_growth_metric(
            latest_metrics.get("revenue"),
            prev_metrics.get("revenue"),
            growth_info.get("revenue_growth")
        ),
        "operating_profit": _classify_growth_metric(
            latest_metrics.get("operating_profit"),
            prev_metrics.get("operating_profit"),
            growth_info.get("operating_profit_growth")
        ),
        "net_profit": _classify_growth_metric(
            latest_metrics.get("net_profit"),
            prev_metrics.get("net_profit"),
            growth_info.get("net_profit_growth")
        )
    }

    # 8. Valuation Context (임계치/저평가/고평가 판정 금지)
    per_val = latest_metrics.get("per")
    if per_val is None:
        per_status = "UNKNOWN"
    elif per_val > 0:
        per_status = "POSITIVE_PER"
    else:
        per_status = "NON_POSITIVE_PER"

    pbr_val = latest_metrics.get("pbr")
    pbr_status = "AVAILABLE" if pbr_val is not None else "UNKNOWN"

    valuation = {
        "per": per_val,
        "per_status": per_status,
        "pbr": pbr_val,
        "pbr_status": pbr_status,
        "eps": latest_metrics.get("eps"),
        "bps": latest_metrics.get("bps")
    }

    # 9. Balance Sheet Context (sector_adjustment_available=False, 안전/위험 등급 금지)
    balance_sheet = {
        "debt_ratio": latest_metrics.get("debt_ratio"),
        "quick_ratio": latest_metrics.get("quick_ratio"),
        "sector_adjustment_available": False
    }

    # 10. Summary Flags (객관적 사실만 flag 가능)
    summary_flags: List[str] = []

    if op is not None and op < 0:
        summary_flags.append("HAS_OPERATING_LOSS")

    if np_val is not None and np_val < 0:
        summary_flags.append("HAS_NET_LOSS")

    if growth["operating_profit"]["status"] == "TURNAROUND":
        summary_flags.append("TURNAROUND_OPERATING_PROFIT")

    if growth["net_profit"]["status"] == "TURNAROUND":
        summary_flags.append("TURNAROUND_NET_PROFIT")

    if growth["revenue"]["direction"] == "DECREASE":
        summary_flags.append("DECLINING_REVENUE")

    roe_val = latest_metrics.get("roe")
    if roe_val is not None and roe_val < 0:
        summary_flags.append("NEGATIVE_ROE")

    if 0 < available_metric_count < total_metrics:
        summary_flags.append("PARTIAL_DATA")

    return {
        "ticker": ticker,
        "name": name,
        "market": market,
        "asset_type": asset_type,
        "data_state": data_state,
        "data_quality": {
            "available_metric_count": available_metric_count,
            "missing_metric_count": missing_metric_count,
            "coverage_ratio": coverage_ratio
        },
        "earnings_state": earnings_state,
        "profitability": profitability,
        "growth": growth,
        "valuation": valuation,
        "balance_sheet": balance_sheet,
        "summary_flags": summary_flags
    }


def get_multi_fundamental_state(
    tickers_or_contexts: List[Union[str, Dict[str, Any]]]
) -> Dict[str, Dict[str, Any]]:
    """
    복수 종목에 대한 Fundamental State를 고속 산출합니다.
    """
    results: Dict[str, Dict[str, Any]] = {}
    for item in tickers_or_contexts:
        state = get_fundamental_state(item)
        t = state.get("ticker", "")
        results[t] = state
    return results
