import os
import sys
import time
import argparse
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import requests

# 프로젝트 루트 경로를 sys.path에 등록
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.data.fundamental_collector import (
    fetch_stock_fundamental,
    atomic_save_snapshot,
    load_fundamental_snapshot,
    DEFAULT_SNAPSHOT_PATH
)
from backend.data.collector import get_ssl_ca_bundle_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("FundamentalBatch")


def get_stock_candidates(explicit_tickers: Optional[List[str]] = None, limit: Optional[int] = None) -> List[Dict[str, str]]:
    """
    수집 대상 STOCK 종목 목록을 반환합니다. ETF는 철저히 배제됩니다.
    """
    from backend.engine.stock_identifier import STOCK_ETF_MASTER
    
    candidates: List[Dict[str, str]] = []
    
    if explicit_tickers:
        ticker_set = set(t.strip().zfill(6) for t in explicit_tickers if t.strip())
        # 마스터에서 이름 및 시장 정보 보완
        master_map = {item["ticker"]: item for item in STOCK_ETF_MASTER if item.get("asset_type") == "STOCK"}
        for t in ticker_set:
            if t in master_map:
                candidates.append({
                    "ticker": t,
                    "name": master_map[t].get("name", t),
                    "market": master_map[t].get("market", "KOSPI")
                })
            else:
                candidates.append({
                    "ticker": t,
                    "name": t,
                    "market": "STOCK"
                })
    else:
        # STOCK_ETF_MASTER에서 asset_type이 STOCK인 종목만 필터링 (ETF 배제)
        for item in STOCK_ETF_MASTER:
            if item.get("asset_type") == "STOCK" and item.get("market") != "ETF":
                candidates.append({
                    "ticker": item["ticker"],
                    "name": item.get("name", item["ticker"]),
                    "market": item.get("market", "KOSPI")
                })

    if limit is not None and limit > 0:
        candidates = candidates[:limit]

    return candidates


def run_fundamental_batch(
    candidates: List[Dict[str, str]],
    output_path: str = DEFAULT_SNAPSHOT_PATH,
    delay: float = 0.2
) -> Dict[str, Any]:
    """
    지정된 종목들을 대상으로 Naver 재무 데이터를 배치 수집하고 원자적으로 스냅샷을 갱신합니다.
    """
    logger.info(f"Starting fundamental batch collection for {len(candidates)} stocks...")
    logger.info(f"Target snapshot path: {output_path}")

    # SSL CA 및 HTTP 세션 준비
    ca_path = get_ssl_ca_bundle_path()
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # 기존 스냅샷(last_good) 로드 시도 (실패 시 빈 dict 기반 생성)
    existing_snapshot = load_fundamental_snapshot(output_path)
    if existing_snapshot:
        logger.info(f"Loaded existing last_good snapshot with {len(existing_snapshot.get('stocks', {}))} stocks.")
        stocks_dict = dict(existing_snapshot.get("stocks", {}))
    else:
        logger.info("No existing snapshot found or invalid. Initializing fresh snapshot store.")
        stocks_dict = {}

    success_count = 0
    fail_count = 0

    for idx, cand in enumerate(candidates, start=1):
        ticker = cand["ticker"]
        name = cand["name"]
        market = cand["market"]
        logger.info(f"[{idx}/{len(candidates)}] Collecting {name} ({ticker})...")

        try:
            fund_data = fetch_stock_fundamental(ticker, session=session, timeout=3.0)
            if fund_data and (fund_data.get("annual", {}).get("metrics") or fund_data.get("quarter", {}).get("metrics")):
                fund_data["name"] = name
                fund_data["market"] = market
                stocks_dict[ticker] = fund_data
                success_count += 1
                logger.info(f"  -> SUCCESS ({ticker})")
            else:
                fail_count += 1
                logger.warning(f"  -> NO DATA or EMPTY ({ticker})")
        except Exception as e:
            fail_count += 1
            logger.error(f"  -> ERROR ({ticker}): {e}")

        if delay > 0 and idx < len(candidates):
            time.sleep(delay)

    # 신규 스냅샷 생성
    snapshot_payload = {
        "metadata": {
            "version": "1.0",
            "source": "naver_finance",
            "target_asset_type": "STOCK",
            "pit_eligible": False,
            "reported_at": None,
            "available_at": None,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "total_stocks_in_snapshot": len(stocks_dict),
            "batch_processed_stocks": len(candidates),
            "batch_success_count": success_count,
            "batch_fail_count": fail_count
        },
        "stocks": stocks_dict
    }

    # Atomic Save 수행
    atomic_replace_success = False
    try:
        atomic_replace_success = atomic_save_snapshot(snapshot_payload, output_path=output_path)
    except Exception as save_err:
        logger.critical(f"Atomic save failed! Existing snapshot preserved: {save_err}")

    summary = {
        "total_candidates": len(candidates),
        "success_count": success_count,
        "fail_count": fail_count,
        "atomic_replace_verified": atomic_replace_success,
        "output_path": output_path
    }

    logger.info(f"Batch completed: {summary}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Naver Fundamental Batch Collector (STOCK only)")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of stocks to collect (for testing)")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers (e.g. 005930,000660)")
    parser.add_argument("--output", type=str, default=DEFAULT_SNAPSHOT_PATH, help="Output snapshot path")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between requests in seconds")

    args = parser.parse_args()

    explicit_tickers = None
    if args.tickers:
        explicit_tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]

    candidates = get_stock_candidates(explicit_tickers=explicit_tickers, limit=args.limit)
    if not candidates:
        logger.error("No valid STOCK candidates found. Exiting.")
        sys.exit(1)

    result = run_fundamental_batch(candidates, output_path=args.output, delay=args.delay)
    if not result.get("atomic_replace_verified"):
        sys.exit(1)


if __name__ == "__main__":
    main()
