import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import re
import logging
import urllib3
import urllib.parse

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def extract_float(text: str) -> float:
    if not text:
        return 0.0
    matches = re.findall(r"[-+]?\d+(?:,\d+)*(?:\.\d+)?", text)
    if matches:
        clean_str = matches[0].replace(',', '')
        try:
            return float(clean_str)
        except ValueError:
            return 0.0
    return 0.0

_OVERVIEW_CACHE = None
_OVERVIEW_CACHE_TS = 0

def fetch_market_indices() -> dict:
    """
    국내 지수(KOSPI, KOSDAQ 실시간 체결가 & 등락률), 환율(USD/KRW), 주요 해외 지수 수집 (30초 캐싱 적용)
    """
    global _OVERVIEW_CACHE, _OVERVIEW_CACHE_TS
    now_ts = time.time()

    if _OVERVIEW_CACHE and (now_ts - _OVERVIEW_CACHE_TS < 30):
        return _OVERVIEW_CACHE

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    
    indices = {
        "kospi": {"name": "코스피", "value": None, "change": None, "rate": None, "status": "데이터 없음"},
        "kosdaq": {"name": "코스닥", "value": None, "change": None, "rate": None, "status": "데이터 없음"},
        "exchange_rate": {"name": "원/달러 환율", "value": None, "status": "데이터 없음"},
        "sp500": {"name": "S&P 500", "value": None, "status": "데이터 없음"},
        "nasdaq": {"name": "나스닥", "value": None, "status": "데이터 없음"},
        "dow": {"name": "다우존스", "value": None, "status": "데이터 없음"}
    }

    # 1. 네이버 실시간 지수 API (KOSPI & KOSDAQ)
    for code, key in [("KOSPI", "kospi"), ("KOSDAQ", "kosdaq")]:
        poll_url = f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}"
        try:
            resp = requests.get(poll_url, headers=HEADERS, timeout=5, verify=False)
            if resp.status_code == 200:
                data = resp.json()
                datas = data.get("datas", [])
                if datas:
                    item = datas[0]
                    val_str = item.get("closePriceRaw")
                    change_str = item.get("compareToPreviousClosePriceRaw")
                    rate_str = item.get("fluctuationsRatioRaw")

                    if val_str:
                        val = float(val_str)
                        change_val = float(change_str) if change_str else 0.0
                        rate_val = float(rate_str) if rate_str else 0.0
                        indices[key] = {
                            "name": "코스피" if code == "KOSPI" else "코스닥",
                            "value": val,
                            "change": change_val,
                            "rate": rate_val,
                            "status": "정상"
                        }
        except Exception as e:
            logger.warning(f"Realtime index API error for {code}: {e}")

    # Fallback 또는 백업: HTML 스크래핑
    if indices["kospi"]["status"] != "정상" or indices["kosdaq"]["status"] != "정상":
        url_krx = "https://finance.naver.com/sise/"
        try:
            resp = requests.get(url_krx, headers=HEADERS, timeout=5, verify=False)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                if indices["kospi"]["status"] != "정상":
                    kospi_val = soup.select_one("#KOSPI_now")
                    kospi_change = soup.select_one("#KOSPI_change")
                    if kospi_val:
                        v = extract_float(kospi_val.text)
                        c_text = kospi_change.text.strip() if kospi_change else "0.0"
                        c_val = extract_float(c_text)
                        if '하락' in c_text or 'down' in str(kospi_change):
                            c_val = -abs(c_val)
                        indices["kospi"] = {"name": "코스피", "value": v, "change": c_val, "rate": round((c_val / (v - c_val) * 100), 2) if (v - c_val) > 0 else 0.0, "status": "정상"}

                if indices["kosdaq"]["status"] != "정상":
                    kosdaq_val = soup.select_one("#KOSDAQ_now")
                    kosdaq_change = soup.select_one("#KOSDAQ_change")
                    if kosdaq_val:
                        v = extract_float(kosdaq_val.text)
                        c_text = kosdaq_change.text.strip() if kosdaq_change else "0.0"
                        c_val = extract_float(c_text)
                        if '하락' in c_text or 'down' in str(kosdaq_change):
                            c_val = -abs(c_val)
                        indices["kosdaq"] = {"name": "코스닥", "value": v, "change": c_val, "rate": round((c_val / (v - c_val) * 100), 2) if (v - c_val) > 0 else 0.0, "status": "정상"}
        except Exception as e:
            logger.warning(f"KRX indices fetch warning: {e}")
        indices["kospi"]["status"] = "데이터 수집 실패"
        indices["kosdaq"]["status"] = "데이터 수집 실패"

    # 2. 환율
    url_market = "https://finance.naver.com/marketindex/"
    try:
        resp = requests.get(url_market, headers=HEADERS, timeout=5, verify=False)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            usd_tag = soup.select_one("a.head.usd div.head_info span.value")
            if usd_tag:
                v = extract_float(usd_tag.text)
                indices["exchange_rate"] = {"name": "원/달러 환율", "value": v, "unit": "원", "status": "정상"}
    except Exception as e:
        logger.warning(f"Market index fetch warning: {e}")
        indices["exchange_rate"]["status"] = "데이터 수집 실패"

    # 3. 해외지수 (S&P500, NASDAQ, DOW) - Yahoo Finance API 활용
    world_symbols = [
        ("^IXIC", "nasdaq", "나스닥"),
        ("^GSPC", "sp500", "S&P 500"),
        ("^DJI", "dow", "다우존스")
    ]
    for symbol, key, name in world_symbols:
        try:
            chart_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            r = requests.get(chart_url, headers=HEADERS, timeout=3.5, verify=False)
            if r.status_code == 200:
                res_data = r.json()
                meta = res_data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                prev = meta.get("chartPreviousClose") or meta.get("previousClose")
                if price:
                    change = round(price - prev, 2) if prev else 0.0
                    rate = round((change / prev) * 100, 2) if prev else 0.0
                    indices[key] = {
                        "name": name,
                        "value": round(price, 2),
                        "change": change,
                        "rate": rate,
                        "status": "정상"
                    }
        except Exception as e:
            logger.warning(f"World index fetch warning for {symbol}: {e}")

    res_data = {
        "updated_at": now_str,
        "source": "Naver Finance Sise/Market/World",
        "is_realtime": True,
        "indices": indices
    }
    _OVERVIEW_CACHE = res_data
    _OVERVIEW_CACHE_TS = now_ts
    return res_data



def fetch_stock_news(ticker: str, stock_name: str, count: int = 5, query: str = "") -> dict:
    """
    종목 주요 뉴스 수집 (네이버 증권 뉴스 iframe 파싱)
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    news_items = []
    
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # 1. 네이버 증권 종목 뉴스 iframe 파싱 (MARKET이 아닌 경우에만)
        if ticker != "MARKET":
            url = f"https://finance.naver.com/item/news_news.naver?code={ticker}&page=1&sm=title_entity_id.basic"
            resp = requests.get(url, headers=HEADERS, timeout=5, verify=False)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                rows = soup.select("table.type5 tr")
                
                for row in rows:
                    title_tag = row.select_one("td.title a")
                    info_tag = row.select_one("td.info")
                    date_tag = row.select_one("td.date")
                    
                    if title_tag:
                        title = title_tag.text.strip()
                        if not title or title == "제목":
                            continue
                        href = title_tag.get("href", "")
                        link = "https://finance.naver.com" + href if href.startswith("/") else href
                        publisher = info_tag.text.strip() if info_tag else "네이버증권"
                        pub_date = date_tag.text.strip() if date_tag else now_str[:10]
                        
                        # 사용자 요청: 실시간 뉴스는 당일 정보만 제공
                        today_str = datetime.now().strftime("%Y.%m.%d")
                        if not pub_date.startswith(today_str):
                            continue
                            
                        news_items.append({
                            "title": title,
                            "link": link,
                            "url": link,      # citation_engine이 url 필드 우선 사용
                            "publisher": publisher,
                            "pub_date": pub_date
                        })
                        
                    if len(news_items) >= count:
                        break

        # 2. Fallback: 네이버 통합 뉴스 RSS 검색 (증권 뉴스 부족 시)
        if len(news_items) == 0 and stock_name:
            if ticker == "MARKET":
                # 질문이 너무 길면 검색이 잘 안되므로, query는 제외하고 시황 관련 키워드만 사용하거나, query를 짧게 자릅니다.
                short_query = query[:15] if query else ""
                search_str = f"{short_query} (시황 OR 증시 OR 매크로 OR 경제) when:1d"
                query_encoded = urllib.parse.quote(search_str.strip())
            else:
                query_encoded = urllib.parse.quote(stock_name + " 주식 when:1d")
            rss_url = f"https://news.google.com/rss/search?q={query_encoded}&hl=ko&gl=KR&ceid=KR:ko"
            rss_resp = requests.get(rss_url, headers=HEADERS, timeout=5, verify=False)
            if rss_resp.status_code == 200:
                rss_soup = BeautifulSoup(rss_resp.text, 'xml')
                items = rss_soup.select("item")
                for item in items[:count]:
                    t = item.select_one("title")
                    l = item.select_one("link")
                    d = item.select_one("pubDate")
                    s = item.select_one("source")
                    if t:
                        link_str = l.text.strip() if l else "#"
                        pub_date_str = d.text.strip()[:16] if d else now_str[:10]
                        
                        # 당일 뉴스만 필터링 (RSS 날짜는 RFC822 포맷: Mon, 31 Aug 2026)
                        today = datetime.now()
                        today_day = str(today.day)
                        today_month_abbr = today.strftime("%b")
                        is_today = (
                            today_month_abbr in pub_date_str and
                            (f" {today_day} " in pub_date_str or f", {today_day} " in pub_date_str)
                        )
                        if not is_today:
                            continue
                        
                        news_items.append({
                            "title": t.text.strip(),
                            "link": link_str,
                            "url": link_str,   # citation_engine이 url 필드 우선 사용
                            "publisher": s.text.strip() if s else "주요 언론사",
                            "pub_date": pub_date_str
                        })
    except Exception as e:
        logger.warning(f"News fetch failed for {stock_name}({ticker}): {e}")

    if not news_items:
        return {
            "status": "데이터 없음",
            "updated_at": now_str,
            "source": "Naver Finance News",
            "ticker": ticker,
            "stock_name": stock_name,
            "count": 0,
            "news": []
        }

    return {
        "status": "정상",
        "updated_at": now_str,
        "source": "Naver Finance News",
        "ticker": ticker,
        "stock_name": stock_name,
        "count": len(news_items),
        "news": news_items
    }

import time

_INDEX_HISTORY_CACHE = {}
_INDEX_CACHE_TTL = 60

def fetch_market_index_history(symbol: str, count: int = 180) -> dict:
    """
    최근 6개월(count일)간의 지수(KOSPI, KOSDAQ, S&P 500, 나스닥) 및 환율(USD/KRW) 일별 추이 데이터 수집
    """
    if not symbol or not symbol.strip():
        symbol = "KOSPI"

    symbol_upper = symbol.upper().strip()
    cache_key = f"{symbol_upper}_{count}"
    now_ts = time.time()

    if cache_key in _INDEX_HISTORY_CACHE:
        cached_ts, cached_res = _INDEX_HISTORY_CACHE[cache_key]
        if now_ts - cached_ts < _INDEX_CACHE_TTL:
            return cached_res

    # 지수 코드 매핑
    target_symbol = symbol_upper
    is_overseas = False
    yahoo_symbol = None

    if symbol_upper in ["USDKRW", "USD/KRW", "USD_KRW", "FX_USDKRW", "EXCHANGE", "원달러"]:
        target_symbol = "FX_USDKRW"
        yahoo_symbol = "KRW=X"
        is_overseas = True

    elif symbol_upper in ["KOSPI", "001", "코스피"]:
        target_symbol = "KOSPI"
    elif symbol_upper in ["KOSDAQ", "201", "코스닥"]:
        target_symbol = "KOSDAQ"
    elif symbol_upper in ["SP500", "S&P500", "S&P 500", "SPI@SPX", "^GSPC", "SPX"]:
        target_symbol = "SP500"
        is_overseas = True
        yahoo_symbol = "^GSPC"
    elif symbol_upper in ["NASDAQ", "나스닥", "NAS@IXIC", "^IXIC", "NAS"]:
        target_symbol = "NASDAQ"
        is_overseas = True
        yahoo_symbol = "^IXIC"

    dates = []
    closes = []
    volumes = []

    # 1. 해외지수 (S&P 500, 나스닥) - Yahoo Finance API (period1/period2 6개월 이력)
    if is_overseas and yahoo_symbol:
        try:
            now_p2 = int(time.time())
            start_p1 = now_p2 - (count * 86400)
            url_yahoo = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?period1={start_p1}&period2={now_p2}&interval=1d"
            resp = requests.get(url_yahoo, headers=HEADERS, timeout=5, verify=False)
            if resp.status_code == 200:
                res_json = resp.json()['chart']['result'][0]
                ts_list = res_json.get('timestamp', [])
                quote = res_json['indicators']['quote'][0]
                close_list = quote.get('close', [])
                vol_list = quote.get('volume', [])

                for idx, t in enumerate(ts_list):
                    if idx < len(close_list) and close_list[idx] is not None:
                        d_str = datetime.fromtimestamp(t).strftime('%Y-%m-%d')
                        c_val = round(float(close_list[idx]), 2)
                        v_val = int(vol_list[idx]) if (vol_list and idx < len(vol_list) and vol_list[idx]) else 0
                        dates.append(d_str)
                        closes.append(c_val)
                        volumes.append(v_val)
        except Exception as e:
            logger.warning(f"Yahoo Finance fetch error for {yahoo_symbol}: {e}")

    # 2. 국내 지수 (KOSPI, KOSDAQ) 및 환율 (FX_USDKRW) - 네이버 fchart API
    if not closes:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={target_symbol}&timeframe=day&count={count}&requestType=0"
        if target_symbol == "FX_USDKRW":
            url = f"https://fchart.stock.naver.com/marketindex/marketindexTimeList.nhn?symbol=FX_USDKRW&timeframe=day&count={count}&requestType=0"

        try:
            resp = requests.get(url, headers=HEADERS, timeout=5, verify=False)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'xml') or BeautifulSoup(resp.text, 'html.parser')
                items = soup.select('item')
                for item in items:
                    data_attr = item.get('data', '')
                    if not data_attr:
                        continue
                    parts = data_attr.split('|')
                    if len(parts) >= 5:
                        date_raw = parts[0]
                        date_str = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
                        close_price = round(float(parts[4]), 2)
                        vol_val = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0
                        dates.append(date_str)
                        closes.append(close_price)
                        volumes.append(vol_val)
        except Exception as e:
            logger.warning(f"Naver fchart fetch error for {target_symbol}: {e}")

    # 3. 데이터 가공 및 리턴
    if closes and len(closes) > 0:
        min_val = min(closes)
        max_val = max(closes)
        latest_val = closes[-1]
        first_val = closes[0]
        change_period = round(latest_val - first_val, 2)
        rate_period = round((change_period / first_val * 100), 2) if first_val > 0 else 0.0

        res_data = {
            "status": "success",
            "symbol": target_symbol,
            "count": len(dates),
            "dates": dates,
            "closes": closes,
            "volumes": volumes,
            "min_val": min_val,
            "max_val": max_val,
            "latest_val": latest_val,
            "period_change": change_period,
            "period_rate": rate_period
        }
        _INDEX_HISTORY_CACHE[cache_key] = (now_ts, res_data)
        return res_data

    return {
        "status": "error",
        "symbol": symbol,
        "message": f"지수/환율({symbol}) 이력 데이터를 불러올 수 없습니다."
    }

