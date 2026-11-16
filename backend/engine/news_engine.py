import re
import urllib.parse
import urllib.request
import json
import html
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

# 기존 마켓 콜렉터 모듈 활용
from backend.data.market_collector import fetch_stock_news

# KST Timezone 정의 (UTC+9)
KST = timezone(timedelta(hours=9))

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
    if not text:
        return ""
    clean = re.sub(r'<.*?>', '', text)
    return html.unescape(clean).strip()

def parse_to_kst_datetime(dt_raw: Any) -> datetime:
    """
    F10C: 다양한 형식의 날짜 문자열(RFC 822 GMT, Naver YYYYMMDDHHmm, ISO 등)을
    timezone-aware KST datetime 객체로 완벽 변환합니다.
    """
    now_kst = datetime.now(KST)
    if not dt_raw:
        return now_kst
    
    if isinstance(dt_raw, datetime):
        if dt_raw.tzinfo is None:
            return dt_raw.replace(tzinfo=KST)
        return dt_raw.astimezone(KST)

    dt_str = str(dt_raw).strip()
    if not dt_str:
        return now_kst

    # 1. RFC 822 / 2822 형식 (예: "Mon, 16 Nov 2026 01:21:00 GMT" or "Sun, 15 Nov 2026 23:48:58 +0000")
    try:
        parsed = parsedate_to_datetime(dt_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(KST)
    except Exception:
        pass

    # 2. Naver 모바일 API 12/14/8자리 포맷
    clean_digits = re.sub(r"\D", "", dt_str)
    if len(clean_digits) == 12:
        try:
            naive = datetime.strptime(clean_digits, "%Y%m%d%H%M")
            return naive.replace(tzinfo=KST)
        except Exception:
            pass
    elif len(clean_digits) == 14:
        try:
            naive = datetime.strptime(clean_digits, "%Y%m%d%H%M%S")
            return naive.replace(tzinfo=KST)
        except Exception:
            pass
    elif len(clean_digits) == 8:
        try:
            naive = datetime.strptime(clean_digits, "%Y%m%d")
            return naive.replace(tzinfo=KST)
        except Exception:
            pass

    # 3. YYYY.MM.DD HH:mm 또는 YYYY-MM-DD HH:mm
    for fmt in ("%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M", "%Y.%m.%d", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(dt_str[:16], fmt)
            return naive.replace(tzinfo=KST)
        except Exception:
            pass

    return now_kst

def get_age_bucket(dt_kst: datetime, now_kst: datetime) -> str:
    """
    F10C: KST 기준 발행일자와 현재 시간의 차이를 기반으로 age_bucket을 산출합니다.
    - TODAY: 동일 날짜이거나 24시간 이내
    - LAST_7D: 7일(168시간) 이내
    - LAST_30D: 30일(720시간) 이내
    - OLDER: 30일 초과
    """
    diff_sec = (now_kst - dt_kst).total_seconds()
    if diff_sec < 0 or dt_kst.date() == now_kst.date() or diff_sec <= 86400:
        return "TODAY"
    elif diff_sec <= 7 * 86400:
        return "LAST_7D"
    elif diff_sec <= 30 * 86400:
        return "LAST_30D"
    return "OLDER"

def normalize_title(title: str) -> str:
    """
    F10C: 기사 제목 중복 제거를 위한 정규화 함수
    - 언론사 접미사(예: - 머니투데이, - 뉴스핌) 제거
    - 머리말 대괄호 태그(예: [단독], [속보]) 제거
    - 특수문자 및 공백 제거
    """
    t = re.sub(r"\s*-\s*[가-힣A-Za-z0-9\s]+$", "", title)
    t = re.sub(r"^\[.*?\]\s*", "", t)
    t = re.sub(r"[\s\W_]+", "", t)
    return t.lower()

def check_relevance(title: str, body: str, stock_name: str, ticker: str) -> str:
    """
    F10C: 대상 기업 관련성 정밀 검증
    - HIGH: title에 정확 회사명/정규화 회사명 포함
    - MEDIUM: title에는 없으나 body/summary에 회사명 포함
    - NONE: 둘 다 미포함 (제외)
    """
    if ticker == "MARKET":
        market_keywords = ["시황", "증시", "코스피", "코스닥", "매크로", "경제", "금리", "환율", "외국인", "기관"]
        text = f"{title} {body}"
        return "HIGH" if any(kw in text for kw in market_keywords) else "NONE"

    clean_name = re.sub(r"(\(주\)|주식회사|㈜)", "", stock_name).strip()
    if not clean_name:
        clean_name = stock_name.strip()
    norm_name = re.sub(r"\s+", "", clean_name).lower()
    t_lower = title.lower()
    b_lower = body.lower()

    # Title 매칭 (HIGH)
    if clean_name.lower() in t_lower or (norm_name and norm_name in re.sub(r"\s+", "", t_lower)):
        return "HIGH"
    
    # Body 매칭 (MEDIUM)
    if clean_name.lower() in b_lower or (norm_name and norm_name in re.sub(r"\s+", "", b_lower)):
        return "MEDIUM"

    return "NONE"

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
                "link": url,
                "summary": summary,
                "category": category,
                "importance": importance,
                "duplicate_count": 1,
                "other_sources": [source],
                "published_at": item.get("published_at"),
                "age_bucket": item.get("age_bucket", "TODAY"),
                "relevance": item.get("relevance", "HIGH"),
            })
            
    return clustered

def fetch_qna_stock_news(ticker: str, name: str, query: str = "") -> Dict[str, Any]:
    """
    F10C: News & Official Coverage Pipeline
    
    파이프라인 순서 준수:
    fetch all candidate items
    -> parse datetime
    -> KST 변환
    -> relevance filter (HIGH/MEDIUM 통과, NONE 제외)
    -> dedupe (URL 및 정규화 제목)
    -> 최신순 정렬
    -> requested count slice (최대 6개)
    """
    search_keyword = name if name else ticker
    if not search_keyword:
        return {"status": "error", "message": "뉴스 검색 대상 종목이 없습니다.", "items": []}

    now_kst = datetime.now(KST)

    try:
        # 1. 1차 수집 (Naver 모바일 종목 뉴스 API + 필요시 Google RSS fallback)
        news_data = fetch_stock_news(ticker=ticker, stock_name=name, count=6, query=query)
        raw_news = news_data.get("news", []) if isinstance(news_data, dict) else (news_data if isinstance(news_data, list) else [])

        # 2. Datetime 파싱, KST 변환, Relevance 검증, Age Bucket 산출
        candidates = []
        for it in raw_news:
            raw_title = it.get("title", "")
            title = clean_html(raw_title)
            if not title:
                continue
            body = clean_html(it.get("body", "") or it.get("summary", title))
            rel = check_relevance(title, body, search_keyword, ticker)
            if rel == "NONE":
                continue  # 무관 기사 즉시 제외

            dt_kst = parse_to_kst_datetime(it.get("pub_date", ""))
            bucket = get_age_bucket(dt_kst, now_kst)
            
            # 무한 확장 방지: 30일 초과(OLDER) 기사는 제외
            if bucket not in ("TODAY", "LAST_7D", "LAST_30D"):
                continue

            pub_display = dt_kst.strftime("%Y.%m.%d %H:%M")
            url = it.get("url") or it.get("link") or "#"
            pub_name = it.get("publisher") or it.get("source") or "주요 언론사"

            candidates.append({
                "title": title,
                "summary": body,
                "body": body,
                "url": url,
                "link": url,
                "publisher": pub_name,
                "source": pub_name,
                "dt_kst": dt_kst,
                "pub_date": pub_display,
                "published_at": dt_kst.isoformat(),
                "age_bucket": bucket,
                "relevance": rel
            })

        # 3. Dedupe (URL 및 제목 정규화 중복 제거)
        seen_urls = set()
        seen_norm_titles = set()
        deduped = []
        for c in candidates:
            if c["url"] in seen_urls:
                continue
            norm_t = normalize_title(c["title"])
            if norm_t in seen_norm_titles:
                continue
            seen_urls.add(c["url"])
            seen_norm_titles.add(norm_t)
            deduped.append(c)

        # 4. 수집된 관련 뉴스가 없는 경우 (F10C Zero-News Guard: 건수 채우기용 무관기사 금지)
        if not deduped:
            return {
                "status": "fail",
                "message": "최근 30일 이내 등록된 관련 뉴스가 없습니다.",
                "items": []
            }

        # 5. 클러스터링 및 8대 카테고리/중요도 가공
        processed_items = deduplicate_and_cluster_news(deduped)

        # 6. 최신순 정렬 (dt_kst 기준 내림차순, 동일시 HIGH relevance 우선)
        processed_items.sort(
            key=lambda x: (
                x.get("relevance") == "HIGH",
                parse_to_kst_datetime(x.get("pub_date", "")).timestamp() if x.get("pub_date") else 0
            ),
            reverse=True
        )

        # 7. 상위 슬라이스 (최대 6개)
        final_items = processed_items[:6]

        return {
            "status": "success",
            "search_keyword": search_keyword,
            "count": len(final_items),
            "items": final_items
        }

    except Exception as e:
        print(f"[News Engine Error]: {e}")
        return {
            "status": "fail",
            "message": "뉴스 검색에 실패했습니다.",
            "error_detail": str(e),
            "items": []
        }
