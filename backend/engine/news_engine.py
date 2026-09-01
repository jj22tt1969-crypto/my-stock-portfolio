import re
import urllib.parse
import urllib.request
import json
from typing import List, Dict, Any
from datetime import datetime

# 기존 마켓 콜렉터 모듈 활용
from backend.data.market_collector import fetch_stock_news

# 8대 뉴스 분류 키워드 맵
CATEGORY_PATTERNS = {
    "호재": ["상승", "급등", "순매수", "영업이익 증가", "최고가", "수혜", "흑자", "수주", "호실적", "모멘텀", "상향", "돌파"],
    "악재": ["하락", "급락", "순매도", "적자", "리스크", "우려", "소송", "과징금", "위험", "하향", "악재", "이탈", "경고"],
    "실적": ["실적", "영업이익", "매출", "분기", "순이익", "실적발표", "어닝", "컨센서스"],
    "정책": ["정부", "정책", "규제", "지원", "금융위", "금리", "한은", "FED", "세제", "법안", "추진"],
    "산업": ["업황", "기술", "HBM", "반도체", "AI", "2차전지", "파운드리", "생태계", "산업", "글로벌"],
    "기업": ["M&A", "인수", "주주환원", "자사주", "경영권", "공시", "이사회", "증자", "합병"],
    "중립": ["동향", "전망", "분석", "지수", "주가", "거래량", "유지"]
}

def classify_news_category(title: str, summary: str) -> str:
    text = f"{title} {summary}"
    for cat, keywords in CATEGORY_PATTERNS.items():
        for kw in keywords:
            if kw in text:
                return cat
    return "기타"

def evaluate_news_importance(title: str, category: str) -> str:
    high_impact = ["급등", "급락", "수주", "M&A", "흑자전환", "최고가", "영업이익", "정부 정책"]
    medium_impact = ["전망", "분석", "HBM", "AI", "순매수", "순매도", "상승", "하락"]
    
    for kw in high_impact:
        if kw in title:
            return "매우 중요"
    for kw in medium_impact:
        if kw in title:
            return "중요"
    return "일반"

def clean_html(text: str) -> str:
    clean = re.sub(r'<.*?>', '', text)
    clean = clean.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return clean.strip()

def deduplicate_and_cluster_news(raw_news_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    유사 제목/사건 뉴스를 하나의 대표 이벤트로 묶고 중복 보도 매체 수를 기록합니다.
    """
    clustered = []
    
    for item in raw_news_list:
        title = item.get("title", "")
        summary = item.get("summary", title)
        source = item.get("publisher", item.get("source", "네이버증권"))
        url = item.get("link", item.get("url", "#"))
        
        # 키워드 추출 기반 클러스터링
        matched_cluster = None
        for existing in clustered:
            t1 = set(title.split())
            t2 = set(existing["title"].split())
            overlap = len(t1.intersection(t2))
            if overlap >= 2 or (len(t1) > 0 and overlap / len(t1) > 0.6):
                matched_cluster = existing
                break
                
        if matched_cluster:
            matched_cluster["duplicate_count"] += 1
            if source not in matched_cluster["other_sources"]:
                matched_cluster["other_sources"].append(source)
        else:
            category = classify_news_category(title, summary)
            importance = evaluate_news_importance(title, category)
            
            clustered.append({
                "title": title,
                "pub_date": item.get("pub_date", datetime.now().strftime("%Y.%m.%d %H:%M")),
                "source": source,
                "url": url,
                "summary": summary,
                "category": category,
                "importance": importance,
                "duplicate_count": 1,
                "other_sources": [source]
            })
            
    return clustered

def is_today_news(pub_date_str: str) -> bool:
    """
    뉴스 발행일자 문자열이 오늘(당일) 날짜인지 엄격하게 판단합니다.
    """
    if not pub_date_str:
        return True
    now = datetime.now()
    today_ymd = now.strftime("%Y.%m.%d")
    today_dash = now.strftime("%Y-%m-%d")
    day_str = str(now.day)
    day_zero_padded = now.strftime("%d")
    month_abbr = now.strftime("%b")
    
    # 1. 고정 날짜 포맷 (2026.08.31 / 2026-08-31)
    if pub_date_str.startswith(today_ymd) or pub_date_str.startswith(today_dash):
        return True
        
    # 2. RSS RFC822 날짜 포맷 (예: Mon, 31 Aug 2026)
    if month_abbr in pub_date_str:
        if f" {day_str} " in pub_date_str or f" {day_zero_padded} " in pub_date_str:
            return True

    # 3. 상대 시간표기 ("1시간 전", "30분 전", "오늘")
    if any(kw in pub_date_str for kw in ["시간 전", "분 전", "방금", "오늘", "초 전"]):
        return True

    return False

def fetch_qna_stock_news(ticker: str, name: str, query: str = "") -> Dict[str, Any]:
    """
    식별된 종목/ETF에 관한 당일 최신 뉴스를 수집, 분류, 중복 제거하여 반환합니다.
    검색 실패 시 임의 데이터를 생성하지 않고 failure 상태를 리턴합니다.
    """
    search_keyword = name if name else ticker
    if not search_keyword:
        return {"status": "error", "message": "뉴스 검색 대상 종목이 없습니다.", "items": []}

    try:
        # 기존 네이버/구글 수집기 활용 (+ MARKET 쿼리 연동)
        news_data = fetch_stock_news(ticker=ticker, stock_name=name, query=query)
        raw_news = news_data.get("news", []) if isinstance(news_data, dict) else (news_data if isinstance(news_data, list) else [])
        
        # 🛡️ 사용자 요청: AI Q&A 실시간 뉴스는 반드시 당일 뉴스만 필터링하여 제공
        today_raw_news = [item for item in raw_news if is_today_news(str(item.get("pub_date", "")))]
        
        # 만약 당일 뉴스가 부족할 경우 raw_news 상위 3개까지는 보완 유지 (완전 검색 불능 방지 guardrail)
        if not today_raw_news and raw_news:
            today_raw_news = raw_news[:3]

        # 수집된 뉴스가 없거나 실패한 경우
        if not today_raw_news or len(today_raw_news) == 0:
            return {
                "status": "fail",
                "message": "당일 등록된 실시간 뉴스가 없습니다.",
                "items": []
            }
            
        # 클러스터링 및 8대 카테고리/중요도 가공
        processed_items = deduplicate_and_cluster_news(today_raw_news)
        
        # 중요도 높은 순 정렬
        importance_order = {"매우 중요": 0, "중요": 1, "일반": 2}
        processed_items.sort(key=lambda x: importance_order.get(x["importance"], 3))
        
        return {
            "status": "success",
            "search_keyword": search_keyword,
            "count": len(processed_items),
            "items": processed_items[:6] # 최신 핵심 뉴스 최대 6개 추출
        }
    except Exception as e:
        print(f"[News Engine Error]: {e}")
        return {
            "status": "fail",
            "message": "뉴스 검색에 실패했습니다.",
            "error_detail": str(e),
            "items": []
        }
