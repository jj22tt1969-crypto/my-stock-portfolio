import os
import time
import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 메모리 캐시 및 TTL 설정 (새 DB table, scheduler, 파일 캐시 사용 금지 준수)
# ─────────────────────────────────────────────────────────────
_STOCK_BULK_CACHE: Optional[Dict[str, Any]] = None
_ETF_BULK_CACHE: Optional[Dict[str, Any]] = None
_CACHE_TTL_SECONDS: float = 600.0  # 10분 메모리 캐시


def _ensure_ssl_env():
    """
    certifi CA 번들과 Windows OS System Root CA 번들을 연결하여
    verify=False 사용 없이 정식 SSL 인증 체인 환경 설정
    """
    try:
        from backend.data.collector import get_ssl_ca_bundle_path
        ca_path = get_ssl_ca_bundle_path()
        if ca_path and os.path.exists(ca_path):
            os.environ['SSL_CERT_FILE'] = ca_path
            os.environ['REQUESTS_CA_BUNDLE'] = ca_path
    except Exception as e:
        logger.warning(f"[Screener] SSL CA bundle env setup warning: {e}")


def _fetch_fdr_krx_listing() -> pd.DataFrame:
    """
    FinanceDataReader(fdr.StockListing('KRX')) Bulk 호출
    """
    _ensure_ssl_env()
    import FinanceDataReader as fdr
    return fdr.StockListing('KRX')


def _fetch_fdr_etf_listing() -> pd.DataFrame:
    """
    FinanceDataReader(fdr.StockListing('ETF/KR')) Bulk 호출
    """
    _ensure_ssl_env()
    import FinanceDataReader as fdr
    return fdr.StockListing('ETF/KR')


def screen_stock_universe(target_count: int = 100, force_reload: bool = False) -> Dict[str, Any]:
    """
    KOSPI / KOSDAQ 전체 개별주 대상 Stage 1 고속 1차 유동성 스크리너
    - 외부 종목별 API 호출 0건
    - 스팩, 우선주, 리츠, KONEX, 거래정지, NaN 100% 제거
    - 급등주 편향 방지 및 유동성(거래대금/시가총액) 안전 후보군 압축
    """
    global _STOCK_BULK_CACHE
    now = time.time()

    cache_hit = False
    fetch_time = 0.0

    # 1. 메모리 캐시 확인
    if not force_reload and _STOCK_BULK_CACHE is not None:
        cached_ts = _STOCK_BULK_CACHE.get("ts", 0)
        if now - cached_ts < _CACHE_TTL_SECONDS:
            cache_hit = True
            df_krx = _STOCK_BULK_CACHE.get("df")
        else:
            _STOCK_BULK_CACHE = None

    # 2. 캐시 미스 시 Bulk 데이터 Fetch
    if not cache_hit:
        t_start_fetch = time.time()
        try:
            df_krx = _fetch_fdr_krx_listing()
            fetch_time = time.time() - t_start_fetch
            if df_krx is None or df_krx.empty:
                return {
                    "status": "unavailable",
                    "error": "FDR KRX bulk listing returned empty data.",
                    "total_input_count": 0,
                    "candidates": []
                }
            _STOCK_BULK_CACHE = {"ts": now, "df": df_krx}
        except Exception as e:
            logger.error(f"[Screener] FDR KRX bulk fetch failed: {e}")
            return {
                "status": "unavailable",
                "error": f"KRX Universe bulk fetch failed: {str(e)}",
                "total_input_count": 0,
                "candidates": []
            }

    total_input_count = len(df_krx)

    # 3. 데이터 품질 및 분류 필터링 (Filter Stage)
    t_start_filter = time.time()

    # 기본 필수 컬럼 및 타입 검증
    required_cols = ['Code', 'Name', 'Market', 'Close', 'Volume', 'Amount', 'Marcap', 'ChagesRatio']
    for col in required_cols:
        if col not in df_krx.columns:
            return {
                "status": "unavailable",
                "error": f"Required column '{col}' missing in KRX listing data.",
                "total_input_count": total_input_count,
                "candidates": []
            }

    # 스팩 (SPAC) 식별
    spacs = df_krx[df_krx['Name'].str.contains('스팩|SPAC', case=False, na=False)]
    
    # 우선주 (Preferred Stock) 식별: 이름 끝자리가 우, 우B, 우(G) 이거나 코드 끝자리가 차수표기(숫자5~9/알파벳)
    pref_name_mask = df_krx['Name'].str.endswith(('우', '우B', '우(G)'))
    pref_code_mask = df_krx['Code'].str.endswith(('5', '6', '7', '8', '9', 'K', 'L', 'M'))
    pref = df_krx[pref_name_mask | pref_code_mask]

    # 리츠 (REITs) 식별
    reits = df_krx[df_krx['Name'].str.contains('리츠|REIT', case=False, na=False)]

    # ETN 식별
    etn = df_krx[df_krx['Name'].str.contains('ETN', case=False, na=False)]

    # 무거래 / 거래정지 / 결손값 식별
    invalid_mask = (
        (df_krx['Close'].isna()) | (df_krx['Close'] <= 0) |
        (df_krx['Volume'].isna()) | (df_krx['Volume'] <= 0) |
        (df_krx['Amount'].isna()) | (df_krx['Amount'] <= 0) |
        (df_krx['Marcap'].isna()) | (df_krx['Marcap'] <= 0) |
        (df_krx['Code'].isna()) | (df_krx['Code'] == '') |
        (df_krx['Name'].isna()) | (df_krx['Name'] == '')
    )
    invalid_rows = df_krx[invalid_mask]

    # KOSPI 및 KOSDAQ (KOSDAQ GLOBAL 포함) 정식 상장 개별주 선별
    valid_market_mask = df_krx['Market'].isin(['KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL'])

    pure_mask = (
        valid_market_mask &
        (~df_krx.index.isin(spacs.index)) &
        (~df_krx.index.isin(pref.index)) &
        (~df_krx.index.isin(reits.index)) &
        (~df_krx.index.isin(etn.index)) &
        (~df_krx.index.isin(invalid_rows.index))
    )

    df_filtered = df_krx[pure_mask].copy()
    filter_time = time.time() - t_start_filter

    filtered_count = len(df_filtered)

    # 4. 정열 및 상위 target_count 후보선정 (Sort Stage)
    t_start_sort = time.time()
    
    # 거래대금(Amount) 내림차순 정렬로 유동성 안전 후보군 선출 (급등주 편향 방지)
    df_sorted = df_filtered.sort_values(by='Amount', ascending=False)
    top_df = df_sorted.head(target_count)
    sort_time = time.time() - t_start_sort

    candidates = []
    for _, row in top_df.iterrows():
        market_str = str(row['Market']).strip()
        # KOSDAQ GLOBAL 은 개별주 마켓 관점에서는 KOSDAQ 카테고리로 통일
        norm_market = "KOSDAQ" if market_str == "KOSDAQ GLOBAL" else market_str

        candidates.append({
            "ticker": str(row['Code']).strip().zfill(6),
            "name": str(row['Name']).strip(),
            "market": norm_market,
            "asset_type": "STOCK",
            "close": int(row['Close']),
            "volume": int(row['Volume']),
            "amount": float(row['Amount']),
            "marcap": float(row['Marcap']),
            "change_ratio": round(float(row['ChagesRatio']), 2) if not pd.isna(row['ChagesRatio']) else 0.0,
            "selection_reason": "high_liquidity"
        })

    total_time = fetch_time + filter_time + sort_time

    return {
        "status": "success",
        "universe_type": "STOCK",
        "cache_hit": cache_hit,
        "total_input_count": total_input_count,
        "filtered_count": filtered_count,
        "target_count": target_count,
        "candidates_count": len(candidates),
        "candidates": candidates,
        "metrics": {
            "fetch_time_sec": round(fetch_time, 6),
            "filter_time_sec": round(filter_time, 6),
            "sort_time_sec": round(sort_time, 6),
            "total_time_sec": round(total_time, 6),
            "api_calls_count": 0
        },
        "breakdown": {
            "spacs_count": len(spacs),
            "preferred_count": len(pref),
            "reits_count": len(reits),
            "etn_count": len(etn),
            "invalid_halted_count": len(invalid_rows)
        }
    }


def screen_etf_universe(target_count: int = 50, force_reload: bool = False) -> Dict[str, Any]:
    """
    국내 상장 ETF 전체 대상 Stage 1 고속 1차 유동성 스크리너
    - 개별주와 100% 별도 Universe로 관리 (STOCK과 ETF 상호 오염 0%)
    - 외부 종목별 API 호출 0건
    """
    global _ETF_BULK_CACHE
    now = time.time()

    cache_hit = False
    fetch_time = 0.0

    # 1. 메모리 캐시 확인
    if not force_reload and _ETF_BULK_CACHE is not None:
        cached_ts = _ETF_BULK_CACHE.get("ts", 0)
        if now - cached_ts < _CACHE_TTL_SECONDS:
            cache_hit = True
            df_etf = _ETF_BULK_CACHE.get("df")
        else:
            _ETF_BULK_CACHE = None

    # 2. 캐시 미스 시 Bulk 데이터 Fetch
    if not cache_hit:
        t_start_fetch = time.time()
        try:
            df_etf = _fetch_fdr_etf_listing()
            fetch_time = time.time() - t_start_fetch
            if df_etf is None or df_etf.empty:
                return {
                    "status": "unavailable",
                    "error": "FDR ETF bulk listing returned empty data.",
                    "total_input_count": 0,
                    "candidates": []
                }
            _ETF_BULK_CACHE = {"ts": now, "df": df_etf}
        except Exception as e:
            logger.error(f"[Screener] FDR ETF bulk fetch failed: {e}")
            return {
                "status": "unavailable",
                "error": f"ETF Universe bulk fetch failed: {str(e)}",
                "total_input_count": 0,
                "candidates": []
            }

    total_input_count = len(df_etf)

    # 3. 데이터 품질 및 분류 필터링
    t_start_filter = time.time()

    required_cols = ['Symbol', 'Name', 'Price', 'Volume', 'Amount', 'MarCap', 'ChangeRate']
    for col in required_cols:
        if col not in df_etf.columns:
            return {
                "status": "unavailable",
                "error": f"Required column '{col}' missing in ETF listing data.",
                "total_input_count": total_input_count,
                "candidates": []
            }

    invalid_mask = (
        (df_etf['Price'].isna()) | (df_etf['Price'] <= 0) |
        (df_etf['Volume'].isna()) | (df_etf['Volume'] <= 0) |
        (df_etf['Amount'].isna()) | (df_etf['Amount'] <= 0) |
        (df_etf['Symbol'].isna()) | (df_etf['Symbol'] == '') |
        (df_etf['Name'].isna()) | (df_etf['Name'] == '')
    )

    df_filtered = df_etf[~invalid_mask].copy()
    filter_time = time.time() - t_start_filter

    filtered_count = len(df_filtered)

    # 4. 정렬 및 상위 target_count 후보선정
    t_start_sort = time.time()
    df_sorted = df_filtered.sort_values(by='Amount', ascending=False)
    top_df = df_sorted.head(target_count)
    sort_time = time.time() - t_start_sort

    candidates = []
    for _, row in top_df.iterrows():
        candidates.append({
            "ticker": str(row['Symbol']).strip().zfill(6),
            "name": str(row['Name']).strip(),
            "market": "ETF",
            "asset_type": "ETF",
            "close": int(row['Price']),
            "volume": int(row['Volume']),
            "amount": float(row['Amount']),
            "marcap": float(row['MarCap']) if not pd.isna(row['MarCap']) else 0.0,
            "change_ratio": round(float(row['ChangeRate']), 2) if not pd.isna(row['ChangeRate']) else 0.0,
            "category": str(row.get('Category', '')),
            "selection_reason": "etf_liquidity"
        })

    total_time = fetch_time + filter_time + sort_time

    return {
        "status": "success",
        "universe_type": "ETF",
        "cache_hit": cache_hit,
        "total_input_count": total_input_count,
        "filtered_count": filtered_count,
        "target_count": target_count,
        "candidates_count": len(candidates),
        "candidates": candidates,
        "metrics": {
            "fetch_time_sec": round(fetch_time, 6),
            "filter_time_sec": round(filter_time, 6),
            "sort_time_sec": round(sort_time, 6),
            "total_time_sec": round(total_time, 6),
            "api_calls_count": 0
        }
    }
