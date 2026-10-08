import logging
import os
import json
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
        logger.warning(f"[KRX Loader] SSL CA bundle env setup warning: {e}")

def load_krx_all_stocks(force_reload: bool = False) -> List[Dict[str, Any]]:
    """
    FinanceDataReader를 활용하여 한국거래소(KRX) 전체 상장 주식(KOSPI, KOSDAQ 등 약 2,870개) 및
    국내 상장 ETF 전체(약 1,170개)를 고속 병합하여 메모리에 로딩 및 indexing합니다.
    (스레드 락 적용으로 동시 10~20회 중복 로딩 완벽 차단)
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
            logger.info("[KRX Loader] 최초 1회 전체 KRX 상장 주식 + ETF (약 4,000여개) 메모리 로딩 중...")
            _ensure_ssl_env()

            stocks_list = []
            ticker_map = {}
            name_map = {}

            # 2-A. ETF/KR Source 로딩 (ETF 우선 순위)
            try:
                df_etf = fdr.StockListing('ETF/KR')
                if df_etf is not None and not df_etf.empty:
                    code_col = 'Symbol' if 'Symbol' in df_etf.columns else ('Code' if 'Code' in df_etf.columns else df_etf.columns[0])
                    for idx, row in df_etf.iterrows():
                        code = str(row.get(code_col, '')).strip().zfill(6)
                        name = str(row.get('Name', '')).strip()
                        if not code or not name:
                            continue

                        item = {
                            "name": name,
                            "ticker": code,
                            "market": "ETF",
                            "asset_type": "ETF",
                            "manager": "자산운용",
                            "score": 90
                        }
                        stocks_list.append(item)
                        ticker_map[code] = item
                        name_map[name.upper()] = item
                    logger.info(f"[KRX Loader] ETF/KR Listing에서 {len(ticker_map)}개 ETF 로딩 성공")
            except Exception as etf_err:
                logger.warning(f"[KRX Loader] ETF/KR Listing 로딩 실패: {etf_err}")

            # 2-B. KRX Source 로딩 (개별 주식)
            try:
                df_krx = fdr.StockListing('KRX')
                if df_krx is not None and not df_krx.empty:
                    krx_count = 0
                    for idx, row in df_krx.iterrows():
                        code = str(row.get('Code', '')).strip().zfill(6)
                        name = str(row.get('Name', '')).strip()
                        market = str(row.get('Market', 'KOSPI')).strip().upper()

                        if not code or not name:
                            continue

                        # 이미 ETF/KR Source에서 로딩된 ticker는 ETF 정보 우선 유지
                        if code in ticker_map:
                            continue

                        item = {
                            "name": name,
                            "ticker": code,
                            "market": market,
                            "asset_type": "STOCK",
                            "manager": "",
                            "score": 90
                        }
                        stocks_list.append(item)
                        ticker_map[code] = item
                        name_map[name.upper()] = item
                        krx_count += 1
                    logger.info(f"[KRX Loader] KRX Listing에서 {krx_count}개 개별 주식 추가 로딩 성공")
            except Exception as krx_err:
                logger.warning(f"[KRX Loader] KRX Listing 로딩 실패: {krx_err}")

            if stocks_list:
                _KRX_ALL_STOCKS_CACHE = stocks_list
                _KRX_TICKER_MAP = ticker_map
                _KRX_NAME_MAP = name_map
                _LAST_LOADED_TS = time.time()
                
                logger.info(f"[KRX Loader] 성공적으로 전체 {len(stocks_list)}개 종목(STOCK+ETF) 메모리 로딩 완료!")
                return stocks_list

            raise RuntimeError("FDR KRX 및 ETF/KR 응답이 모두 비어있습니다.")

        except Exception as e:
            logger.warning(f"[KRX Loader] KRX/ETF 외부 로딩 실패: {e}")
            _LAST_LOADED_TS = time.time()  # 무한 404 재시도 방지

            # 1차 Fallback: 로컬 번들 스냅샷 (krx_all_stocks.json) 로드
            try:
                json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "krx_all_stocks.json")
                if os.path.exists(json_path):
                    with open(json_path, "r", encoding="utf-8") as f:
                        bundled_stocks = json.load(f)
                    if bundled_stocks and isinstance(bundled_stocks, list):
                        ticker_map = {}
                        name_map = {}
                        for item in bundled_stocks:
                            code = str(item.get("ticker", "")).strip().zfill(6)
                            name = str(item.get("name", "")).strip()
                            if code and name:
                                ticker_map[code] = item
                                name_map[name.upper()] = item
                        _KRX_ALL_STOCKS_CACHE = bundled_stocks
                        _KRX_TICKER_MAP = ticker_map
                        _KRX_NAME_MAP = name_map
                        logger.info(f"[KRX Loader] 번들 스냅샷(krx_all_stocks.json)에서 성공적으로 {len(bundled_stocks)}개 종목 복원 완료!")
                        return bundled_stocks
            except Exception as bundled_err:
                logger.warning(f"[KRX Loader] 번들 스냅샷 로딩 실패: {bundled_err}")

            # 2차 Fallback: 포트폴리오 DB 종목 활용
            try:
                from backend.db import database as db
                db_stocks = db.get_all_stocks(asset_type="ALL")
                fallback_list = []
                for s in db_stocks:
                    item = {
                        "name": s["name"],
                        "ticker": s["ticker"],
                        "market": s.get("market", "KOSPI"),
                        "asset_type": s.get("asset_type", "STOCK"),
                        "manager": "",
                        "score": 90
                    }
                    fallback_list.append(item)
                    _KRX_TICKER_MAP[s["ticker"]] = item
                    _KRX_NAME_MAP[s["name"].upper()] = item
                _KRX_ALL_STOCKS_CACHE = fallback_list
                return fallback_list
            except Exception:
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

