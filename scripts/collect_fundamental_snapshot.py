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
    수집 대상 전체 STOCK 종목 목록을 반환합니다.
    backend.engine.krx_loader.load_krx_all_stocks()의 전체 KRX Universe를 재사용합니다.
    ETF는 철저히 배제되며, ticker 중복을 제거합니다.
    """
    from backend.engine.krx_loader import load_krx_all_stocks
    
    krx_universe = load_krx_all_stocks()
    candidates: List[Dict[str, str]] = []
    
    if explicit_tickers:
        ticker_set = set(t.strip().zfill(6) for t in explicit_tickers if t.strip())
        master_map = {
            item["ticker"]: item for item in krx_universe 
            if item.get("asset_type") == "STOCK" and item.get("market") != "ETF"
        }
        seen = set()
        for t in explicit_tickers:
            tk = t.strip().zfill(6)
            if not tk or tk in seen:
                continue
            seen.add(tk)
            if tk in master_map:
                candidates.append({
                    "ticker": tk,
                    "name": master_map[tk].get("name", tk),
                    "market": master_map[tk].get("market", "KOSPI")
                })
            else:
                candidates.append({
                    "ticker": tk,
                    "name": tk,
                    "market": "STOCK"
                })
    else:
        seen_tickers = set()
        for item in krx_universe:
            ticker = str(item.get("ticker", "")).strip().zfill(6)
            asset_type = item.get("asset_type")
            market = str(item.get("market", "")).strip().upper()
            
            # asset_type == "STOCK"만 필터, ETF 및 중복 티커 배제
            if asset_type == "STOCK" and market != "ETF":
                if ticker and ticker not in seen_tickers:
                    seen_tickers.add(ticker)
                    candidates.append({
                        "ticker": ticker,
                        "name": item.get("name", ticker),
                        "market": item.get("market", "KOSPI")
                    })

    if limit is not None and limit > 0:
        candidates = candidates[:limit]

    return candidates


def run_fundamental_batch(
    candidates: List[Dict[str, str]],
    output_path: str = DEFAULT_SNAPSHOT_PATH,
    delay: float = 0.05,
    workers: int = 6
) -> Dict[str, Any]:
    """
    지정된 종목들을 대상으로 Naver 재무 데이터를 배치 수집하고 원자적으로 스냅샷을 갱신합니다.
    """
    import concurrent.futures

    logger.info(f"Starting fundamental batch collection for {len(candidates)} stocks (workers={workers})...")
    logger.info(f"Target snapshot path: {output_path}")

    # SSL CA 및 HTTP 세션 준비
    ca_path = get_ssl_ca_bundle_path()
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=workers * 2, pool_maxsize=workers * 2)
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

    start_time = time.time()
    success_count = 0
    fail_count = 0
    failed_details: List[Dict[str, Any]] = []

    def _fetch_single(cand):
        ticker = cand["ticker"]
        name = cand["name"]
        market = cand["market"]
        try:
            fund_data = fetch_stock_fundamental(ticker, session=session, timeout=4.0)
            if delay > 0:
                time.sleep(delay)
            if fund_data and (fund_data.get("annual", {}).get("metrics") or fund_data.get("quarter", {}).get("metrics")):
                fund_data["name"] = name
                fund_data["market"] = market
                return (ticker, name, fund_data, None)
            else:
                return (ticker, name, None, "No finance data returned (empty or not supported)")
        except Exception as e:
            return (ticker, name, None, str(e))

    if workers > 1:
        total_cand = len(candidates)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_cand = {executor.submit(_fetch_single, c): c for c in candidates}
            completed = 0
            for future in concurrent.futures.as_completed(future_to_cand):
                completed += 1
                ticker, name, fund_data, err_reason = future.result()
                if fund_data:
                    stocks_dict[ticker] = fund_data
                    success_count += 1
                else:
                    fail_count += 1
                    failed_details.append({"ticker": ticker, "name": name, "reason": err_reason})

                if completed % 200 == 0 or completed == total_cand:
                    elapsed = round(time.time() - start_time, 1)
                    logger.info(f"Progress: [{completed}/{total_cand}] ({round(completed/total_cand*100, 1)}%) - Success: {success_count}, Fail: {fail_count}, Elapsed: {elapsed}s")
    else:
        for idx, cand in enumerate(candidates, start=1):
            ticker, name, fund_data, err_reason = _fetch_single(cand)
            if fund_data:
                stocks_dict[ticker] = fund_data
                success_count += 1
                logger.info(f"[{idx}/{len(candidates)}] SUCCESS ({ticker})")
            else:
                fail_count += 1
                failed_details.append({"ticker": ticker, "name": name, "reason": err_reason})
                logger.warning(f"[{idx}/{len(candidates)}] FAIL ({ticker}): {err_reason}")

    duration_sec = round(time.time() - start_time, 2)

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
            "batch_fail_count": fail_count,
            "batch_duration_sec": duration_sec,
            "failed_stocks": failed_details
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
        "duration_sec": duration_sec,
        "failed_details": failed_details,
        "atomic_replace_verified": atomic_replace_success,
        "output_path": output_path
    }

    logger.info(f"Batch completed in {duration_sec}s: {summary}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Naver Fundamental Batch Collector (STOCK only)")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of stocks to collect (for testing)")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers (e.g. 005930,000660)")
    parser.add_argument("--output", type=str, default=DEFAULT_SNAPSHOT_PATH, help="Output snapshot path")
    parser.add_argument("--delay", type=float, default=0.03, help="Delay between requests in seconds")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent workers count")

    args = parser.parse_args()

    explicit_tickers = None
    if args.tickers:
        explicit_tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]

    candidates = get_stock_candidates(explicit_tickers=explicit_tickers, limit=args.limit)
    if not candidates:
        logger.error("No valid STOCK candidates found. Exiting.")
        sys.exit(1)

    result = run_fundamental_batch(candidates, output_path=args.output, delay=args.delay, workers=args.workers)
    if not result.get("atomic_replace_verified"):
        sys.exit(1)


if __name__ == "__main__":
    main()
