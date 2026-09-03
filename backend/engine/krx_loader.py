import logging
import time
import threading
import FinanceDataReader as fdr
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# 메모리 캐시 및 스레드 락 전역 변수
_KRX_ALL_STOCKS_CACHE: List[Dict[str, Any]] = []
_KRX_TICKER_MAP: Dict[str, Dict[str, Any]] = {}
_KRX_NAME_MAP: Dict[str, Dict[str, Any]] = {}
_LAST_LOADED_TS: float = 0
_CACHE_TTL: float = 86400  # 24시간 캐시 유지
_LOAD_LOCK = threading.Lock()  # 스레드 경합 방지용 락

def load_krx_all_stocks(force_reload: bool = False) -> List[Dict[str, Any]]:
    """
    FinanceDataReader를 활용하여 한국거래소(KRX) 전체 상장 종목(KOSPI, KOSDAQ, ETF 등 약 2,700개)을
    메모리에 즉시 로딩 및 indexing합니다. (스레드 락 적용으로 동시 10~20회 중복 로딩 완벽 차단)
    """
    global _KRX_ALL_STOCKS_CACHE, _KRX_TICKER_MAP, _KRX_NAME_MAP, _LAST_LOADED_TS
    now = time.time()

    # 1. 캐시가 이미 존재하고 유효하면 락 없이 0ms 즉시 리턴
    if not force_reload and _KRX_ALL_STOCKS_CACHE and (now - _LAST_LOADED_TS < _CACHE_TTL):
        return _KRX_ALL_STOCKS_CACHE

    # 2. 캐시가 없거나 갱신 필요 시 스레드 락을 획득하여 단 1회만 실행
    with _LOAD_LOCK:
        # 락 획득 후 다른 스레드가 이미 로딩을 끝냈는지 재확인 (Double-Checked Locking)
        if not force_reload and _KRX_ALL_STOCKS_CACHE and (now - _LAST_LOADED_TS < _CACHE_TTL):
            return _KRX_ALL_STOCKS_CACHE

        try:
            logger.info("[KRX Loader] 최초 1회 전체 KRX 상장 종목(2,800여개) 메모리 로딩 중...")
            df_krx = fdr.StockListing('KRX')
            
            stocks_list = []
            ticker_map = {}
            name_map = {}

            for idx, row in df_krx.iterrows():
                code = str(row.get('Code', '')).strip().zfill(6)
                name = str(row.get('Name', '')).strip()
                market = str(row.get('Market', 'KOSPI')).strip().upper()
                
                if not code or not name:
                    continue

                is_etf = any(b in name.upper() for b in ["ETF", "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "KBSTAR", "ARIRANG", "HANARO"])
                asset_type = "ETF" if is_etf or market == "ETF" else "STOCK"

                item = {
                    "name": name,
                    "ticker": code,
                    "market": market,
                    "asset_type": asset_type,
                    "manager": "자산운용" if is_etf else "",
                    "score": 90
                }

                stocks_list.append(item)
                ticker_map[code] = item
                name_map[name.upper()] = item

            _KRX_ALL_STOCKS_CACHE = stocks_list
            _KRX_TICKER_MAP = ticker_map
            _KRX_NAME_MAP = name_map
            _LAST_LOADED_TS = time.time()
            
            logger.info(f"[KRX Loader] 성공적으로 KRX 전체 {len(stocks_list)}개 종목 메모리 로딩 완료!")
            return stocks_list

        except Exception as e:
            logger.error(f"[KRX Loader] KRX 종목 로딩 실패: {e}")
            return _KRX_ALL_STOCKS_CACHE


def search_krx_stocks(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    FinanceDataReader로 로딩된 전 종목에서 질의어(종목명/종목코드) 검색
    """
    if not query or not str(query).strip():
        return []

    q = str(query).strip().upper()
    all_stocks = load_krx_all_stocks()

    # 1. 티커 완전 일치
    if q in _KRX_TICKER_MAP:
        return [{**_KRX_TICKER_MAP[q], "match_type": "EXACT_TICKER", "score": 110}]

    # 2. 종목명 완전 일치
    if q in _KRX_NAME_MAP:
        return [{**_KRX_NAME_MAP[q], "match_type": "EXACT_NAME", "score": 100}]

    # 3. 전방 일치 & 부분 일치
    matches = []
    for item in all_stocks:
        name_u = item["name"].upper()
        ticker = item["ticker"]
        
        if name_u.startswith(q):
            matches.append({**item, "match_type": "STARTS_WITH_NAME", "score": 85})
        elif q in name_u:
            matches.append({**item, "match_type": "PARTIAL_NAME", "score": 75})
        elif q in ticker:
            matches.append({**item, "match_type": "PARTIAL_TICKER", "score": 70})

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches[:limit]
