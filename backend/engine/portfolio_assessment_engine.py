import copy
import logging
import statistics
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from backend.engine.fundamental_engine import get_fundamental_context
from backend.engine.portfolio_engine import analyze_portfolio

logger = logging.getLogger(__name__)


def _classify_growth_status(current: Optional[float], previous: Optional[float]) -> str:
    """
    실적 성장 상태 분류:
    - NORMAL_GROWTH: prev > 0 and curr > 0
    - TURNAROUND: prev < 0 and curr > 0 (흑자 전환)
    - LOSS_WIDENING: prev < 0 and curr <= prev (적자 확대)
    - DEFICIT_CONTINUATION: prev < 0 and curr < 0 and curr > prev (적자 지속/축소)
    - NOT_COMPARABLE: prev is None or curr is None or prev == 0
    """
    if current is None or previous is None or previous == 0:
        return "NOT_COMPARABLE"

    if previous > 0:
        return "NORMAL_GROWTH"

    # previous < 0 인 경우
    if current > 0:
        return "TURNAROUND"
    elif current <= previous:
        return "LOSS_WIDENING"
    else:
        return "DEFICIT_CONTINUATION"


def _aggregate_metric(
    stock_items: List[Dict[str, Any]],
    metric_extractor_fn,
    total_stock_count: int,
    exclude_le_zero: bool = False
) -> Dict[str, Any]:
    """
    단일 지표에 대한 단순 평균, 가중 평균(평가금액 가중치), 중앙값 및 커버리지를 계산합니다.
    """
    valid_entries: List[Tuple[float, float]] = []  # (value, eval_amount)
    excluded_count = 0

    for item in stock_items:
        val = metric_extractor_fn(item)
        eval_amt = float(item.get("eval_amount", 0.0))

        if val is None:
            continue

        if exclude_le_zero and val <= 0:
            excluded_count += 1
            continue

        valid_entries.append((float(val), max(eval_amt, 0.0)))

    valid_count = len(valid_entries)
    valid_coverage = round((valid_count / total_stock_count * 100.0), 2) if total_stock_count > 0 else 0.0

    if not valid_entries:
        res = {
            "valid_count": 0,
            "valid_coverage": valid_coverage,
            "simple_average": None,
            "weighted_average": None,
            "median": None
        }
        if exclude_le_zero:
            res["excluded_loss_stocks_count"] = excluded_count
        return res

    values = [e[0] for e in valid_entries]
    eval_amounts = [e[1] for e in valid_entries]
    total_valid_eval = sum(eval_amounts)

    # 1. 단순 평균
    simple_avg = round(sum(values) / len(values), 2)

    # 2. 중앙값 (Median)
    med = round(statistics.median(values), 2)

    # 3. 평가금액 가중 평균
    if total_valid_eval > 0:
        weighted_avg = round(sum(v * (w / total_valid_eval) for v, w in zip(values, eval_amounts)), 2)
    else:
        weighted_avg = simple_avg

    res = {
        "valid_count": valid_count,
        "valid_coverage": valid_coverage,
        "simple_average": simple_avg,
        "weighted_average": weighted_avg,
        "median": med
    }
    if exclude_le_zero:
        res["excluded_loss_stocks_count"] = excluded_count

    return res


def _aggregate_growth_metric(
    stock_items: List[Dict[str, Any]],
    growth_key: str,
    total_stock_count: int
) -> Dict[str, Any]:
    """
    성장률 지표(revenue_growth, operating_profit_growth, net_profit_growth)에 대한 집계.
    - growth_status == 'NORMAL_GROWTH' (전년 흑자 & 당해 흑자)인 종목만 weighted_average, simple_average, median 계산에 사용.
    - TURNAROUND, DEFICIT_CONTINUATION, LOSS_WIDENING, NOT_COMPARABLE은 평균 계산에서 엄격히 제외하여 왜곡 방지.
    - 제외된 상태의 raw 값은 유지되며, excluded_status_counts 및 별도 distribution으로 보존.
    """
    status_key = f"{growth_key}_status"
    valid_entries: List[Tuple[float, float]] = []

    excluded_status_counts = {
        "TURNAROUND": 0,
        "DEFICIT_CONTINUATION": 0,
        "LOSS_WIDENING": 0,
        "NOT_COMPARABLE": 0
    }

    for item in stock_items:
        ann = item.get("fundamental", {}).get("annual", {})
        if not ann:
            excluded_status_counts["NOT_COMPARABLE"] += 1
            continue

        growth_info = ann.get("growth", {})
        val = growth_info.get(growth_key)
        status = growth_info.get(status_key, "NOT_COMPARABLE")
        eval_amt = float(item.get("eval_amount", 0.0))

        if status == "NORMAL_GROWTH" and val is not None:
            valid_entries.append((float(val), max(eval_amt, 0.0)))
        else:
            if status in excluded_status_counts:
                excluded_status_counts[status] += 1
            else:
                excluded_status_counts["NOT_COMPARABLE"] += 1

    valid_count = len(valid_entries)
    valid_coverage = round((valid_count / total_stock_count * 100.0), 2) if total_stock_count > 0 else 0.0

    if not valid_entries:
        return {
            "valid_count": 0,
            "valid_coverage": valid_coverage,
            "simple_average": None,
            "weighted_average": None,
            "median": None,
            "excluded_status_counts": excluded_status_counts
        }

    values = [e[0] for e in valid_entries]
    eval_amounts = [e[1] for e in valid_entries]
    total_valid_eval = sum(eval_amounts)

    simple_avg = round(sum(values) / len(values), 2)
    med = round(statistics.median(values), 2)
    if total_valid_eval > 0:
        weighted_avg = round(sum(v * (w / total_valid_eval) for v, w in zip(values, eval_amounts)), 2)
    else:
        weighted_avg = simple_avg

    return {
        "valid_count": valid_count,
        "valid_coverage": valid_coverage,
        "simple_average": simple_avg,
        "weighted_average": weighted_avg,
        "median": med,
        "excluded_status_counts": excluded_status_counts
    }


def assess_portfolio_fundamentals(
    portfolio_data: Optional[Dict[str, Any]] = None,
    asset_type: str = "STOCK"
) -> Dict[str, Any]:
    """
    현재 보유 포트폴리오와 Fundamental Context를 네트워크 호출 없이 결합하여 평가 Context를 산출합니다.

    - 기존 portfolio_engine의 보유종목/현재가/평가금액 결과를 그대로 재사용 (현재가 재수집/DB 중복조회 금지)
    - STOCK: Fundamental 적용 및 Coverage 산출
    - ETF: Fundamental NOT_APPLICABLE, Coverage 분모에서 완전 제외
    - 종합 점수 및 등급 산출 금지 (사실 데이터 기반 집계만 산출)
    """
    # 1. 포트폴리오 데이터 확보 (주어지지 않은 경우 기존 analyze_portfolio 1회 호출)
    if portfolio_data is None:
        source_portfolio = analyze_portfolio(asset_type=asset_type)
    else:
        source_portfolio = portfolio_data

    # 원본 불변성 보장 (Deepcopy)
    portfolio_copy = copy.deepcopy(source_portfolio)
    raw_items: List[Dict[str, Any]] = portfolio_copy.get("items", [])

    now_iso = datetime.now(timezone.utc).isoformat()

    if not raw_items:
        return {
            "status": "EMPTY",
            "analyzed_at": now_iso,
            "asset_type": asset_type,
            "portfolio_summary": {
                "total_items_count": 0,
                "stock_count": 0,
                "etf_count": 0,
                "stock_market_value": 0.0,
                "etf_market_value": 0.0,
                "total_market_value": 0.0
            },
            "coverage": {
                "stock_count": 0,
                "fundamental_success_count": 0,
                "no_finance_data_count": 0,
                "coverage_by_count": 0.0,
                "stock_market_value": 0.0,
                "fundamental_covered_market_value": 0.0,
                "coverage_by_value": 0.0
            },
            "raw_assessment": None,
            "items": []
        }

    # 2. 종목별 Fundamental 결합 및 STOCK / ETF 분리
    enriched_items: List[Dict[str, Any]] = []
    stock_items: List[Dict[str, Any]] = []
    etf_items: List[Dict[str, Any]] = []

    total_market_val = 0.0
    stock_market_val = 0.0
    etf_market_val = 0.0

    for item in raw_items:
        ticker = item.get("ticker", "")
        item_asset_type = item.get("asset_type", "STOCK")
        eval_amt = float(item.get("eval_amount", 0.0))
        total_market_val += eval_amt

        # fundamental_engine 조회 (0ms 메모리 캐시 룩업)
        f_ctx = get_fundamental_context(ticker)
        item_asset_type = item.get("asset_type") or f_ctx.get("asset_type", "STOCK")

        # Growth에 턴어라운드/적자상태 태그 추가
        annual_data = f_ctx.get("annual")
        if annual_data and isinstance(annual_data, dict):
            growth_info = annual_data.get("growth") or {}
            latest_act = annual_data.get("latest_actual") or {}
            prev_act = annual_data.get("previous_actual") or {}

            latest_m = latest_act.get("metrics") or {}
            prev_m = prev_act.get("metrics") or {}

            growth_info["revenue_growth_status"] = _classify_growth_status(
                latest_m.get("revenue"), prev_m.get("revenue")
            )
            growth_info["operating_profit_growth_status"] = _classify_growth_status(
                latest_m.get("operating_profit"), prev_m.get("operating_profit")
            )
            growth_info["net_profit_growth_status"] = _classify_growth_status(
                latest_m.get("net_profit"), prev_m.get("net_profit")
            )
            annual_data["growth"] = growth_info

        enriched_item = {
            **item,
            "asset_type": item_asset_type,
            "market_value": eval_amt,
            "portfolio_weight": item.get("weight", 0.0),
            "profit_rate": item.get("return_rate", 0.0),
            "fundamental": f_ctx
        }

        # 자산군별 분류 (Fundamental 상태가 NOT_APPLICABLE이거나 asset_type이 ETF인 경우)
        if item_asset_type == "ETF" or f_ctx.get("status") == "NOT_APPLICABLE":
            etf_market_val += eval_amt
            etf_items.append(enriched_item)
        else:
            stock_market_val += eval_amt
            stock_items.append(enriched_item)

        enriched_items.append(enriched_item)

    stock_count = len(stock_items)
    etf_count = len(etf_items)

    # 3. Portfolio Coverage 산출 (STOCK 기준)
    fund_success_stocks = [s for s in stock_items if s["fundamental"].get("status") == "SUCCESS"]
    no_finance_stocks = [s for s in stock_items if s["fundamental"].get("status") == "NO_FINANCE_DATA"]

    fund_success_count = len(fund_success_stocks)
    no_finance_count = len(no_finance_stocks)

    coverage_by_count = round((fund_success_count / stock_count * 100.0), 2) if stock_count > 0 else 0.0

    covered_market_val = sum(s.get("market_value", 0.0) for s in fund_success_stocks)
    coverage_by_value = round((covered_market_val / stock_market_val * 100.0), 2) if stock_market_val > 0 else 0.0

    # 4. Raw Metrics 집계 (단순평균, 금액가중평균, 중앙값, 커버리지)
    # Helper extractors
    def _get_metric_val(item, key):
        ann = item.get("fundamental", {}).get("annual", {})
        if not ann:
            return None
        latest = ann.get("latest_actual", {})
        if not latest:
            return None
        return latest.get("metrics", {}).get(key)

    def _get_growth_val(item, key):
        ann = item.get("fundamental", {}).get("annual", {})
        if not ann:
            return None
        return ann.get("growth", {}).get(key)

    metrics_assessment = {
        "per": _aggregate_metric(stock_items, lambda it: _get_metric_val(it, "per"), stock_count, exclude_le_zero=True),
        "pbr": _aggregate_metric(stock_items, lambda it: _get_metric_val(it, "pbr"), stock_count),
        "roe": _aggregate_metric(stock_items, lambda it: _get_metric_val(it, "roe"), stock_count),
        "debt_ratio": _aggregate_metric(stock_items, lambda it: _get_metric_val(it, "debt_ratio"), stock_count),
        "operating_margin": _aggregate_metric(stock_items, lambda it: _get_metric_val(it, "operating_margin"), stock_count),
        "net_margin": _aggregate_metric(stock_items, lambda it: _get_metric_val(it, "net_margin"), stock_count),
        "revenue_growth": _aggregate_growth_metric(stock_items, "revenue_growth", stock_count),
        "operating_profit_growth": _aggregate_growth_metric(stock_items, "operating_profit_growth", stock_count),
        "net_profit_growth": _aggregate_growth_metric(stock_items, "net_profit_growth", stock_count)
    }

    # 5. Earnings 및 Growth 분포 집계 (Positive / Negative 비중)
    pos_net_income_stocks = []
    neg_net_income_stocks = []
    for it in stock_items:
        net_profit = _get_metric_val(it, "net_profit")
        if net_profit is not None:
            if net_profit > 0:
                pos_net_income_stocks.append(it)
            elif net_profit < 0:
                neg_net_income_stocks.append(it)

    pos_op_growth_stocks = []
    neg_op_growth_stocks = []
    for it in stock_items:
        op_g = _get_growth_val(it, "operating_profit_growth")
        if op_g is not None:
            if op_g > 0:
                pos_op_growth_stocks.append(it)
            elif op_g < 0:
                neg_op_growth_stocks.append(it)

    pos_net_growth_stocks = []
    neg_net_growth_stocks = []
    for it in stock_items:
        net_g = _get_growth_val(it, "net_profit_growth")
        if net_g is not None:
            if net_g > 0:
                pos_net_growth_stocks.append(it)
            elif net_g < 0:
                neg_net_growth_stocks.append(it)

    def _calc_dist(sub_items):
        cnt = len(sub_items)
        amt = sum(float(x.get("market_value", 0.0)) for x in sub_items)
        return {
            "count": cnt,
            "count_ratio": round((cnt / stock_count * 100.0), 2) if stock_count > 0 else 0.0,
            "market_value": round(amt, 2),
            "value_ratio": round((amt / stock_market_val * 100.0), 2) if stock_market_val > 0 else 0.0
        }

    earnings_distribution = {
        "positive_net_income": _calc_dist(pos_net_income_stocks),
        "negative_net_income": _calc_dist(neg_net_income_stocks)
    }

    growth_distribution = {
        "operating_profit_growth": {
            "positive": _calc_dist(pos_op_growth_stocks),
            "negative": _calc_dist(neg_op_growth_stocks)
        },
        "net_profit_growth": {
            "positive": _calc_dist(pos_net_growth_stocks),
            "negative": _calc_dist(neg_net_growth_stocks)
        }
    }

    # 6. Turnaround / Deficit 상태별 분포 집계 (제외된 상태의 count / value_ratio 보존)
    def _calc_growth_status_distribution(metric_key):
        status_key = f"{metric_key}_status"
        res_dist = {}
        for st in ["NORMAL_GROWTH", "TURNAROUND", "DEFICIT_CONTINUATION", "LOSS_WIDENING", "NOT_COMPARABLE"]:
            sub = [
                it for it in stock_items 
                if it.get("fundamental", {}).get("annual", {}).get("growth", {}).get(status_key) == st
            ]
            res_dist[st] = _calc_dist(sub)
        return res_dist

    growth_status_distribution = {
        "revenue_growth": _calc_growth_status_distribution("revenue_growth"),
        "operating_profit_growth": _calc_growth_status_distribution("operating_profit_growth"),
        "net_profit_growth": _calc_growth_status_distribution("net_profit_growth")
    }

    # 7. 금융주/업종 식별 여부
    # 프로젝트 내에 전종목 표준 WICS/KSIC 금융업 식별 근거가 없으므로 추측하지 않고 False 반환 (규칙 준수)
    sector_adjustment_available = False

    return {
        "status": "SUCCESS",
        "analyzed_at": now_iso,
        "asset_type": asset_type,
        "portfolio_summary": {
            "total_items_count": len(enriched_items),
            "stock_count": stock_count,
            "etf_count": etf_count,
            "stock_market_value": round(stock_market_val, 2),
            "etf_market_value": round(etf_market_val, 2),
            "total_market_value": round(total_market_val, 2)
        },
        "coverage": {
            "stock_count": stock_count,
            "fundamental_success_count": fund_success_count,
            "no_finance_data_count": no_finance_count,
            "coverage_by_count": coverage_by_count,
            "stock_market_value": round(stock_market_val, 2),
            "fundamental_covered_market_value": round(covered_market_val, 2),
            "coverage_by_value": coverage_by_value
        },
        "raw_assessment": {
            "sector_adjustment_available": sector_adjustment_available,
            "metrics": metrics_assessment,
            "earnings_distribution": earnings_distribution,
            "growth_distribution": growth_distribution,
            "growth_status_distribution": growth_status_distribution
        },
        "items": enriched_items
    }
