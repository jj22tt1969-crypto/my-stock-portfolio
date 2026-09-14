import re
from typing import Dict, Any, Optional

def parse_recommendation_intent(question: str, req_limit: Optional[int] = None) -> Dict[str, Any]:
    """
    LLM 없이 질문 문장으로부터 추천 의도(Intent), 시장 구분(Scope), 투자 기간(Horizon), 요청 개수(Count)를
    결정론적으로 추출하는 Intent Parser
    """
    q_norm = question.strip()
    q_lower = q_norm.lower()

    # 1. 숫자 추출 (예: "5개", "3종목", "10개" 등)
    num_match = re.search(r'(\d+)\s*(?:개|종목|가지)', q_norm)
    if num_match:
        extracted_num = int(num_match.group(1))
    else:
        extracted_num = req_limit if (req_limit is not None and req_limit > 0) else None

    # 2. 키워드 플래그 탐지
    is_etf = any(k in q_lower for k in ["etf", "이티에프", "상장지수"])
    is_short = any(k in q_lower for k in ["단기", "단기매매", "스윙", "단기유망", "단기 유망", "단기 추천"])
    is_mid = any(k in q_lower for k in ["중기", "중장기", "중기추천", "중기 추천"])
    
    is_portfolio = any(k in q_lower for k in ["보유종목", "보유 종목", "포트폴리오", "내 종목", "내 계좌", "보유중인"])
    is_joint_buy = any(k in q_lower for k in ["쌍끌이", "외국인 기관", "외인 기관", "외인과 기관", "외국인과 기관", "외인 기관 동시"])
    is_flow_improving = any(k in q_lower for k in ["수급 개선", "수급이 개선", "수급 좋은", "매집", "외국인 매수", "외인 매수", "기관 매집", "기관이 최근", "수급개선"])
    is_trend_not_overheated = any(k in q_lower for k in ["과열되지 않은", "비과열", "과열 없는", "안정적 상승", "비 과열"])
    is_pullback = any(k in q_lower for k in ["눌림목", "눌림"])

    # 3. Intent 판정 우선순위
    if is_portfolio:
        intent = "PORTFOLIO_SHORT_RANK"
        default_count = 5
        market_scope = "PORTFOLIO"
        horizon = "SHORT"
    elif is_joint_buy:
        intent = "FLOW_JOINT_BUY"
        default_count = 5
        market_scope = "ALL"
        horizon = "SHORT"
    elif is_etf:
        market_scope = "ETF"
        default_count = 3
        if is_short:
            intent = "ETF_SHORT_RECOMMEND"
            horizon = "SHORT"
        else:
            intent = "ETF_MID_RECOMMEND"
            horizon = "MID"
    elif is_pullback:
        intent = "PULLBACK_CANDIDATE"
        default_count = 5
        market_scope = "STOCK"
        horizon = "MID"
    elif is_trend_not_overheated:
        intent = "TREND_NOT_OVERHEATED"
        default_count = 5
        market_scope = "STOCK"
        horizon = "MID"
    elif is_flow_improving:
        intent = "FLOW_IMPROVING"
        default_count = 5
        market_scope = "STOCK"
        horizon = "SHORT"
    elif is_short:
        intent = "STOCK_SHORT_RECOMMEND"
        default_count = 5
        market_scope = "STOCK"
        horizon = "SHORT"
    elif is_mid:
        intent = "STOCK_MID_RECOMMEND"
        default_count = 5
        market_scope = "STOCK"
        horizon = "MID"
    else:
        # 일반 추천 fallback
        if any(k in q_norm for k in ["추천", "찾아", "보여", "알려", "유망"]):
            intent = "STOCK_SHORT_RECOMMEND"
            default_count = 5
            market_scope = "STOCK"
            horizon = "SHORT"
        else:
            intent = "NORMAL_RECOMMENDATION_UNKNOWN"
            default_count = 5
            market_scope = "STOCK"
            horizon = "SHORT"

    # 상한선 제한 (최소 1개, 최대 10개)
    final_count = min(10, max(1, extracted_num if extracted_num is not None else default_count))

    return {
        "intent": intent,
        "market_scope": market_scope,
        "horizon": horizon,
        "requested_count": final_count
    }
