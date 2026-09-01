import re
from typing import List, Dict, Any

# 주식 및 ETF 마스터 데이터베이스 (확장 가능한 마스터 레코드)
STOCK_ETF_MASTER = [
    # 대표 개별주식 (KOSPI / KOSDAQ)
    {"name": "삼성전자", "ticker": "005930", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "SK하이닉스", "ticker": "000660", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "삼성E&A", "ticker": "028050", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "샌즈랩", "ticker": "411080", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "코난테크놀로지", "ticker": "402030", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "한일시멘트", "ticker": "300720", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "자이글", "ticker": "234920", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "아톤", "ticker": "158430", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "씨에스윈드", "ticker": "112610", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "케이프", "ticker": "064820", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "바이오니아", "ticker": "064550", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "라온시큐어", "ticker": "042510", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "현대차", "ticker": "005380", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "NAVER", "ticker": "035420", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    # KOSPI / KOSDAQ 통신/인프라/금융/대형주 및 핵심 대표 종목 대거 확장
    {"name": "SK텔레콤", "ticker": "017670", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "KT", "ticker": "030200", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "LG유플러스", "ticker": "032640", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "한국전력", "ticker": "015760", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "삼성물산", "ticker": "028260", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "SK", "ticker": "034730", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "LG에너지솔루션", "ticker": "373220", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "삼성바이오로직스", "ticker": "207940", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "기아", "ticker": "000270", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "셀트리온", "ticker": "068270", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "KB금융", "ticker": "105560", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "신한지주", "ticker": "055550", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "POSCO홀딩스", "ticker": "005490", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "포스코홀딩스", "ticker": "005490", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "포스코퓨처엠", "ticker": "003670", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "삼성SDI", "ticker": "006400", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "LG화학", "ticker": "051910", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "현대모비스", "ticker": "012330", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "카카오뱅크", "ticker": "323410", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "한화에어로스페이스", "ticker": "012450", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "현대로템", "ticker": "064350", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "HD현대중공업", "ticker": "329180", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "크래프톤", "ticker": "259960", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "하나금융지주", "ticker": "086790", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "우리금융지주", "ticker": "316140", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "삼성생명", "ticker": "032830", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "삼성화재", "ticker": "000810", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "삼성전기", "ticker": "009150", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "두산에너빌리티", "ticker": "034020", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "한화오션", "ticker": "042660", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "삼성중공업", "ticker": "010140", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "HMM", "ticker": "011200", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "카카오페이", "ticker": "377300", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "SK바이오팜", "ticker": "326030", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "SK바이오사이언스", "ticker": "302440", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "하이브", "ticker": "352820", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "HYBE", "ticker": "352820", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "엔씨소프트", "ticker": "036570", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "넷마블", "ticker": "251270", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "S-Oil", "ticker": "010950", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "SOIL", "ticker": "010950", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},
    {"name": "에쓰오일", "ticker": "010950", "market": "KOSPI", "asset_type": "STOCK", "manager": ""},

    # 코스닥 핵심 선도 종목군
    {"name": "에코프로비엠", "ticker": "247540", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "에코프로", "ticker": "086520", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "HLB", "ticker": "028300", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "알테오젠", "ticker": "196170", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "루닛", "ticker": "328130", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "레인보우로보틱스", "ticker": "277810", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "셀트리온제약", "ticker": "068760", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "리노공업", "ticker": "058470", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "HPSP", "ticker": "403870", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "이오테크닉스", "ticker": "039030", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "솔브레인", "ticker": "357780", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "동진쎄미켐", "ticker": "005290", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "원익IPS", "ticker": "240810", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "하나마이크론", "ticker": "067310", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "제주반도체", "ticker": "080220", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "가온칩스", "ticker": "399720", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "칩스앤미디어", "ticker": "094360", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "어보브반도체", "ticker": "102120", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "삼천당제약", "ticker": "000250", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "리가켐바이오", "ticker": "141080", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "클래시스", "ticker": "214150", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "휴젤", "ticker": "145020", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "파두", "ticker": "440110", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "펄어비스", "ticker": "263750", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "JYP Ent.", "ticker": "035900", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "JYP", "ticker": "035900", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "SM", "ticker": "041510", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "에스엠", "ticker": "041510", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "YG엔터테인먼트", "ticker": "122870", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "와이지엔터테인먼트", "ticker": "122870", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "CJ ENM", "ticker": "035760", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},
    {"name": "스튜디오드래곤", "ticker": "253450", "market": "KOSDAQ", "asset_type": "STOCK", "manager": ""},

    # ETF 대표군 및 인기 ETF 라인업 대폭 확장
    {"name": "KODEX 200", "ticker": "069500", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "TIGER 미국S&P500", "ticker": "360750", "market": "ETF", "asset_type": "ETF", "manager": "미래에셋자산운용"},
    {"name": "KODEX 미국S&P500", "ticker": "379800", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "KODEX 미국S&P500TR", "ticker": "379800", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "KODEX 반도체", "ticker": "091160", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "TIGER 미국나스닥100", "ticker": "133690", "market": "ETF", "asset_type": "ETF", "manager": "미래에셋자산운용"},
    {"name": "ACE 미국빅테크TOP7 Plus", "ticker": "465580", "market": "ETF", "asset_type": "ETF", "manager": "한국투자신탁운용"},
    {"name": "RISE 200", "ticker": "148020", "market": "ETF", "asset_type": "ETF", "manager": "KB자산운용"},
    {"name": "SOL 미국S&P500", "ticker": "433330", "market": "ETF", "asset_type": "ETF", "manager": "신한자산운용"},
    {"name": "KODEX 2차전지산업", "ticker": "305540", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "TIGER 2차전지테마", "ticker": "305720", "market": "ETF", "asset_type": "ETF", "manager": "미래에셋자산운용"},
    {"name": "TIGER 차이나전기차SOLACTIVE", "ticker": "371160", "market": "ETF", "asset_type": "ETF", "manager": "미래에셋자산운용"},
    {"name": "TIGER 미국배당다우존스", "ticker": "458730", "market": "ETF", "asset_type": "ETF", "manager": "미래에셋자산운용"},
    {"name": "ACE 미국배당다우존스", "ticker": "402970", "market": "ETF", "asset_type": "ETF", "manager": "한국투자신탁운용"},
    {"name": "SOL 미국배당다우존스", "ticker": "446720", "market": "ETF", "asset_type": "ETF", "manager": "신한자산운용"},
    {"name": "KODEX 미국나스닥100TR", "ticker": "379810", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "KODEX 레버리지", "ticker": "122630", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "KODEX 인버스", "ticker": "114800", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "KODEX 200선물인버스2X", "ticker": "252670", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "KODEX CD금리액티브(합성)", "ticker": "459580", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "TIGER CD금리투자KIS(합성)", "ticker": "357870", "market": "ETF", "asset_type": "ETF", "manager": "미래에셋자산운용"},
    {"name": "KODEX AI반도체핵심장비", "ticker": "471000", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "TIGER AI반도체핵심공정", "ticker": "470870", "market": "ETF", "asset_type": "ETF", "manager": "미래에셋자산운용"},
    {"name": "TIGER 미국테크TOP10 INDXX", "ticker": "381170", "market": "ETF", "asset_type": "ETF", "manager": "미래에셋자산운용"},
    {"name": "ACE 미국빅테크TOP7 Plus H", "ticker": "465580", "market": "ETF", "asset_type": "ETF", "manager": "한국투자신탁운용"},
    {"name": "KODEX 미국30년국채액티브(H)", "ticker": "462940", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "TIGER 미국30년국채프리미엄액티브(H)", "ticker": "476550", "market": "ETF", "asset_type": "ETF", "manager": "미래에셋자산운용"},
    {"name": "SOL 조선TOP3플러스", "ticker": "466920", "market": "ETF", "asset_type": "ETF", "manager": "신한자산운용"},
    {"name": "KODEX 골드선물(H)", "ticker": "132030", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "KODEX WTI원유선물(H)", "ticker": "261220", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "TIGER 인도Nifty50", "ticker": "453870", "market": "ETF", "asset_type": "ETF", "manager": "미래에셋자산운용"},
    {"name": "KODEX 인도Nifty50", "ticker": "453880", "market": "ETF", "asset_type": "ETF", "manager": "삼성자산운용"},
    {"name": "PLUS 200", "ticker": "105190", "market": "ETF", "asset_type": "ETF", "manager": "한화자산운용"},
    # KOACT (삼성액티브자산운용) 시리즈
    {"name": "KOACT 미국나스닥성장기업액티브", "ticker": "0015B0", "market": "ETF", "asset_type": "ETF", "manager": "삼성액티브자산운용"},
    {"name": "KOACT 미국배당대표성장액티브", "ticker": "462920", "market": "ETF", "asset_type": "ETF", "manager": "삼성액티브자산운용"},
    {"name": "KOACT 테크TOP10인프라액티브", "ticker": "471530", "market": "ETF", "asset_type": "ETF", "manager": "삼성액티브자산운용"},
    {"name": "KOACT 바이오헬스케어액티브", "ticker": "462330", "market": "ETF", "asset_type": "ETF", "manager": "삼성액티브자산운용"},
    {"name": "KOACT Global AI Tech액티브", "ticker": "471540", "market": "ETF", "asset_type": "ETF", "manager": "삼성액티브자산운용"}
]

# ETF 브랜드 한글-영문 Alias 맵핑 사전
BRAND_ALIAS_MAP = {
    "코덱스": "KODEX",
    "타이거": "TIGER",
    "에이스": "ACE",
    "솔": "SOL",
    "라이즈": "RISE",
    "플러스": "PLUS",
    "히어로즈": "HEROES",
    "하나로": "HANARO",
    "킨덱스": "KINDEX",
    "유니콘": "UNICORN",
    "아이엔": "WOORI",
    "코액트": "KOACT"
}


def search_stock_or_etf(query: str, asset_type: str = "ALL") -> List[Dict[str, Any]]:
    """
    사용자의 입력 검색어(종목명, 종목코드, ETF명, 운용사 브랜드명)를 기반으로
    후보 종목/ETF 리스트를 반환합니다.
    """
    if not query or not query.strip():
        return []

    q_raw = query.strip()
    
    # 괄호 포함 입력("KOACT(0015B0)" 또는 "삼성전자(005930)") 정제
    code_in_parentheses = None
    pure_name = q_raw
    code_match = re.search(r'\(([0-9A-Za-z]{6})\)', q_raw)
    if code_match:
        code_in_parentheses = code_match.group(1).upper()
        pure_name = re.sub(r'\([0-9A-Za-z]{6}\)', '', q_raw).strip()

    q = pure_name.upper()
    
    # 한글 브랜드명 치환 처리 (예: "코덱스 200" -> "KODEX 200")
    q_mapped = q
    for kor_brand, eng_brand in BRAND_ALIAS_MAP.items():
        if kor_brand in pure_name:
            q_mapped = pure_name.replace(kor_brand, eng_brand).upper()
            break

    results = []
    target_type = asset_type.upper() if asset_type else "ALL"

    for item in STOCK_ETF_MASTER:
        item_type = item["asset_type"].upper()
        name_upper = item["name"].upper()
        ticker = item["ticker"]
        manager = item["manager"].upper()

        score = 0
        match_type = ""

        # 0. Exact match via extracted parentheses code
        if code_in_parentheses and ticker == code_in_parentheses:
            score = 110
            match_type = "EXACT_TICKER"
        # 1. Exact ticker match
        elif q == ticker or q_raw.upper() == ticker:
            score = 105
            match_type = "EXACT_TICKER"
        # 2. Exact name match
        elif q == name_upper or q_mapped == name_upper or q_raw.upper() == name_upper:
            score = 95
            match_type = "EXACT_NAME"
        # 3. Starts with name match
        elif name_upper.startswith(q) or name_upper.startswith(q_mapped):
            score = 88
            match_type = "STARTS_WITH_NAME"
        # 4. Partial name or ticker match
        elif q in ticker or q in name_upper or q_mapped in name_upper or (manager and (q in manager or q_mapped in manager)):
            score = 75 if (q in name_upper or q_mapped in name_upper) else 60
            match_type = "PARTIAL"

        if score > 0:
            if target_type != "ALL" and target_type == item_type:
                score += 10

            results.append({**item, "match_type": match_type, "score": score})

        if target_type != "ALL" and target_type != item_type:
            # 타겟 자산 유형(STOCK/ETF)이 지정된 경우 비대상은 기본 스킵하되 점수 조정으로 후순위화
            pass

        name_upper = item["name"].upper()
        ticker = item["ticker"]
        manager = item["manager"].upper()

        score = 0
        match_type = ""

        # 1. Exact ticker match
        if q == ticker:
            score = 100
            match_type = "EXACT_TICKER"
        # 2. Exact name match
        elif q == name_upper or q_mapped == name_upper:
            score = 95
            match_type = "EXACT_NAME"
        # 3. Starts with name match
        elif name_upper.startswith(q) or name_upper.startswith(q_mapped):
            score = 88
            match_type = "STARTS_WITH_NAME"
        # 4. Partial name or ticker match
        elif q in ticker or q in name_upper or q_mapped in name_upper or (manager and (q in manager or q_mapped in manager)):
            score = 75 if (q in name_upper or q_mapped in name_upper) else 60
            match_type = "PARTIAL"

        if score > 0:
            # asset_type 필터 가중치 (선택한 모드와 일치하면 +10점)
            if target_type != "ALL" and target_type == item_type:
                score += 10

            results.append({**item, "match_type": match_type, "score": score})

    # 점수 높은 순 정렬
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

def get_stock_by_ticker_or_name(query: str, asset_type: str = "ALL") -> Dict[str, Any]:
    """
    단일 종목이 정확히 식별 가능한지 확인 (없으면 None)
    """
    candidates = search_stock_or_etf(query, asset_type=asset_type)
    if len(candidates) == 1 or (candidates and candidates[0]["score"] >= 90):
        return candidates[0]
    return None

def search_all_stock_or_etf(query: str, asset_type: str = "ALL") -> List[Dict[str, Any]]:
    """
    KOSPI, KOSDAQ 상장종목 전체 및 ETF 전체를 탐색 및 동적 식별합니다.
    1차: STOCK_ETF_MASTER 수록 종목 매칭
    2차: collector.resolve_ticker() 동적 파싱을 통합하여 코스피/코스닥 전 종목 탐색 지원
    """
    if not query or not query.strip():
        return []

    q = query.strip()
    results = search_stock_or_etf(q, asset_type=asset_type)
    seen_tickers = {r["ticker"] for r in results}

    # resolve_ticker 동적 조회를 통해 마스터 데이터베이스에 없는 신규/중소형 상장 종목도 수용
    try:
        from backend.data.collector import resolve_ticker
        live_ticker, live_name = resolve_ticker(q, asset_type_hint=asset_type)
        if live_ticker and live_ticker not in seen_tickers:
            is_etf_name = any(b in live_name.upper() for b in ["ETF", "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "KBSTAR", "ARIRANG", "HANARO"])
            detected_asset_type = "ETF" if is_etf_name else "STOCK"
            market = "ETF" if detected_asset_type == "ETF" else "KOSPI"
            
            score = 90
            if asset_type != "ALL" and asset_type.upper() == detected_asset_type:
                score += 10

            results.append({
                "name": live_name,
                "ticker": live_ticker,
                "market": market,
                "asset_type": detected_asset_type,
                "manager": "자산운용" if detected_asset_type == "ETF" else "",
                "match_type": "DYNAMIC_RESOLVED",
                "score": score
            })
    except Exception:
        pass

    results.sort(key=lambda x: x["score"], reverse=True)
    return results

