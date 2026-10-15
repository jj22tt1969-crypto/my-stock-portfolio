import os
import json
import gzip
import logging
import tempfile
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Union, Tuple
import requests

from backend.data.collector import get_ssl_ca_bundle_path

logger = logging.getLogger(__name__)

# 네이버 모바일 재무 테이블 지표 한글명 -> 표준 영문 키 매핑
METRIC_KEY_MAP = {
    "매출액": "revenue",
    "영업이익": "operating_profit",
    "당기순이익": "net_profit",
    "지배주주순이익": "controlling_net_profit",
    "비지배주주순이익": "non_controlling_net_profit",
    "영업이익률": "operating_margin",
    "순이익률": "net_margin",
    "ROE": "roe",
    "ROE(지배주주)": "roe",
    "부채비율": "debt_ratio",
    "당좌비율": "quick_ratio",
    "유보율": "retention_ratio",
    "EPS": "eps",
    "EPS(원)": "eps",
    "PER": "per",
    "PER(배)": "per",
    "BPS": "bps",
    "BPS(원)": "bps",
    "PBR": "pbr",
    "PBR(배)": "pbr",
    "주당배당금": "dps",
    "주당배당금(원)": "dps",
    "배당수익률": "dividend_yield",
    "배당수익률(%)": "dividend_yield",
    "배당성향": "payout_ratio",
    "배당성향(%)": "payout_ratio",
}

DEFAULT_SNAPSHOT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fundamental_snapshot.json"
)
DEFAULT_BASE_SNAPSHOT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fundamental_base_snapshot.json.gz"
)
DEFAULT_SEED_SNAPSHOT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fundamental_seed_snapshot.json"
)


def parse_numeric_value(raw_val: Any) -> Optional[float]:
    """
    재무 수치 파싱.
    결측치, 공백, 하이픈, None은 절대 0으로 대체하지 않고 None을 반환합니다. (Missing != 0 규칙 준수)
    """
    if raw_val is None:
        return None
    if isinstance(raw_val, (int, float)):
        return float(raw_val)
    
    val_str = str(raw_val).strip().replace(",", "")
    if val_str in ("", "-", "N/A", "NaN", "null", "None", "--"):
        return None
    
    try:
        return float(val_str)
    except (ValueError, TypeError):
        return None


def _parse_finance_section(section_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    네이버 모바일 finance/annual 또는 quarter 응답의 financeInfo 섹션을 파싱합니다.
    actual / consensus 구분 및 fiscal_period를 보존합니다.
    """
    if not section_data or not isinstance(section_data, dict):
        return {"periods": [], "metrics": {}}

    fin_info = section_data.get("financeInfo")
    if not fin_info or not isinstance(fin_info, dict):
        return {"periods": [], "metrics": {}}

    # 1. Periods (결산 기간 메타데이터 파싱 및 보존)
    periods: List[Dict[str, Any]] = []
    raw_titles = fin_info.get("trTitleList", [])
    if isinstance(raw_titles, list):
        for item in raw_titles:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip()
            title = str(item.get("title", "")).strip()
            is_consensus_str = str(item.get("isConsensus", "N")).strip().upper()
            is_consensus = (is_consensus_str == "Y")
            periods.append({
                "key": key,
                "fiscal_period": title,
                "is_consensus": is_consensus
            })

    # 2. Metrics (각 행별 재무 지표 파싱)
    metrics: Dict[str, Any] = {}
    raw_rows = fin_info.get("rowList", [])
    if isinstance(raw_rows, list):
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title", "")).strip()
            if not title:
                continue

            standard_key = METRIC_KEY_MAP.get(title, title)
            cols = row.get("columns", {})
            values_by_period: Dict[str, Optional[float]] = {}

            if isinstance(cols, dict):
                for period_key, cell in cols.items():
                    if isinstance(cell, dict):
                        cell_val = cell.get("value")
                    else:
                        cell_val = cell
                    values_by_period[str(period_key)] = parse_numeric_value(cell_val)

            metrics[standard_key] = {
                "title": title,
                "values": values_by_period
            }

    return {
        "periods": periods,
        "metrics": metrics
    }


def fetch_stock_fundamental(
    ticker: str,
    session: Optional[requests.Session] = None,
    timeout: float = 3.0
) -> Optional[Dict[str, Any]]:
    """
    네이버 모바일 증권 API를 통해 특정 종목의 연간 및 분기 재무 스냅샷을 수집합니다.
    Point-in-Time 공시일자가 없으므로 reported_at=None, available_at=None, pit_eligible=False로 명시합니다.
    """
    ticker_clean = str(ticker).strip().zfill(6)
    ca_path = get_ssl_ca_bundle_path()
    local_session = session or requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"https://m.stock.naver.com/domestic/stock/{ticker_clean}/finance/annual"
    }

    url_annual = f"https://m.stock.naver.com/api/stock/{ticker_clean}/finance/annual"
    url_quarter = f"https://m.stock.naver.com/api/stock/{ticker_clean}/finance/quarter"

    # 수집 시점 타임스탬프 (ISO 8601)
    collected_at = datetime.now(timezone.utc).isoformat()

    data_annual = None
    data_quarter = None

    try:
        resp_a = local_session.get(url_annual, headers=headers, timeout=timeout, verify=ca_path)
        if resp_a.status_code == 200:
            data_annual = resp_a.json()
    except Exception as e:
        logger.warning(f"[{ticker_clean}] Failed to fetch annual fundamental: {e}")

    try:
        resp_q = local_session.get(url_quarter, headers=headers, timeout=timeout, verify=ca_path)
        if resp_q.status_code == 200:
            data_quarter = resp_q.json()
    except Exception as e:
        logger.warning(f"[{ticker_clean}] Failed to fetch quarter fundamental: {e}")

    # 두 응답 모두 유효 데이터(financeInfo)가 전혀 없는 경우 (ETF 또는 미제공 종목)
    has_annual = bool(data_annual and data_annual.get("financeInfo"))
    has_quarter = bool(data_quarter and data_quarter.get("financeInfo"))

    if not has_annual and not has_quarter:
        return None

    parsed_annual = _parse_finance_section(data_annual)
    parsed_quarter = _parse_finance_section(data_quarter)

    # 기업 개요 요약
    summary = None
    if data_annual and isinstance(data_annual.get("corporationSummary"), dict):
        summary = data_annual.get("corporationSummary")
    elif data_quarter and isinstance(data_quarter.get("corporationSummary"), dict):
        summary = data_quarter.get("corporationSummary")

    return {
        "ticker": ticker_clean,
        "collected_at": collected_at,
        "reported_at": None,
        "available_at": None,
        "pit_eligible": False,
        "annual": parsed_annual,
        "quarter": parsed_quarter,
        "summary": summary
    }


def validate_fundamental_snapshot(snapshot: Dict[str, Any]) -> None:
    """
    스냅샷 데이터의 스키마와 무결성을 검증합니다.
    검증 실패 시 ValueError를 발생시킵니다.
    """
    if not isinstance(snapshot, dict):
        raise ValueError("Snapshot root must be a dictionary.")

    metadata = snapshot.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Snapshot must contain a 'metadata' dictionary.")

    # 필수 메타데이터 키 및 조건 검증
    if metadata.get("pit_eligible") is not False:
        raise ValueError("metadata.pit_eligible must be explicitly False.")
    if metadata.get("reported_at") is not None:
        raise ValueError("metadata.reported_at must be None (null).")
    if metadata.get("available_at") is not None:
        raise ValueError("metadata.available_at must be None (null).")
    if not metadata.get("collected_at"):
        raise ValueError("metadata.collected_at must be non-empty.")
    if metadata.get("target_asset_type") != "STOCK":
        raise ValueError("metadata.target_asset_type must be 'STOCK'.")

    stocks = snapshot.get("stocks")
    if not isinstance(stocks, dict):
        raise ValueError("Snapshot must contain a 'stocks' dictionary.")

    for ticker, stock_data in stocks.items():
        if not isinstance(stock_data, dict):
            raise ValueError(f"Stock record for {ticker} must be a dictionary.")
        if stock_data.get("ticker") != ticker:
            raise ValueError(f"Ticker mismatch: key={ticker}, body={stock_data.get('ticker')}")
        if stock_data.get("pit_eligible") is not False:
            raise ValueError(f"Stock {ticker} pit_eligible must be False.")
        if stock_data.get("reported_at") is not None:
            raise ValueError(f"Stock {ticker} reported_at must be None.")
        if stock_data.get("available_at") is not None:
            raise ValueError(f"Stock {ticker} available_at must be None.")
        if not stock_data.get("collected_at"):
            raise ValueError(f"Stock {ticker} collected_at must be non-empty.")
        if "annual" not in stock_data or "quarter" not in stock_data:
            raise ValueError(f"Stock {ticker} must have both 'annual' and 'quarter' keys.")


def atomic_save_snapshot(snapshot: Dict[str, Any], output_path: str = DEFAULT_SNAPSHOT_PATH) -> bool:
    """
    스냅샷을 temp 파일에 기록하고 정합성을 검증한 뒤 원자적으로(atomic replace) 교체합니다.
    실패 시 기존 스냅샷(last_good)을 훼손하지 않습니다.
    """
    # 1. 메모리 상의 데이터 검증
    validate_fundamental_snapshot(snapshot)

    dir_name = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(dir_name, exist_ok=True)

    # 2. 동일 디렉터리 내에 임시 파일 생성
    temp_fd, temp_path = tempfile.mkstemp(prefix="fundamental_snapshot_", suffix=".tmp", dir=dir_name)
    try:
        with open(temp_fd, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        # 3. 작성된 임시 파일을 다시 읽어 재검증
        with open(temp_path, "r", encoding="utf-8") as f:
            reloaded = json.load(f)
            validate_fundamental_snapshot(reloaded)

        # 4. 원자적 치환 (Atomic Replace)
        os.replace(temp_path, output_path)
        logger.info(f"Fundamental snapshot atomically saved to {output_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to atomically save snapshot: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise e


def load_fundamental_snapshot(
    snapshot_path: Optional[str] = None,
    base_path: Optional[str] = None,
    seed_path: Optional[str] = None,
    fallback_to_seed: bool = True,
    return_source_path: bool = False
) -> Union[Optional[Dict[str, Any]], Tuple[Optional[Dict[str, Any]], Optional[str]]]:
    """
    기존 스냅샷 파일을 안전하게 읽어옵니다.
    Loader 우선순위:
    1. Runtime snapshot JSON (기본: DEFAULT_SNAPSHOT_PATH)
    2. Base snapshot Gzip (기본: DEFAULT_BASE_SNAPSHOT_PATH)
    3. Seed snapshot JSON (기본: DEFAULT_SEED_SNAPSHOT_PATH)

    return_source_path: True일 경우 (data, source_path) 튜플 반환, False일 경우 data만 반환 (기존 호환)
    """
    primary_path = snapshot_path or DEFAULT_SNAPSHOT_PATH
    base_snapshot_path = base_path or DEFAULT_BASE_SNAPSHOT_PATH
    fallback_path = seed_path or DEFAULT_SEED_SNAPSHOT_PATH

    loaded_data = None
    loaded_source = None

    # 1. 런타임 스냅샷 우선 로드 (JSON)
    if os.path.exists(primary_path):
        try:
            with open(primary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                validate_fundamental_snapshot(data)
                loaded_data = data
                loaded_source = primary_path
        except Exception as e:
            logger.warning(f"Failed to load or validate runtime snapshot at {primary_path}: {e}")

    # 2. Base 스냅샷 로드 (Gzip JSON)
    if loaded_data is None and os.path.exists(base_snapshot_path):
        try:
            with gzip.open(base_snapshot_path, "rt", encoding="utf-8") as f:
                data = json.load(f)
                validate_fundamental_snapshot(data)
                logger.info(f"Loaded base fundamental snapshot from {base_snapshot_path} (fallback).")
                loaded_data = data
                loaded_source = base_snapshot_path
        except Exception as e:
            logger.warning(f"Failed to load or validate base snapshot at {base_snapshot_path}: {e}")

    # 3. Seed 스냅샷 Fallback 로드 (최후의 수단)
    if loaded_data is None and fallback_to_seed and os.path.exists(fallback_path):
        try:
            with open(fallback_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                validate_fundamental_snapshot(data)
                logger.info(f"Loaded seed fundamental snapshot from {fallback_path} (fallback).")
                loaded_data = data
                loaded_source = fallback_path
        except Exception as e:
            logger.warning(f"Failed to load or validate seed snapshot at {fallback_path}: {e}")

    if return_source_path:
        return loaded_data, loaded_source
    return loaded_data
