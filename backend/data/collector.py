import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import re
import logging
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# HTTP 커넥션 풀링(Keep-Alive) 세션 객체 고속 공유 (pool_maxsize=25)
http_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=25, pool_maxsize=25)
http_session.mount("https://", adapter)
http_session.mount("http://", adapter)
http_session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})


COMMON_TICKERS = {
    "삼성전자": "005930",
    "SK하이닉스": "000660",
    "LG에너지솔루션": "373220",
    "삼성바이오로직스": "207940",
    "현대차": "005380",
    "기아": "000270",
    "셀트리온": "068270",
    "KB금융": "105560",
    "NAVER": "035420",
    "네이버": "035420",
    "카카오": "035720",
    "POSCO홀딩스": "005490",
    "포스코홀딩스": "005490"
}


def resolve_ticker(query: str, asset_type_hint: str = None) -> tuple[str, str]:
    """
    종목명, 종목코드, 복합형태("삼성전자(005930)") 입력 시
    종목코드(6자리)와 정확한 종목명을 반환합니다.
    """
    if not query or not str(query).strip():
        return None, None

    query = str(query).strip()

    # 0. "KOACT(0015B0)" 또는 "삼성전자(005930)" 형태에서 코드와 종목명 자동 추출 (최우선 0ms 반환)
    code_match = re.search(r'\(([0-9A-Za-z]{6})\)', query)
    if code_match:
        extracted_code = code_match.group(1).upper()
        extracted_name = re.sub(r'\([0-9A-Za-z]{6}\)', '', query).strip()
        
        from backend.engine.stock_identifier import search_stock_or_etf, BRAND_ALIAS_MAP
        m_by_code = search_stock_or_etf(extracted_code, asset_type=asset_type_hint or "ALL")
        if m_by_code and m_by_code[0].get("score", 0) >= 90:
            return m_by_code[0]["ticker"], m_by_code[0]["name"]
            
        m_by_name = search_stock_or_etf(extracted_name, asset_type=asset_type_hint or "ALL")
        if m_by_name and m_by_name[0].get("score", 0) >= 60:
            return m_by_name[0]["ticker"], m_by_name[0]["name"]
            
        if extracted_name:
            return extracted_code, extracted_name

    # 1. FinanceDataReader (KRX 2,870여개 전종목) 탐색 (우선순위 1)
    try:
        from backend.engine.krx_loader import search_krx_stocks
        krx_m = search_krx_stocks(query, limit=1)
        if krx_m and krx_m[0].get("score", 0) >= 80:
            return krx_m[0]["ticker"], krx_m[0]["name"]
    except Exception:
        pass

    # 1-2. STOCK_ETF_MASTER 마스터 데이터베이스 연동
    from backend.engine.stock_identifier import search_stock_or_etf, BRAND_ALIAS_MAP
    master_results = search_stock_or_etf(query, asset_type=asset_type_hint or "ALL")
    if master_results:
        top = master_results[0]
        if top.get("score", 0) >= 60:
            return top["ticker"], top["name"]

    # 2. COMMON_TICKERS 사전 매칭
    if query in COMMON_TICKERS:
        return COMMON_TICKERS[query], query
    
    # 3. 6자리 영문+숫자 혼합 종목코드 처리 (예: "005930", "069500", "0015B0")
    if re.match(r'^[0-9A-Za-z]{6}$', query):
        url = f"https://finance.naver.com/item/main.naver?code={query}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        try:
            resp = requests.get(url, headers=headers, timeout=1.5, verify=False)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                name_tag = soup.select_one('.wrap_company h2 a')
                if name_tag:
                    return query.upper(), name_tag.text.strip()
        except Exception as e:
            logger.warning(f"Failed to fetch stock name for ticker {query}: {e}")
        return query.upper(), query.upper()

    # 한글 브랜드 치환 검색용 질의 생성 (예: "코덱스 200" -> "KODEX 200")
    search_q = query
    for kor_b, eng_b in BRAND_ALIAS_MAP.items():
        if kor_b in query:
            search_q = query.replace(kor_b, eng_b)
            break

    # 4. 네이버 증권 종목 검색 API (타임아웃 1.5초)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    for q_term in [search_q, query]:
        search_url = f"https://ac.finance.naver.com/ac?q={requests.utils.quote(q_term)}&target=stock"
        try:
            resp = requests.get(search_url, headers=headers, timeout=1.5, verify=False)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('items', [[]])[0]
                for item in items:
                    if len(item) >= 2:
                        name = item[0]
                        code = item[1]
                        if q_term in name or query in name:
                            return code, name
                if items and len(items[0]) >= 2:
                    return items[0][1], items[0][0]
        except Exception as e:
            logger.warning(f"Search ticker API failed for '{q_term}': {e}")
    
    # 5. 네이버 주식 웹 검색 페이지 파싱 (타임아웃 1.5초)
    for q_term in [search_q, query]:
        try:
            search_web_url = f"https://finance.naver.com/search/searchList.naver?query={requests.utils.quote(q_term)}"
            resp = requests.get(search_web_url, headers=headers, timeout=1.5, verify=False)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                first_row = soup.select_one('table.tbl_search td.tit a')
                if first_row and 'code=' in first_row.get('href', ''):
                    found_code = first_row['href'].split('code=')[1].split('&')[0]
                    found_name = first_row.text.strip()
                    return found_code, found_name
        except Exception as e:
            logger.warning(f"Naver web search parse failed for '{q_term}': {e}")

    return None, None




def fetch_naver_realtime_price(ticker: str) -> dict:
    """
    네이버 증권 실시간 API(polling.finance.naver.com) 및 HTML 메인 페이지에서 장중 실시간 현재가, 전일대비, 거래량 수집
    """
    # 1순위: 네이버 실시간 Polling JSON API
    poll_url = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{ticker}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        resp = requests.get(poll_url, headers=headers, timeout=5, verify=False)
        if resp.status_code == 200:
            res_json = resp.json()
            datas = res_json.get("datas", [])
            if datas:
                item = datas[0]
                close_price_raw = item.get("closePriceRaw")
                diff_raw = item.get("compareToPreviousClosePriceRaw")
                vol_raw = item.get("accumulatedTradingVolumeRaw")

                if close_price_raw is not None and str(close_price_raw).replace('-', '').isdigit():
                    c_price = int(close_price_raw)
                    diff_val = int(diff_raw) if diff_raw is not None and str(diff_raw).replace('-', '').isdigit() else 0
                    vol_val = int(vol_raw) if vol_raw is not None and str(vol_raw).replace('-', '').isdigit() else 0
                    
                    if c_price > 0:
                        return {
                            "current_price": c_price,
                            "diff": diff_val,
                            "volume": vol_val
                        }
    except Exception as e:
        logger.warning(f"Realtime JSON API fetch error for {ticker}: {e}")

    # 2순위: HTML 스크래핑 Fallback
    url = f"https://finance.naver.com/item/main.naver?code={ticker}"
    try:
        resp = requests.get(url, headers=headers, timeout=5, verify=False)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. 실시간 현재가
        today_tag = soup.select_one("p.no_today span.blind") or soup.select_one("em.no_today span.blind")
        if not today_tag:
            return None
        current_price = int(today_tag.text.replace(',', ''))

        # 2. 전일 대비 및 상승/하락
        exday_tag = soup.select_one("p.no_exday") or soup.select_one("em.no_exday")
        diff = 0
        if exday_tag:
            diff_blind = exday_tag.select_one("span.blind")
            if diff_blind and diff_blind.text.replace(',', '').isdigit():
                diff_val = int(diff_blind.text.replace(',', ''))
                if "ico_down" in str(exday_tag) or "하락" in str(exday_tag) or "fall" in str(exday_tag):
                    diff = -diff_val
                else:
                    diff = diff_val

        # 3. 거래량
        volume = 0
        table_info = soup.select("table.no_info tr td")
        for td in table_info:
            if "거래량" in td.text:
                blind = td.select_one("span.blind")
                if blind and blind.text.replace(',', '').isdigit():
                    volume = int(blind.text.replace(',', ''))
                    break

        return {
            "current_price": current_price,
            "diff": diff,
            "volume": volume
        }
    except Exception as e:
        logger.warning(f"Realtime price HTML fallback fetch error for {ticker}: {e}")
        return None


def fetch_naver_frgn_data(ticker: str, pages: int = 1) -> pd.DataFrame:
    """
    네이버 금융 일별 수급 크롤링 (Connection Pooling 및 1.5초 타임아웃 적용)
    """
    records = []

    for page in range(1, pages + 1):
        url = f"https://finance.naver.com/item/frgn.naver?code={ticker}&page={page}"
        try:
            resp = http_session.get(url, timeout=1.5, verify=False)
            if resp.status_code != 200:
                continue

            
            soup = BeautifulSoup(resp.text, 'html.parser')
            tables = soup.select('table.type2')
            if len(tables) < 2:
                continue
            
            target_table = tables[1]
            rows = target_table.select('tr')
            
            for row in rows:
                cols = row.select('td')
                if len(cols) < 9:
                    continue
                
                date_str = cols[0].text.strip()
                if not re.match(r'^\d{4}\.\d{2}\.\d{2}$', date_str):
                    continue
                
                date_formatted = date_str.replace('.', '-')
                close_price = int(cols[1].text.strip().replace(',', ''))
                
                diff_str = cols[2].text.strip().replace(',', '')
                img_tag = cols[2].find('img')
                sign = 1
                if img_tag and ('fall' in img_tag.get('alt', '') or 'down' in img_tag.get('alt', '')):
                    sign = -1
                diff = int(diff_str) * sign if diff_str.isdigit() else 0

                volume = int(cols[4].text.strip().replace(',', '')) if cols[4].text.strip().replace(',', '').isdigit() else 0
                
                # 수급 수량 파싱: +, -, 콤마 등 모든 부호 및 기호를 완벽히 처리하여 매수(+) 데이터 유실 방지
                inst_net_qty_raw = cols[5].text.strip().replace(',', '').replace('+', '')
                try:
                    inst_net_qty = int(inst_net_qty_raw)
                except ValueError:
                    inst_net_qty = 0
                
                frgn_net_qty_raw = cols[6].text.strip().replace(',', '').replace('+', '')
                try:
                    frgn_net_qty = int(frgn_net_qty_raw)
                except ValueError:
                    frgn_net_qty = 0
                
                frgn_ratio_str = cols[8].text.strip().replace('%', '').replace(',', '').replace('+', '')
                try:
                    frgn_ratio = float(frgn_ratio_str)
                except ValueError:
                    frgn_ratio = 0.0

                frgn_net_buy = frgn_net_qty * close_price
                inst_net_buy = inst_net_qty * close_price
                trading_value = volume * close_price

                records.append({
                    'date': date_formatted,
                    'close_price': close_price,
                    'diff': diff,
                    'volume': volume,
                    'trading_value': trading_value,
                    'foreign_net_buy': frgn_net_buy,
                    'institution_net_buy': inst_net_buy,
                    'foreign_net_qty': frgn_net_qty,
                    'institution_net_qty': inst_net_qty,
                    'foreign_holding_ratio': frgn_ratio
                })
        except Exception as e:
            logger.error(f"Error scraping page {page} for ticker {ticker}: {e}")

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df.sort_values(by='date', ascending=True, inplace=True)
    df.reset_index(drop=True, inplace=True)
    df['change_rate'] = (df['diff'] / (df['close_price'] - df['diff']) * 100).round(2)
    return df


def fetch_pykrx_flow_data(ticker: str, days: int = 30) -> pd.DataFrame:
    try:
        from pykrx import stock
        to_date = datetime.now().strftime("%Y%m%d")
        from_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

        df_price = stock.get_market_ohlcv_by_date(from_date, to_date, ticker)
        if df_price.empty:
            return pd.DataFrame()

        df_net = stock.get_market_trading_value_by_date(from_date, to_date, ticker)
        
        df = pd.DataFrame()
        df['date'] = df_price.index.strftime("%Y-%m-%d")
        df['close_price'] = df_price['종가'].values
        df['diff'] = df_price['대비'].values if '대비' in df_price.columns else 0
        df['volume'] = df_price['거래량'].values
        df['trading_value'] = df_price['거래대금'].values
        
        if not df_net.empty and '외국인합계' in df_net.columns:
            df['foreign_net_buy'] = df_net['외국인합계'].values
            df['institution_net_buy'] = df_net['기관합계'].values
        else:
            df['foreign_net_buy'] = 0
            df['institution_net_buy'] = 0
            
        df['foreign_holding_ratio'] = 0.0
        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        logger.warning(f"PyKRX fetch fallback failed for {ticker}: {e}")
        return pd.DataFrame()


def fetch_fdr_flow_data(ticker: str, days: int = 30) -> pd.DataFrame:
    """
    FinanceDataReader(fdr.DataReader) 기반 3차 비상 시세 폴백 수집 함수
    """
    try:
        import FinanceDataReader as fdr
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
        df_fdr = fdr.DataReader(ticker, start=start_date)
        if df_fdr.empty:
            return pd.DataFrame()

        df = pd.DataFrame()
        df['date'] = df_fdr.index.strftime("%Y-%m-%d")
        df['close_price'] = df_fdr['Close'].values.astype(int)
        
        if 'Change' in df_fdr.columns:
            prev_close = df_fdr['Close'].shift(1).fillna(df_fdr['Close'])
            df['diff'] = (df_fdr['Close'] - prev_close).values.astype(int)
        else:
            df['diff'] = 0

        df['volume'] = df_fdr['Volume'].values.astype(int) if 'Volume' in df_fdr.columns else 0
        df['trading_value'] = df['volume'] * df['close_price']
        df['foreign_net_buy'] = 0
        df['institution_net_buy'] = 0
        df['foreign_holding_ratio'] = 0.0
        df['change_rate'] = (df['diff'] / (df['close_price'] - df['diff']) * 100).round(2)
        
        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        logger.warning(f"FinanceDataReader fetch fallback failed for {ticker}: {e}")
        return pd.DataFrame()


import time

_FLOW_DATA_CACHE = {}
_CACHE_TTL_SECONDS = 60

def get_stock_flow_data(ticker_or_name: str, min_days: int = 20) -> dict:
    """
    종목 데이터 수집 + 장중 실시간 현재가 융합 (60초 인메모리 캐싱 적용)
    """
    now_ts = time.time()
    cache_key = f"{ticker_or_name}_{min_days}"
    
    if cache_key in _FLOW_DATA_CACHE:
        cached_time, cached_data = _FLOW_DATA_CACHE[cache_key]
        if now_ts - cached_time < _CACHE_TTL_SECONDS:
            return cached_data

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    ticker, name = resolve_ticker(ticker_or_name)
    if not ticker:
        err_res = {
            "data_available": False,
            "status_code": "DATA_NOT_FOUND",
            "status_message": "데이터 없음",
            "error": f"'{ticker_or_name}' 종목을 찾을 수 없습니다.",
            "updated_at": now_str,
            "source": "FinanceDataReader / KRX",
            "is_delayed": False
        }
        return err_res


    # 1. 일별 수급 데이터 수집 (경량화 1~2페이지 수집)
    source_name = "Naver Finance (실시간 융합)"
    pages_to_fetch = 1 if min_days <= 20 else 2
    df = fetch_naver_frgn_data(ticker, pages=pages_to_fetch)

    if df.empty or len(df) < 5:
        source_name = "KRX Open Data (PyKRX)"
        df = fetch_pykrx_flow_data(ticker, days=min_days)

    if df.empty or len(df) < 5:
        source_name = "FinanceDataReader (KRX Data)"
        df = fetch_fdr_flow_data(ticker, days=min_days)

    if df.empty or len(df) < 5:
        return {
            "data_available": False,
            "status_code": "FETCH_FAILED",
            "status_message": "데이터 수집 실패",
            "error": f"'{name}'({ticker}) 종목의 실시간 수급 데이터를 가져올 수 없습니다.",
            "updated_at": now_str,
            "source": source_name,
            "is_delayed": False
        }

    # 2. 장중 실시간 현재가 수집 및 최신 행 융합(Override)
    realtime_info = fetch_naver_realtime_price(ticker)
    if realtime_info and realtime_info["current_price"] > 0:
        latest_idx = len(df) - 1
        last_date = df.at[latest_idx, 'date']
        
        # 마지막 행이 오늘 날짜인 경우 실시간 시세로 덮어쓰기
        if last_date == today_str:
            df.at[latest_idx, 'close_price'] = realtime_info["current_price"]
            df.at[latest_idx, 'diff'] = realtime_info["diff"]
            if realtime_info["volume"] > 0:
                df.at[latest_idx, 'volume'] = realtime_info["volume"]
                df.at[latest_idx, 'trading_value'] = realtime_info["volume"] * realtime_info["current_price"]
        else:
            # 마지막 행이 과거 날짜(어제 등)인 경우 오늘 날짜 실시간 행 추가
            last_row = df.iloc[-1].to_dict()
            new_row = {
                'date': today_str,
                'close_price': realtime_info["current_price"],
                'diff': realtime_info["diff"],
                'volume': realtime_info["volume"] if realtime_info["volume"] > 0 else last_row.get('volume', 0),
                'trading_value': (realtime_info["volume"] * realtime_info["current_price"]) if realtime_info["volume"] > 0 else last_row.get('trading_value', 0),
                'foreign_net_buy': last_row.get('foreign_net_buy', 0),
                'institution_net_buy': last_row.get('institution_net_buy', 0),
                'foreign_net_qty': last_row.get('foreign_net_qty', 0),
                'institution_net_qty': last_row.get('institution_net_qty', 0),
                'foreign_holding_ratio': last_row.get('foreign_holding_ratio', 0.0),
                'change_rate': round((realtime_info["diff"] / (realtime_info["current_price"] - realtime_info["diff"]) * 100), 2) if (realtime_info["current_price"] - realtime_info["diff"]) > 0 else 0.0
            }
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    res = {
        "data_available": True,
        "status_code": "OK",
        "status_message": "정상",
        "ticker": ticker,
        "name": name,
        "count": len(df),
        "updated_at": now_str,
        "source": source_name,
        "is_delayed": False, # 실시간 체결가 융합 반영
        "df": df,
        "investor_breakdown": fetch_investor_breakdown_data(ticker, days=min_days)
    }
    _FLOW_DATA_CACHE[cache_key] = (now_ts, res)
    return res


def fetch_investor_breakdown_data(ticker: str, days: int = 20) -> dict:
    """
    외국인, 연기금 등, 금융투자, 투신, 사모, 개인 6개 주체별 세부 수급 데이터 수집 (최근 5/10/20일 누적)
    기존 FCS/FFCS 및 수급 판단 엔진에는 영향을 주지 않으며 독립 데이터 객체로 반환함.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://m.stock.naver.com/'
    }
    
    daily_records = []
    
    # 1. 네이버 모바일 API 수급 트렌드 (외국인, 기관, 개인 일별 데이터)
    try:
        url = f"https://m.stock.naver.com/api/stock/{ticker}/trend?pageSize={max(days, 25)}&page=1"
        resp = http_session.get(url, headers=headers, timeout=2.0, verify=False)
        if resp.status_code == 200:
            raw_items = resp.json()
            if isinstance(raw_items, list):
                for item in raw_items:
                    bizdate = str(item.get("bizdate", ""))
                    if len(bizdate) == 8:
                        date_fmt = f"{bizdate[:4]}-{bizdate[4:6]}-{bizdate[6:8]}"
                    else:
                        date_fmt = bizdate

                    close_p = float(str(item.get("closePrice", "0")).replace(',', ''))
                    
                    # 외국인, 기관, 개인 순매수 수량 및 거래대금(억원) 파싱
                    frgn_qty = int(str(item.get("foreignerPureBuyQuant", "0")).replace(',', '').replace('+', ''))
                    organ_qty = int(str(item.get("organPureBuyQuant", "0")).replace(',', '').replace('+', ''))
                    indiv_qty = int(str(item.get("individualPureBuyQuant", "0")).replace(',', '').replace('+', ''))

                    frgn_amt = round((frgn_qty * close_p) / 100000000.0, 2)
                    organ_amt = round((organ_qty * close_p) / 100000000.0, 2)
                    indiv_amt = round((indiv_qty * close_p) / 100000000.0, 2)

                    daily_records.append({
                        "date": date_fmt,
                        "close_price": close_p,
                        "foreign_qty": frgn_qty,
                        "foreign_amount": frgn_amt,
                        "institution_qty": organ_qty,
                        "institution_amount": organ_amt,
                        "individual_qty": indiv_qty,
                        "individual_amount": indiv_amt,
                        # 기관 세부 주체 (API 미제공 시 null 표기 - 임의 생성 금지)
                        "pension_amount": None,
                        "financial_investment_amount": None,
                        "investment_trust_amount": None,
                        "private_fund_amount": None
                    })
    except Exception as e:
        logger.warning(f"Failed to fetch mobile investor trend for {ticker}: {e}")

    # 2. KRX / 공공데이터 API Key 환경 변수 연동 (설정된 경우 세부 주체 보완)
    krx_api_key = os.getenv("KRX_API_KEY") or os.getenv("PUBLIC_DATA_API_KEY")
    if krx_api_key:
        try:
            # KRX / 공공데이터포털 주식투자자별매매동향 API 연동
            krx_url = f"http://apis.data.go.kr/1160100/service/GetStockMarketInfoService/getInvestorTradingByStock?serviceKey={krx_api_key}&resultType=json&likeShtnIscd={ticker}&numOfRows=100"
            k_resp = http_session.get(krx_url, timeout=2.5)
            if k_resp.status_code == 200:
                k_data = k_resp.json()
                items = k_data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
                date_map = {r["date"]: r for r in daily_records}
                for it in items:
                    dt = it.get("basDt", "")
                    if len(dt) == 8:
                        dt_fmt = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
                    else:
                        dt_fmt = dt
                    
                    invst_nm = str(it.get("invstNm", ""))
                    net_amt = float(it.get("ntbyTrdval", 0)) / 100000000.0 # 억원
                    
                    if dt_fmt in date_map:
                        rec = date_map[dt_fmt]
                        if "연기금" in invst_nm:
                            rec["pension_amount"] = round(net_amt, 2)
                        elif "금융투자" in invst_nm:
                            rec["financial_investment_amount"] = round(net_amt, 2)
                        elif "투신" in invst_nm:
                            rec["investment_trust_amount"] = round(net_amt, 2)
                        elif "사모" in invst_nm:
                            rec["private_fund_amount"] = round(net_amt, 2)
        except Exception as e:
            logger.warning(f"KRX Open API fetch error for {ticker}: {e}")

    # 일자 오름차순 정렬 (과거 -> 최근)
    daily_records.sort(key=lambda x: x["date"])

    if not daily_records:
        return {
            "available": False,
            "message": "투자자별 세부 수급 데이터를 수집할 수 없습니다.",
            "daily": [],
            "cumulative": {}
        }

    # 최근 5일, 10일, 20일 누적 합계 연산
    def calc_cum(days_n: int):
        sub_records = daily_records[-days_n:] if len(daily_records) >= days_n else daily_records
        
        def safe_sum(key):
            vals = [r[key] for r in sub_records if r.get(key) is not None]
            return round(sum(vals), 2) if vals else None

        return {
            "foreign": safe_sum("foreign_amount"),
            "institution": safe_sum("institution_amount"),
            "pension": safe_sum("pension_amount"),
            "financial_investment": safe_sum("financial_investment_amount"),
            "investment_trust": safe_sum("investment_trust_amount"),
            "private_fund": safe_sum("private_fund_amount"),
            "individual": safe_sum("individual_amount")
        }

    return {
        "available": True,
        "updated_at": now_str,
        "daily": daily_records[-20:],
        "cumulative": {
            "5d": calc_cum(5),
            "10d": calc_cum(10),
            "20d": calc_cum(20)
        }
    }



def fetch_stock_chart_analysis(ticker_or_name: str, timeframe: str = 'day') -> dict:
    """
    최근 6개월간의 가격 이력, 추세선(5/20/60일 이동평균), 거래량, MFI(자금흐름지수) 분석
    timeframe: 'day' (일간), 'month' (월간), 'year' (연간)
    """
    ticker, name = resolve_ticker(ticker_or_name)
    if not ticker:
        return {"status": "error", "message": f"종목 '{ticker_or_name}'을 찾을 수 없습니다."}

    # fchart xml 차트 데이터 (250일분 수집)
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count=250&requestType=0"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    records = []
    try:
        resp = requests.get(url, headers=headers, timeout=5, verify=False)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'xml') or BeautifulSoup(resp.text, 'html.parser')
            items = soup.select('item')
            for item in items:
                data_attr = item.get('data', '')
                if not data_attr:
                    continue
                parts = data_attr.split('|')
                if len(parts) >= 6:
                    date_raw = parts[0]
                    date_str = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
                    open_p = float(parts[1])
                    high_p = float(parts[2])
                    low_p = float(parts[3])
                    close_p = float(parts[4])
                    vol = int(parts[5]) if parts[5].isdigit() else 0
                    
                    records.append({
                        'date': date_str,
                        'open_price': open_p,
                        'high_price': high_p,
                        'low_price': low_p,
                        'close_price': close_p,
                        'volume': vol
                    })
    except Exception as e:
        logger.warning(f"Stock chart fetch error for {ticker}: {e}")

    if not records:
        return {"status": "error", "message": "차트 데이터를 불러올 수 없습니다."}

    df = pd.DataFrame(records)
    df.sort_values(by='date', ascending=True, inplace=True)
    df.reset_index(drop=True, inplace=True)

    # 1. MFI (Money Flow Index 14일) 계산
    tp = (df['high_price'] + df['low_price'] + df['close_price']) / 3.0
    rmf = tp * df['volume']
    tp_diff = tp.diff()
    
    pos_flow = pd.Series(np.where(tp_diff > 0, rmf, 0.0))
    neg_flow = pd.Series(np.where(tp_diff < 0, rmf, 0.0))
    
    pos_mf = pos_flow.rolling(window=14).sum()
    neg_mf = neg_flow.rolling(window=14).sum()
    
    mfr = pos_mf / neg_mf.replace(0, np.nan)
    mfi_series = 100 - (100 / (1 + mfr))
    df['mfi'] = mfi_series.fillna(50.0).round(2)

    # 2. RMI (Relative Momentum Index 14일, 4일 간격) 계산
    diff4 = df['close_price'].diff(4).fillna(0)
    up4 = np.where(diff4 > 0, diff4, 0.0)
    down4 = np.where(diff4 < 0, -diff4, 0.0)
    gain_rmi = pd.Series(up4).ewm(com=13, min_periods=1).mean()
    loss_rmi = pd.Series(down4).ewm(com=13, min_periods=1).mean()
    rs_rmi = np.where(loss_rmi == 0, 99999.0, gain_rmi / np.where(loss_rmi == 0, 1.0, loss_rmi))
    rmi_series = 100.0 - (100.0 / (1.0 + rs_rmi))
    df['rmi'] = pd.Series(rmi_series).fillna(50.0).round(2)

    # 3. 이동평균선 (추세선 MA5, MA20, MA60)
    df['ma5'] = df['close_price'].rolling(window=5).mean().fillna(df['close_price']).round(2)
    df['ma20'] = df['close_price'].rolling(window=20).mean().fillna(df['close_price']).round(2)
    df['ma60'] = df['close_price'].rolling(window=60).mean().fillna(df['close_price']).round(2)

    # 4. timeframe ('day', 'month', 'year') 별 집계
    if timeframe == 'month':
        df['period_key'] = df['date'].str.slice(0, 7) # YYYY-MM
        res_df = df.groupby('period_key').agg({
            'date': 'last',
            'close_price': 'last',
            'ma5': 'mean',
            'ma20': 'mean',
            'ma60': 'mean',
            'volume': 'sum',
            'mfi': 'mean',
            'rmi': 'mean'
        }).reset_index(drop=True)
    elif timeframe == 'year':
        df['period_key'] = df['date'].str.slice(0, 4) # YYYY
        res_df = df.groupby('period_key').agg({
            'date': 'last',
            'close_price': 'last',
            'ma5': 'mean',
            'ma20': 'mean',
            'ma60': 'mean',
            'volume': 'sum',
            'mfi': 'mean',
            'rmi': 'mean'
        }).reset_index(drop=True)
    else:
        # 일간 (최근 130 영업일 약 6개월)
        res_df = df.tail(130).reset_index(drop=True)

    dates = res_df['date'].tolist()
    closes = res_df['close_price'].round(2).tolist()
    ma5 = res_df['ma5'].round(2).tolist()
    ma20 = res_df['ma20'].round(2).tolist()
    ma60 = res_df['ma60'].round(2).tolist()
    volumes = res_df['volume'].astype(int).tolist()
    mfi_vals = res_df['mfi'].round(2).tolist()
    rmi_vals = res_df['rmi'].round(2).tolist()

    return {
        "status": "success",
        "ticker": ticker,
        "name": name,
        "timeframe": timeframe,
        "count": len(dates),
        "dates": dates,
        "closes": closes,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "volumes": volumes,
        "mfi": mfi_vals,
        "rmi": rmi_vals
    }
