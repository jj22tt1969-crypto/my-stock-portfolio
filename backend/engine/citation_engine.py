import re
from datetime import datetime
from typing import List, Dict, Any, Optional

# 주요 금융/경제 언론사 목록 (신뢰도: 높음)
MAJOR_FINANCIAL_PRESS = [
    "연합인포맥스", "한국경제", "매일경제", "조선비즈", "서울경제", 
    "이데일리", "머니투데이", "파이낸셜뉴스", "아시아경제", "헤럴드경제", 
    "연합뉴스", "동아일보", "중앙일보", "조선일보", "SBS Biz"
]

def calculate_reliability(source_type: str, publisher: str) -> str:
    """
    출처 유형 및 발행 기관에 기반하여 신뢰도 레벨을 자동 평가합니다.
    - 공식기관/공식공시 (DART, GOVERNMENT) -> 매우 높음
    - 기업/운용사 공식자료 (COMPANY, OFFICIAL) -> 매우 높음
    - 주요 금융언론 -> 높음
    - 일반언론 -> 중간
    - 블로그/커뮤니티/SNS -> 참고
    """
    st_upper = source_type.upper() if source_type else "OTHER"
    
    if st_upper in ["DART", "GOVERNMENT"]:
        return "매우 높음"
    elif st_upper in ["COMPANY", "OFFICIAL"]:
        return "매우 높음"
    elif st_upper == "NEWS":
        for press in MAJOR_FINANCIAL_PRESS:
            if press in publisher:
                return "높음"
        return "중간"
    elif st_upper in ["BLOG", "COMMUNITY", "SNS", "OTHER"]:
        if any(kw in publisher for kw in ["블로그", "커뮤니티", "카페", "SNS", "트위터", "유튜브"]):
            return "참고"
        return "중간"
    
    return "중간"

def map_source_type(raw_source_type: str, institution: str = "") -> str:
    """
    원본 수집 타입 및 기관명을 기반으로 산출 표준 source_type을 분류합니다.
    (DART, GOVERNMENT, COMPANY, OFFICIAL, NEWS, OTHER)
    """
    if not raw_source_type:
        return "OTHER"

    rst = raw_source_type.upper()
    if "DART" in rst or "공시" in rst:
        return "DART"
    elif "GOV" in rst or "정부" in rst or any(inst in institution for inst in ["금융위원회", "한국은행", "금융감독원", "기획재정부"]):
        return "GOVERNMENT"
    elif "ETF" in rst or "운용사" in rst or "KRX" in institution or "한국거래소" in institution:
        return "OFFICIAL"
    elif "COMPANY" in rst or "기업" in rst:
        return "COMPANY"
    elif "NEWS" in rst or "뉴스" in rst or "언론" in rst:
        return "NEWS"
    
    return "OTHER"

def build_citation_item(
    idx: int,
    raw_item: Dict[str, Any],
    default_source_type: str = "NEWS"
) -> Optional[Dict[str, Any]]:
    """
    수집된 단일 검색 항목(뉴스 또는 공식자료)으로부터 9개 필수 필드가 포함된 Citation 객체를 생성합니다.
    실제 URL이 존재하지 않거나 무효한 항목은 생성하지 않습니다.
    """
    url = raw_item.get("url") or raw_item.get("link")
    if not url or url == "#" or not str(url).startswith("http"):
        # 🛡️ Guardrail: 실제 유효한 URL이 없는 항목은 출처로 인용하지 않음
        return None

    title = raw_item.get("title", "").strip()
    if not title:
        return None

    publisher = raw_item.get("institution") or raw_item.get("source") or raw_item.get("publisher") or "기타 제공처"
    raw_st = raw_item.get("source_type") or default_source_type
    source_type = map_source_type(raw_st, publisher)
    
    pub_date = raw_item.get("pub_date") or raw_item.get("published_at") or datetime.now().strftime("%Y.%m.%d")
    retrieved_at = raw_item.get("retrieved_at") or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    
    reliability = calculate_reliability(source_type, publisher)
    
    # 관련도 평가 (뉴스 중요도 또는 기본값 활용)
    importance = raw_item.get("importance", "일반")
    if source_type in ["DART", "GOVERNMENT", "OFFICIAL"]:
        relevance = "매우 높음 (공식 출처)"
    elif importance == "매우 중요":
        relevance = "높음 (주요 사건)"
    elif importance == "중요":
        relevance = "높음 (관련 이슈)"
    else:
        relevance = "보통 (참고 뉴스)"

    return {
        "source_id": f"CIT-{idx}",
        "source_type": source_type,
        "title": title,
        "publisher": publisher,
        "published_at": pub_date,
        "url": url,
        "retrieved_at": retrieved_at,
        "reliability": reliability,
        "relevance": relevance,
        "summary": raw_item.get("summary", "")
    }

def generate_citations(
    news_items: List[Dict[str, Any]],
    official_items: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    수집된 뉴스 및 공식자료 수집 결과로부터 검증된 Citation 목록을 생성합니다.
    - 공식자료(DART, 정부, ETF)를 우선순위로 배치
    - 정부기관 바로가기의 경우 기관별로 1개씩만 중복 없이 깔끔하게 노출
    """
    citations = []
    current_id = 1
    seen_gov_institutions = set()

    # 1. 공식자료 항목 우선 인용 생성
    if official_items:
        for item in official_items:
            publisher = item.get("institution") or item.get("publisher") or ""
            raw_st = item.get("source_type", "")
            
            # 정부기관일 경우 동일 기관 중복 노출 방지
            if "GOV" in str(raw_st).upper() or "정부" in str(raw_st) or any(inst in publisher for inst in ["금융위원회", "한국은행", "금융감독원"]):
                if publisher in seen_gov_institutions:
                    continue
                seen_gov_institutions.add(publisher)

            cit = build_citation_item(current_id, item, default_source_type="OFFICIAL")
            if cit:
                citations.append(cit)
                current_id += 1

    # 2. 실시간 뉴스 항목 인용 생성
    if news_items:
        for item in news_items:
            # 중복 URL 체크
            url = item.get("url") or item.get("link")
            if any(c["url"] == url for c in citations):
                continue
                
            cit = build_citation_item(current_id, item, default_source_type="NEWS")
            if cit:
                citations.append(cit)
                current_id += 1

    return citations
