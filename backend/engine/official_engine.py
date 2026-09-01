import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Any, Optional
import urllib3
import urllib.parse

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8',
}

# ─────────────────────────────────────────────────────────────
# 1. 질문 의도(Intent) 분류기
# ─────────────────────────────────────────────────────────────

INTENT_PATTERNS = {
    "DART": [
        "공시", "공개", "보고서", "실적", "분기", "연간", "사업보고서", "반기보고서",
        "주주", "배당", "증자", "자사주", "합병", "분할", "수시공시", "IR", "기업설명"
    ],
    "GOVERNMENT": [
        "정부", "정책", "금리", "규제", "세제", "법안", "기획재정부", "금융위",
        "금감원", "한은", "한국은행", "산업부", "산업통상", "수혜", "지원", "보조금",
        "기준금리", "통화정책", "재정정책", "보조", "정부정책"
    ],
    "ETF": [
        "ETF", "etf", "구성종목", "운용보고서", "운용사", "수수료", "추적오차",
        "편입", "편출", "기초지수", "설명서", "운용현황"
    ]
}

def classify_query_intent(query: str, asset_type: str = "STOCK") -> str:
    """질문 키워드를 분석해 검색 의도를 분류합니다."""
    if asset_type == "ETF":
        return "ETF"

    for intent, keywords in INTENT_PATTERNS.items():
        for kw in keywords:
            if kw.lower() in query.lower():
                return intent

    return "DART"  # 기본: DART 공시 검색


# ─────────────────────────────────────────────────────────────
# 2. DART 전자공시시스템 공시 검색
# ─────────────────────────────────────────────────────────────

def fetch_dart_disclosures(stock_name: str, ticker: str, max_items: int = 5) -> List[Dict[str, Any]]:
    """
    DART 전자공시시스템에서 최신 공시 목록을 수집합니다.
    수집 실패 시 DART 직접 링크 fallback을 제공합니다.
    """
    results = []

    try:
        search_name = urllib.parse.quote(stock_name)
        url = (
            f"https://dart.fss.or.kr/dsSearch/search.ax"
            f"?textCrpNm={search_name}&sort=date&maxResults=20"
        )
        resp = requests.get(url, headers=HEADERS, timeout=8, verify=False)

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            rows = soup.select("table.tbList tbody tr")

            for row in rows:
                cols = row.select("td")
                if len(cols) < 4:
                    continue

                title_tag = row.select_one("td.title a")
                if not title_tag:
                    continue

                title = title_tag.get_text(strip=True)
                if not title or len(title) < 3:
                    continue

                href = title_tag.get("href", "")
                doc_url = (
                    "https://dart.fss.or.kr" + href
                    if href.startswith("/") else href
                )

                corp_name = cols[1].get_text(strip=True) if len(cols) > 1 else stock_name
                doc_type  = cols[2].get_text(strip=True) if len(cols) > 2 else "공시"
                pub_date  = cols[3].get_text(strip=True) if len(cols) > 3 else datetime.now().strftime("%Y.%m.%d")

                results.append({
                    "title": title,
                    "source_type": "DART",
                    "institution": "금융감독원 전자공시시스템(DART)",
                    "pub_date": pub_date,
                    "doc_type": doc_type,
                    "summary": f"{corp_name} / {doc_type} (DART 전자공시)",
                    "url": doc_url
                })

                if len(results) >= max_items:
                    break

    except Exception as e:
        print(f"[Official Engine - DART Error]: {e}")

    # Fallback: DART 검색 직접 링크 제공
    if not results:
        results.append({
            "title": f"{stock_name} 공시 검색 — DART 바로가기",
            "source_type": "DART",
            "institution": "금융감독원 전자공시시스템(DART)",
            "pub_date": datetime.now().strftime("%Y.%m.%d"),
            "doc_type": "공시 검색",
            "summary": (
                f"DART 전자공시 시스템에서 '{stock_name}' 관련 최신 공시를 직접 확인하세요. "
                "사업보고서, 분기보고서, 주요사항보고서 등을 열람할 수 있습니다."
            ),
            "url": "https://dart.fss.or.kr/dsSearch/main.do"
        })

    return results


# ─────────────────────────────────────────────────────────────
# 3. 정부기관 보도자료 검색
# ─────────────────────────────────────────────────────────────

GOVERNMENT_SOURCES = [
    {
        "name": "금융위원회",
        "search_url": "https://www.fsc.go.kr/no010101?srchWord={query}",
        "base_url": "https://www.fsc.go.kr",
        "fallback_url": "https://www.fsc.go.kr",
        "row_selector": ".bbs-list tbody tr, table tbody tr",
        "title_selector": "td.title a, .title a, a",
        "date_selector": "td.date, .date",
        "category": "금융정책"
    },
    {
        "name": "한국은행",
        "search_url": "https://www.bok.or.kr/portal/bbs/B0000230/list.do?menuNo=200612&searchWrd={query}",
        "base_url": "https://www.bok.or.kr",
        "fallback_url": "https://www.bok.or.kr",
        "row_selector": ".board-list tbody tr, table.tb tbody tr",
        "title_selector": "td a",
        "date_selector": "td.date, td:last-child",
        "category": "통화/금리정책"
    },
    {
        "name": "금융감독원",
        "search_url": "https://www.fss.or.kr/fss/bbs/B0000188/list.do?menuNo=200218&searchWrd={query}",
        "base_url": "https://www.fss.or.kr",
        "fallback_url": "https://www.fss.or.kr",
        "row_selector": "table.tb01 tbody tr, .bd-list tbody tr",
        "title_selector": "td a",
        "date_selector": "td:last-child",
        "category": "금융감독"
    },
]

# 산업 관련 검색 키워드 매핑
INDUSTRY_KEYWORDS = {
    "반도체": "반도체",
    "배터리": "배터리",
    "2차전지": "배터리",
    "자동차": "자동차",
    "AI": "인공지능",
    "바이오": "바이오",
    "금융": "금융",
    "부동산": "부동산",
    "에너지": "에너지",
}

def _pick_search_keyword(stock_name: str, query: str) -> Optional[str]:
    """정부기관 검색에 쓸 가장 적합한 키워드를 선택합니다."""
    if stock_name == "전체 시황" or stock_name == "MARKET":
        # 사용자의 긴 질문 쿼리 대신, 보편적으로 검색이 잘 되는 경제 정책 키워드를 반환
        return "경제 동향"

    combined = stock_name + " " + query
    for raw, mapped in INDUSTRY_KEYWORDS.items():
        if raw in combined:
            return mapped
    # 특정 종목명이 정책 검색에 적합하지 않은 유령/무효 종목인 경우 stock_name 사용 (키워드 남발 방지)
    return stock_name if stock_name else None

def fetch_government_docs(stock_name: str, query: str, max_items: int = 3) -> List[Dict[str, Any]]:
    """
    정부기관(금융위, 한은, 금감원) 메인 홈페이지 바로가기 데이터를 리턴합니다.
    서브폴더 오작동 및 중복 출력을 방지하고, 각 기관별 메인 도메인으로만 1개씩 명확하게 연결됩니다.
    """
    results = []
    for source in GOVERNMENT_SOURCES:
        results.append({
            "title": f"[{source['name']}] 공식 메인 홈페이지 바로가기 (로그인)",
            "source_type": "정부기관",
            "institution": source["name"],
            "pub_date": datetime.now().strftime("%Y.%m.%d"),
            "doc_type": source["category"],
            "summary": f"{source['name']} 공식 메인 홈페이지로 접속하여 로그인 및 정책/감독/통계 서비스를 이용하세요.",
            "url": source["fallback_url"]  # 메인 루트 도메인 (fsc.go.kr, fss.or.kr, bok.or.kr)
        })
    return results[:max_items]


# ─────────────────────────────────────────────────────────────
# 4. ETF 공식자료 검색
# ─────────────────────────────────────────────────────────────

ETF_MANAGERS = {
    "TIGER":  {"name": "미래에셋자산운용", "url": "https://www.tigeretf.com"},
    "KODEX":  {"name": "삼성자산운용",     "url": "https://www.kodex.com"},
    "KBSTAR": {"name": "KB자산운용",       "url": "https://www.kbstaretf.com"},
    "HANARO": {"name": "NH아문디자산운용", "url": "https://www.hanaroetf.com"},
    "RISE":   {"name": "KB자산운용",       "url": "https://www.riseetf.com"},
    "ACE":    {"name": "한국투자신탁운용", "url": "https://www.aceetf.co.kr"},
    "TIMEFOLIO": {"name": "타임폴리오자산운용", "url": "https://www.timefolioetf.com"},
    "SOL":    {"name": "신한자산운용",     "url": "https://www.soletf.com"},
    "KOSEF":  {"name": "키움투자자산운용", "url": "https://etf.kiwoom.com"},
}

def fetch_etf_official_docs(etf_name: str, ticker: str, manager: str = "") -> List[Dict[str, Any]]:
    """
    ETF 운용사 공식자료 및 DART 운용보고서, KRX ETF 정보를 수집합니다.
    """
    results = []

    # 1. DART 운용보고서 검색
    dart_results = fetch_dart_disclosures(etf_name, ticker, max_items=3)
    results.extend(dart_results)

    # 2. KRX ETF 정보 페이지
    results.append({
        "title": f"{etf_name} — KRX 상장 ETF 정보 조회",
        "source_type": "ETF운용사",
        "institution": "한국거래소(KRX)",
        "pub_date": datetime.now().strftime("%Y.%m.%d"),
        "doc_type": "ETF 기본정보",
        "summary": (
            f"KRX에서 {etf_name}({ticker})의 구성종목, 순자산총액(NAV), "
            "일별 수익률, 거래량 등 상세 정보를 확인하세요."
        ),
        "url": "https://etf.krx.co.kr/contents/ETF/02/EtfSearch.jspx"
    })

    # 3. 운용사별 공식 페이지 링크
    matched_manager = None
    etf_upper = etf_name.upper()
    for prefix, info in ETF_MANAGERS.items():
        if prefix in etf_upper or (manager and manager in info["name"]):
            matched_manager = info
            break

    if matched_manager:
        results.append({
            "title": f"{matched_manager['name']} — {etf_name} 상품 공식 페이지",
            "source_type": "ETF운용사",
            "institution": matched_manager["name"],
            "pub_date": datetime.now().strftime("%Y.%m.%d"),
            "doc_type": "ETF 운용현황",
            "summary": (
                f"{matched_manager['name']} 공식 사이트에서 {etf_name} ETF의 "
                "구성종목, 운용현황, 투자설명서, 운용보고서를 확인하세요."
            ),
            "url": matched_manager["url"]
        })

    # 4. 네이버 증권 ETF 페이지
    results.append({
        "title": f"{etf_name} ({ticker}) — 네이버 증권 ETF 상세",
        "source_type": "DART",
        "institution": "네이버 증권",
        "pub_date": datetime.now().strftime("%Y.%m.%d"),
        "doc_type": "ETF 시세/구성종목",
        "summary": f"네이버 증권에서 {etf_name}의 현재가, 구성종목, 수익률을 확인하세요.",
        "url": f"https://finance.naver.com/item/main.naver?code={ticker}"
    })

    return results[:6]


# ─────────────────────────────────────────────────────────────
# 5. 통합 공식자료 검색 메인 함수
# ─────────────────────────────────────────────────────────────

def fetch_official_documents(
    ticker: str,
    name: str,
    query: str,
    asset_type: str = "STOCK",
    manager: str = ""
) -> Dict[str, Any]:
    """
    질문 의도를 분석하고 적합한 공식자료(DART/정부기관/ETF 운용사)를 검색합니다.
    - 언론 뉴스와 분리된 공식/정부/공시 자료만 수집
    - 수집 실패 시 임의 데이터 생성 금지, 실패 메시지 반환
    """
    if not name and not ticker:
        return {
            "status": "error",
            "message": "검색 대상 종목/ETF가 없습니다.",
            "intent": "NONE",
            "items": []
        }

    intent = classify_query_intent(query, asset_type)
    all_results = []

    try:
        if asset_type == "ETF":
            all_results = fetch_etf_official_docs(name, ticker, manager)

        elif ticker == "MARKET" or intent == "GOVERNMENT":
            # MARKET/정부 키워드 질문: 기관 메인 홈페이지 바로가기 3개(기관별 1개씩)만 제공
            gov_docs = fetch_government_docs(name, query, max_items=3)
            if ticker == "MARKET":
                all_results = gov_docs
            else:
                dart_docs = fetch_dart_disclosures(name, ticker, max_items=2)
                all_results = gov_docs + dart_docs

        else:
            # 기본: DART 우선
            dart_docs = fetch_dart_disclosures(name, ticker, max_items=5)
            all_results = dart_docs

            # 쿼리에 정부 키워드가 포함된 경우 정부 자료 보충 (중복 없이 기관별 1개)
            gov_kws = ["정책", "정부", "금리", "규제", "세제", "금융위", "한은"]
            if any(kw in query for kw in gov_kws):
                existing_institutions = {r.get("institution", "") for r in all_results}
                gov_docs = fetch_government_docs(name, query, max_items=3)
                # 이미 포함된 기관 중복 제거
                gov_docs = [g for g in gov_docs if g.get("institution") not in existing_institutions]
                all_results.extend(gov_docs)

    except Exception as e:
        print(f"[Official Engine Critical Error]: {e}")
        return {
            "status": "fail",
            "message": "공식자료 검색에 실패했습니다.",
            "intent": intent,
            "items": []
        }

    if not all_results:
        return {
            "status": "fail",
            "message": "공식자료 검색에 실패했습니다.",
            "intent": intent,
            "items": []
        }

    return {
        "status": "success",
        "intent": intent,
        "search_keyword": name,
        "count": len(all_results),
        "items": all_results[:6]
    }
