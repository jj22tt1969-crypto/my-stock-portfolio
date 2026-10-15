import os
import time
import logging
import threading
from typing import Dict, Any, Optional, List, Tuple

from backend.data.fundamental_collector import (
    load_fundamental_snapshot,
    DEFAULT_SNAPSHOT_PATH,
    DEFAULT_BASE_SNAPSHOT_PATH,
    DEFAULT_SEED_SNAPSHOT_PATH
)
from backend.engine.stock_identifier import get_stock_by_ticker_or_name

logger = logging.getLogger(__name__)

# 전역 메모리 캐시 및 스레드 동기화 락
_SNAPSHOT_CACHE: Optional[Dict[str, Any]] = None
_SNAPSHOT_SIGNATURE: Optional[Tuple[Tuple[str, float], ...]] = None
_SNAPSHOT_MTIME: float = 0.0
_SNAPSHOT_PATH_USED: Optional[str] = None
_CACHE_LOCK = threading.Lock()

# 13대 핵심 재무 지표 표준 키
FUNDAMENTAL_METRIC_KEYS = [
    "per", "pbr", "eps", "bps", "dps",
    "roe", "operating_margin", "net_margin",
    "debt_ratio", "quick_ratio",
    "revenue", "operating_profit", "net_profit"
]


def _get_snapshot_signature() -> Tuple[Tuple[str, float], ...]:
    """
    Runtime, Base, Seed 3개 파일의 존재 여부 및 mtime signature를 반환합니다.
    파일 미존재 시 mtime은 -1.0으로 표현됩니다.
    """
    candidates = (
        DEFAULT_SNAPSHOT_PATH,
        DEFAULT_BASE_SNAPSHOT_PATH,
        DEFAULT_SEED_SNAPSHOT_PATH,
    )
    sig = []
    for cand in candidates:
        try:
            mtime = os.path.getmtime(cand) if os.path.exists(cand) else -1.0
        except OSError:
            mtime = -1.0
        sig.append((cand, mtime))
    return tuple(sig)


def get_fundamental_snapshot_cache(force_reload: bool = False) -> Optional[Dict[str, Any]]:
    """
    Fundamental Snapshot을 메모리에 1회 로딩하여 캐싱합니다.
    - Loader 우선순위:
      1. Runtime snapshot JSON (fundamental_snapshot.json)
      2. Base snapshot Gzip (fundamental_base_snapshot.json.gz)
      3. Seed snapshot JSON (fundamental_seed_snapshot.json)
    - 외부 API 호출 절대 금지
    - Engine 내부 json/gzip 직접 파싱 금지 -> load_fundamental_snapshot 단일 위임
    - Cache Invalidation: Runtime/Base/Seed 3개 파일의 existence + mtime signature 기반
    """
    global _SNAPSHOT_CACHE, _SNAPSHOT_SIGNATURE, _SNAPSHOT_MTIME, _SNAPSHOT_PATH_USED

    current_sig = _get_snapshot_signature()

    # 후보 파일이 디스크에 아예 하나도 존재하지 않는 경우
    if all(mtime == -1.0 for _, mtime in current_sig):
        return None

    # 캐시가 유효하고 3개 파일의 시그니처 변경이 없으면 0ms 즉시 반환 (Warm Cache)
    if (
        not force_reload
        and _SNAPSHOT_CACHE is not None
        and _SNAPSHOT_SIGNATURE == current_sig
    ):
        return _SNAPSHOT_CACHE

    with _CACHE_LOCK:
        if (
            not force_reload
            and _SNAPSHOT_CACHE is not None
            and _SNAPSHOT_SIGNATURE == current_sig
        ):
            return _SNAPSHOT_CACHE

        t0 = time.perf_counter()
        loaded, source_path = load_fundamental_snapshot(return_source_path=True)
        t1 = time.perf_counter()

        if loaded and source_path:
            try:
                real_mtime = os.path.getmtime(source_path)
            except OSError:
                real_mtime = 0.0

            _SNAPSHOT_CACHE = loaded
            _SNAPSHOT_SIGNATURE = current_sig
            _SNAPSHOT_MTIME = real_mtime
            _SNAPSHOT_PATH_USED = source_path
            load_ms = round((t1 - t0) * 1000, 2)
            total_stocks = len(loaded.get("stocks", {}))
            source_name = os.path.basename(source_path)
            logger.info(
                f"[FundamentalEngine] Snapshot cache loaded from {source_name} "
                f"({total_stocks} stocks, {load_ms} ms)"
            )
            return _SNAPSHOT_CACHE
        else:
            logger.warning("[FundamentalEngine] Failed to load snapshot from any candidate")
            _SNAPSHOT_CACHE = None
            _SNAPSHOT_SIGNATURE = current_sig
            _SNAPSHOT_MTIME = 0.0
            _SNAPSHOT_PATH_USED = None
            return None


def _calculate_growth(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """
    전년 대비 성장률(%) 계산 (YoY).
    - 분모 0 또는 결측치(None)이면 null(None) 반환 (Missing != 0 준수)
    - 음수 분모는 abs(previous)를 사용하여 회계적 증감 방향 보존
    """
    if current is None or previous is None:
        return None
    if previous == 0:
        return None

    diff = current - previous
    growth = (diff / abs(previous)) * 100.0
    return round(growth, 2)


def _extract_metrics_for_period(
    metrics_dict: Dict[str, Any],
    period_key: str
) -> Dict[str, Optional[float]]:
    """
    특정 결산 기간(period_key)에 대한 13대 핵심 지표 값을 추출합니다.
    - 결측치는 0으로 채우지 않고 None 유지 (Missing != 0 규칙)
    """
    extracted: Dict[str, Optional[float]] = {}
    for k in FUNDAMENTAL_METRIC_KEYS:
        metric_data = metrics_dict.get(k)
        if metric_data and isinstance(metric_data, dict):
            values_map = metric_data.get("values", {})
            val = values_map.get(period_key)
            extracted[k] = val if val is not None else None
        else:
            extracted[k] = None
    return extracted


def get_fundamental_context(ticker: str) -> Dict[str, Any]:
    """
    지정된 종목(ticker)에 대한 Fundamental Context를 반환합니다.

    [상태 구분]
    - SUCCESS: 정상 재무 데이터 및 Actual 실적 확보
    - NO_FINANCE_DATA: Naver 재무 미제공 종목 (스팩, 인프라펀드, 일부 코넥스 등 - 재무불량으로 판단하지 않음)
    - NOT_APPLICABLE: ETF 종목 (기업 고유의 재무제표가 성립되지 않는 자산)
    """
    clean_ticker = str(ticker).strip().zfill(6)

    # 0. ETF 종목 사전 식별 (ETF 요청만으로 2MB Gzip/29MB 대용량 캐시가 로드되는 것을 방지)
    import backend.engine.krx_loader as kl
    stock_info = kl._KRX_TICKER_MAP.get(clean_ticker)
    if not stock_info and not kl._KRX_TICKER_MAP:
        from backend.engine.stock_identifier import STOCK_ETF_MASTER
        for it in STOCK_ETF_MASTER:
            if it.get("ticker") == clean_ticker:
                stock_info = it
                break
    if not stock_info:
        stock_info = get_stock_by_ticker_or_name(clean_ticker)

    if stock_info and (stock_info.get("asset_type") == "ETF" or stock_info.get("market") == "ETF"):
        return {
            "ticker": clean_ticker,
            "name": stock_info.get("name", clean_ticker),
            "market": "ETF",
            "asset_type": "ETF",
            "status": "NOT_APPLICABLE",
            "status_reason": "ETF is not applicable for corporate fundamental metrics",
            "collected_at": None,
            "annual": None,
            "quarter": None,
            "summary": None
        }

    # 1. STOCK 종목인 경우에만 비로소 스냅샷 메모리 캐시 확보 (Lazy Load)
    cache = get_fundamental_snapshot_cache()
    stock_record = cache.get("stocks", {}).get(clean_ticker) if cache else None

    # 2. 스냅샷에 존재하는 경우 (STOCK 확정, O(1) 즉시 처리)
    if stock_record:
        name = stock_record.get("name", clean_ticker)
        market = stock_record.get("market", "KOSPI")
        asset_type = "STOCK"
    else:
        # 스냅샷에 없는 경우: ETF 또는 미제공 종목인지 재확인
        if not kl._KRX_TICKER_MAP:
            kl.load_krx_all_stocks()
            stock_info = kl._KRX_TICKER_MAP.get(clean_ticker)
            if not stock_info:
                stock_info = get_stock_by_ticker_or_name(clean_ticker)

        name = stock_info.get("name", clean_ticker) if stock_info else clean_ticker
        market = stock_info.get("market", "UNKNOWN") if stock_info else "UNKNOWN"
        asset_type = stock_info.get("asset_type", "STOCK") if stock_info else "STOCK"

        # ETF 자산군인 경우 즉시 NOT_APPLICABLE 반환
        if asset_type == "ETF" or market == "ETF":
            return {
                "ticker": clean_ticker,
                "name": name,
                "market": "ETF",
                "asset_type": "ETF",
                "status": "NOT_APPLICABLE",
                "status_reason": "ETF is not applicable for corporate fundamental metrics",
                "collected_at": None,
                "annual": None,
                "quarter": None,
                "summary": None
            }

        # Naver 재무 미제공 종목 (재무불량으로 판단하지 않고 데이터 부재로 안전 격리)
        return {
            "ticker": clean_ticker,
            "name": name,
            "market": market,
            "asset_type": "STOCK",
            "status": "NO_FINANCE_DATA",
            "status_reason": "No finance data available from source (not treated as financial distress)",
            "collected_at": None,
            "annual": None,
            "quarter": None,
            "summary": None
        }

    record_name = stock_record.get("name", name)
    record_market = stock_record.get("market", market)
    collected_at = stock_record.get("collected_at")
    summary = stock_record.get("summary")

    # 3. Annual 데이터 파싱 (Actual vs Consensus 엄격 분리)
    annual_raw = stock_record.get("annual", {})
    annual_periods: List[Dict[str, Any]] = annual_raw.get("periods", [])
    annual_metrics: Dict[str, Any] = annual_raw.get("metrics", {})

    actual_annual_periods = [p for p in annual_periods if not p.get("is_consensus")]
    consensus_annual_periods = [p for p in annual_periods if p.get("is_consensus")]

    latest_annual_actual = None
    previous_annual_actual = None
    annual_growth = {
        "revenue_growth": None,
        "operating_profit_growth": None,
        "net_profit_growth": None
    }

    if actual_annual_periods:
        p_latest = actual_annual_periods[-1]
        latest_key = p_latest.get("key")
        latest_metrics = _extract_metrics_for_period(annual_metrics, latest_key)
        latest_annual_actual = {
            "key": latest_key,
            "fiscal_period": p_latest.get("fiscal_period"),
            "is_consensus": False,
            "metrics": latest_metrics
        }

        if len(actual_annual_periods) >= 2:
            p_prev = actual_annual_periods[-2]
            prev_key = p_prev.get("key")
            prev_metrics = _extract_metrics_for_period(annual_metrics, prev_key)
            previous_annual_actual = {
                "key": prev_key,
                "fiscal_period": p_prev.get("fiscal_period"),
                "is_consensus": False,
                "metrics": prev_metrics
            }

            # 실제 비교 가능한 확정 Actual 기간이 존재할 때만 Growth 계산 (Consensus 절대 불포함)
            annual_growth["revenue_growth"] = _calculate_growth(
                latest_metrics.get("revenue"), prev_metrics.get("revenue")
            )
            annual_growth["operating_profit_growth"] = _calculate_growth(
                latest_metrics.get("operating_profit"), prev_metrics.get("operating_profit")
            )
            annual_growth["net_profit_growth"] = _calculate_growth(
                latest_metrics.get("net_profit"), prev_metrics.get("net_profit")
            )

    annual_consensus = None
    if consensus_annual_periods:
        p_con = consensus_annual_periods[0]
        con_key = p_con.get("key")
        con_metrics = _extract_metrics_for_period(annual_metrics, con_key)
        annual_consensus = {
            "key": con_key,
            "fiscal_period": p_con.get("fiscal_period"),
            "is_consensus": True,
            "metrics": con_metrics
        }

    annual_context = {
        "latest_actual": latest_annual_actual,
        "previous_actual": previous_annual_actual,
        "consensus": annual_consensus,
        "growth": annual_growth
    }

    # 4. Quarter 데이터 파싱 (Actual vs Consensus 엄격 분리)
    quarter_raw = stock_record.get("quarter", {})
    quarter_periods: List[Dict[str, Any]] = quarter_raw.get("periods", [])
    quarter_metrics: Dict[str, Any] = quarter_raw.get("metrics", {})

    actual_quarter_periods = [p for p in quarter_periods if not p.get("is_consensus")]
    consensus_quarter_periods = [p for p in quarter_periods if p.get("is_consensus")]

    latest_quarter_actual = None
    if actual_quarter_periods:
        pq_latest = actual_quarter_periods[-1]
        q_latest_key = pq_latest.get("key")
        q_latest_metrics = _extract_metrics_for_period(quarter_metrics, q_latest_key)
        latest_quarter_actual = {
            "key": q_latest_key,
            "fiscal_period": pq_latest.get("fiscal_period"),
            "is_consensus": False,
            "metrics": q_latest_metrics
        }

    quarter_consensus = None
    if consensus_quarter_periods:
        pq_con = consensus_quarter_periods[0]
        q_con_key = pq_con.get("key")
        q_con_metrics = _extract_metrics_for_period(quarter_metrics, q_con_key)
        quarter_consensus = {
            "key": q_con_key,
            "fiscal_period": pq_con.get("fiscal_period"),
            "is_consensus": True,
            "metrics": q_con_metrics
        }

    quarter_context = {
        "latest_actual": latest_quarter_actual,
        "consensus": quarter_consensus
    }

    # 유효 Actual 실적이 전혀 없는 경우 NO_FINANCE_DATA로 처리
    if not latest_annual_actual and not latest_quarter_actual:
        return {
            "ticker": clean_ticker,
            "name": record_name,
            "market": record_market,
            "asset_type": "STOCK",
            "status": "NO_FINANCE_DATA",
            "status_reason": "No actual period financial records found",
            "collected_at": collected_at,
            "annual": None,
            "quarter": None,
            "summary": summary
        }

    return {
        "ticker": clean_ticker,
        "name": record_name,
        "market": record_market,
        "asset_type": "STOCK",
        "status": "SUCCESS",
        "status_reason": None,
        "collected_at": collected_at,
        "annual": annual_context,
        "quarter": quarter_context,
        "summary": summary
    }


def get_multi_fundamental_context(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    복수 종목에 대한 Fundamental Context를 고속 조회합니다.
    """
    results: Dict[str, Dict[str, Any]] = {}
    for t in tickers:
        clean_t = str(t).strip().zfill(6)
        results[clean_t] = get_fundamental_context(clean_t)
    return results
