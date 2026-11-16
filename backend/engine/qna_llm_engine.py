import re
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from backend.data.collector import get_stock_flow_data
from backend.engine.decision_engine import analyze_stock_decision
from backend.engine.cross_validation_engine import analyze_cross_indicators, perform_cross_validation
from backend.engine.news_engine import fetch_qna_stock_news
from backend.engine.official_engine import fetch_official_documents, classify_query_intent
from backend.engine.citation_engine import generate_citations
from backend.engine.fundamental_valuation_engine import get_fundamental_shadow_context
from backend.engine.stock_identifier import STOCK_ETF_MASTER
from backend.db import database as db

# F9C: 5분 메모리 TTL 캐시 (종목별 News / DART 수집)
_QNA_NEWS_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_QNA_OFFICIAL_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 300.0  # 5분

def _get_cached_news(ticker: str, name: str, query: str = "") -> Dict[str, Any]:
    key = f"{ticker or name}".strip().upper()
    now = time.time()
    try:
        if key in _QNA_NEWS_CACHE:
            expire_at, data = _QNA_NEWS_CACHE[key]
            if now < expire_at:
                return data
    except Exception:
        pass

    res = fetch_qna_stock_news(ticker=ticker, name=name, query=query)
    try:
        if res.get("status") == "success" and res.get("items"):
            _QNA_NEWS_CACHE[key] = (now + _CACHE_TTL_SECONDS, res)
    except Exception:
        pass
    return res

def _get_cached_official(ticker: str, name: str, query: str = "", asset_type: str = "STOCK", manager: str = "") -> Dict[str, Any]:
    # F10C: 일반 기업공시와 정부/정책 질의가 캐시를 공유하여 오염되지 않도록 official_intent를 stable key에 포함
    official_intent = classify_query_intent(query, asset_type=asset_type)
    key = f"{ticker or name}_{asset_type}_{official_intent}".strip().upper()
    now = time.time()
    try:
        if key in _QNA_OFFICIAL_CACHE:
            expire_at, data = _QNA_OFFICIAL_CACHE[key]
            if now < expire_at:
                return data
    except Exception:
        pass

    res = fetch_official_documents(ticker=ticker, name=name, query=query, asset_type=asset_type, manager=manager)
    try:
        if res.get("status") == "success" and res.get("items"):
            _QNA_OFFICIAL_CACHE[key] = (now + _CACHE_TTL_SECONDS, res)
    except Exception:
        pass
    return res

# F10B-1 / F10B-1R: Q&A Intent Router 상수 및 우선순위 정의
QNA_INTENTS: Tuple[str, ...] = (
    "GENERAL_SUMMARY",
    "DECISION_BUY",
    "DECISION_SELL",
    "DECISION_WATERING",
    "FLOW_GENERAL",
    "FLOW_CONCURRENCY",
    "FLOW_SMART_MONEY",
    "TECH_RSI_RMI",
    "RISK_ANALYSIS",
    "NEWS_DISCLOSURE",
    "FUNDAMENTAL_VALUATION",
)

QNA_INTENT_PRIORITY: Tuple[str, ...] = (
    "DECISION_WATERING",
    "DECISION_BUY",
    "DECISION_SELL",
    "NEWS_DISCLOSURE",
    "TECH_RSI_RMI",
    "FLOW_SMART_MONEY",
    "FLOW_CONCURRENCY",
    "RISK_ANALYSIS",
    "FUNDAMENTAL_VALUATION",
    "FLOW_GENERAL",
    "GENERAL_SUMMARY",
)

# Decision으로 오분류하면 안 되는 수급/기술 복합 용어 (부분문자열 오분류 차단용)
NON_DECISION_COMPOUND_TERMS: Tuple[str, ...] = (
    "과매도", "과매수", "순매수", "순매도", "매수세", "매도세",
    "매수우위", "매도우위", "매수물량", "매도물량", "매수주체", "매도주체",
    "동반 매수", "동반매수", "동반 매도", "동반매도", "쌍끌이 매수", "쌍끌이매수", "쌍끌이 매도", "쌍끌이매도",
)

SUMMARY_REQUEST_KEYWORDS: Tuple[str, ...] = (
    "종합적으로", "종합 분석", "종합분석", "종합 리포트", "종합리포트", "전체적으로", "전반적으로",
)

INTENT_KEYWORD_RULES: Dict[str, Tuple[str, ...]] = {
    "NEWS_DISCLOSURE": (
        "뉴스", "공시", "dart", "보도자료", "수시공시", "사업보고서", "분기보고서", "반기보고서", "실시간 보도", "언론 보도",
    ),
    "TECH_RSI_RMI": (
        "rsi", "rmi", "mfi", "과열", "과매도", "과매수",
        "볼린저", "bollinger", "macd", "스토캐스틱", "stochastic",
        "이평선", "이동평균", "ma5", "ma20", "ma60", "ma120",
        "정배열", "역배열", "골든크로스", "데드크로스", "지지선", "저항선",
        "기술적 상태", "차트 상태", "모멘텀 지표",
    ),
    "FLOW_SMART_MONEY": (
        "smart money", "smartmoney", "스마트머니", "스마트 머니",
        "연기금", "투신", "사모펀드", "사모 수급", "금융투자",
        "기관 세부", "세부 수급", "주체별 수급", "투자자별 수급",
    ),
    "FLOW_CONCURRENCY": (
        "쌍끌이", "동조화", "동조 상태", "동반 순매수", "동반 순매도",
        "동반 매수", "동반 매도", "같이 사고", "같이 사", "같이 팔",
        "함께 사고", "함께 매수", "동시 순매수", "동시 매수",
        "외국인과 기관이 같이", "외인과 기관이 같이",
    ),
    "RISK_ANALYSIS": (
        "위험요인", "위험 요인", "리스크", "위험은", "위험할까",
        "최대 낙폭", "낙폭", "atr", "변동성 위험", "주의할 점", "주의점", "취약점", "반대 신호",
    ),
    "FUNDAMENTAL_VALUATION": (
        "per", "pbr", "roe", "eps", "bps", "dps",
        "재무", "실적", "영업이익", "순이익", "당기순이익", "매출",
        "부채비율", "당좌비율", "이익률", "영업이익률", "순이익률",
        "밸류에이션", "기업가치", "펀더멘털", "펀더멘탈", "흑자", "적자",
    ),
    "FLOW_GENERAL": (
        "수급", "순매수", "순매도", "매수세", "매도세", "ffcs", "fcs", "수급 사이클",
        "외국인 매수", "외국인 매도", "기관 매수", "기관 매도",
        "외인 매수", "외인 매도", "외국인 지분", "외국인 비중",
    ),
}

_INVESTOR_FLOW_PATTERN = re.compile(
    r"(외국인|외인|기관|연기금|개인|투신|사모)[은는이가도의과와랑\s]*(같이\s*|함께\s*|동시\s*|연속\s*|계속\s*|지금\s*|최근\s*)*(순)?(매수|매도|사고|팔고|사나|파나|사\?|팔아\?)"
)

# 금융 질문 의사결정 보조 키워드 매핑 (단순 "매수"/"매도" 단독 포함 금지)
DECISION_QUERY_KEYWORDS = {
    "WATERING": [
        "물타기", "추매", "추가매수", "추가 매수", "평단가 낮",
        "더 사도", "더 살까", "더 사야", "더 사?", "분할 추가",
    ],
    "BUY": [
        "매수해도", "매수할까", "매수해야", "매수 타이밍", "매수타이밍",
        "지금 매수", "신규 매수", "신규매수", "매수 진입", "매수진입",
        "매수 가능", "매수 어때", "진입해도", "진입할까",
        "사도 될까", "사도될까", "사도 되나", "살까", "사야", "사볼까", "사?",
    ],
    "SELL": [
        "매도해도", "매도할까", "매도해야", "매도 타이밍", "매도타이밍",
        "지금 매도", "전량 매도", "매도 가능", "매도 어때",
        "팔아도", "팔까", "팔아야", "팔아?", "익절", "손절",
        "차익실현", "차익 실현", "비중 축소", "비중축소", "처분할까", "정리해야", "정리할까",
    ],
}

# 미래 예측 / 환각 유발 질문 감지 키워드
PREDICTION_QUERY_KEYWORDS = ["확실히", "무조건", "얼마까지", "상향", "상장폐지", "대박", "보장", "내일 오르", "내일 떨어"]


def _sanitize_for_decision_matching(query: str) -> str:
    """
    Decision(BUY/SELL/WATERING) 판정 전 과매도·순매수·순매도·매수세·매도세 및
    외국인/기관 주체 수급 서술어를 제거하여 부분문자열 오분류를 차단합니다.
    """
    sanitized = query
    for term in NON_DECISION_COMPOUND_TERMS:
        sanitized = sanitized.replace(term, " ")
    sanitized = _INVESTOR_FLOW_PATTERN.sub(" ", sanitized)
    return sanitized


def _match_decision_intent(query: str) -> Optional[str]:
    """
    부분문자열 오분류가 제거된 텍스트에서 DECISION_WATERING / DECISION_BUY / DECISION_SELL을 판정합니다.
    """
    sanitized = _sanitize_for_decision_matching(query)

    if any(kw in sanitized for kw in DECISION_QUERY_KEYWORDS["WATERING"]):
        return "DECISION_WATERING"
    if any(kw in sanitized for kw in DECISION_QUERY_KEYWORDS["BUY"]) or re.search(
        r"매수\s*(할|해도|해야|가능|어때|타이밍|시점|검토|\?)", sanitized
    ):
        return "DECISION_BUY"
    if any(kw in sanitized for kw in DECISION_QUERY_KEYWORDS["SELL"]) or re.search(
        r"매도\s*(할|해도|해야|가능|어때|타이밍|시점|검토|\?)", sanitized
    ):
        return "DECISION_SELL"
    return None


def route_qna_intents(query: str) -> Dict[str, Any]:
    """
    F10B-1R: 혼합 질문(Mixed-Query) 지원 Q&A Intent Router.
    - primary_intent 및 secondary_intents를 반환합니다.
    - GENERAL_SUMMARY는 (A) 특정 도메인 지정 없는 종합 요청이거나,
      (B) 3개 이상 복수 도메인을 명시적으로 종합 요청한 경우에만 반환합니다.
    - 사용자가 최종 행동 판단(DECISION_*)을 명시적으로 묻는 경우 DECISION_*를 primary로 배치하고
      함께 언급된 도메인 근거를 secondary_intents로 보존합니다.
    """
    if not query or not str(query).strip():
        return {"primary_intent": "GENERAL_SUMMARY", "secondary_intents": []}

    q_norm = str(query).strip().lower()
    dec_intent = _match_decision_intent(q_norm)

    domain_order = (
        "NEWS_DISCLOSURE",
        "TECH_RSI_RMI",
        "FLOW_SMART_MONEY",
        "FLOW_CONCURRENCY",
        "RISK_ANALYSIS",
        "FUNDAMENTAL_VALUATION",
        "FLOW_GENERAL",
    )

    matched_domains: List[str] = []
    for intent_name in domain_order:
        if intent_name == "FLOW_GENERAL":
            # FLOW_SMART_MONEY 또는 FLOW_CONCURRENCY가 이미 매칭된 경우 단순 '수급' 중복 매칭 방지
            if "FLOW_SMART_MONEY" in matched_domains or "FLOW_CONCURRENCY" in matched_domains:
                specific_flow_kws = tuple(kw for kw in INTENT_KEYWORD_RULES["FLOW_GENERAL"] if kw != "수급")
                if any(kw in q_norm for kw in specific_flow_kws):
                    matched_domains.append("FLOW_GENERAL")
                continue
            if any(kw in q_norm for kw in INTENT_KEYWORD_RULES["FLOW_GENERAL"]) or _INVESTOR_FLOW_PATTERN.search(q_norm):
                matched_domains.append("FLOW_GENERAL")
        else:
            if any(kw in q_norm for kw in INTENT_KEYWORD_RULES[intent_name]):
                matched_domains.append(intent_name)

    # GENERAL_SUMMARY 조건 B: 3개 이상 복수 도메인 + 종합 요청 키워드 (최종 의사결정 질문이 아닌 경우)
    if dec_intent is None and len(matched_domains) >= 3 and any(kw in q_norm for kw in SUMMARY_REQUEST_KEYWORDS):
        return {"primary_intent": "GENERAL_SUMMARY", "secondary_intents": []}

    ordered: List[str] = []
    if dec_intent:
        ordered.append(dec_intent)
    ordered.extend(matched_domains)

    if not ordered:
        return {"primary_intent": "GENERAL_SUMMARY", "secondary_intents": []}

    return {
        "primary_intent": ordered[0],
        "secondary_intents": ordered[1:],
    }


def classify_qna_intent(query: str) -> str:
    """하위 호환용 단일 primary_intent 반환 함수."""
    return route_qna_intents(query)["primary_intent"]


def get_user_portfolio_info(ticker: str, name: str) -> Optional[Dict[str, Any]]:
    """DB 포트폴리오에서 사용자의 해당 종목 보유 현황을 조회합니다."""
    try:
        stock = None
        if ticker:
            stock = db.get_stock_by_ticker(ticker)
        if not stock and name:
            all_stocks = db.get_all_stocks(asset_type="ALL")
            for s in all_stocks:
                if s.get("name") == name:
                    stock = s
                    break
        return stock
    except Exception as e:
        logger.warning(f"[QnA Engine] get_user_portfolio_info fail-safe: {e}")
        return None


def classify_decision_query(query: str) -> Optional[str]:
    """
    기존 action_opinion 호환용 의사결정 의도(BUY, SELL, WATERING) 반환 함수.
    route_qna_intents의 primary_intent를 사용하여 과매도/순매수/순매도 오분류를 차단합니다.
    """
    qna_intent = classify_qna_intent(query)
    if qna_intent == "DECISION_BUY":
        return "BUY"
    elif qna_intent == "DECISION_SELL":
        return "SELL"
    elif qna_intent == "DECISION_WATERING":
        return "WATERING"
    return None


def map_intent_data_sources(
    qna_intent: str,
    flow_data: Dict[str, Any],
    flow_info: Dict[str, Any],
    tech_info: Dict[str, Any],
    timing_info: Dict[str, Any],
    decision_res: Dict[str, Any],
    cross_analysis: Dict[str, Any],
    primary_fund: Dict[str, Any],
    news_items: List[Dict[str, Any]],
    official_items: List[Dict[str, Any]],
    user_stock_info: Dict[str, Any],
    secondary_intents: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    F10B-1 / F10B-1R: primary_intent 및 secondary_intents가 참조할 기존 엔진 데이터 Source Mapping.
    - 신규 지표/임계치(threshold) 계산 절대 금지 (기존 Engine 계산값만 참조)
    """
    shadow_ctx = primary_fund.get("shadow_context", {}) if isinstance(primary_fund, dict) else {}
    val_ctx = shadow_ctx.get("valuation_context", {}) if isinstance(shadow_ctx, dict) else {}
    prof_ctx = shadow_ctx.get("profitability_context", {}) if isinstance(shadow_ctx, dict) else {}
    earn_ctx = shadow_ctx.get("earnings_context", {}) if isinstance(shadow_ctx, dict) else {}
    qual_ctx = shadow_ctx.get("quality_shadow_score_card", {}) if isinstance(shadow_ctx, dict) else {}
    risk_info = tech_info.get("risk_analysis", {}) if isinstance(tech_info, dict) else {}
    inv_breakdown = flow_data.get("investor_breakdown", {}) if isinstance(flow_data, dict) else {}

    source_Registry: Dict[str, Dict[str, Any]] = {
        "FLOW_GENERAL": {
            "periods_analysis": flow_info.get("periods_analysis"),
            "foreign_direction": flow_info.get("foreign_direction"),
            "institution_direction": flow_info.get("institution_direction"),
            "flow_state": flow_info.get("flow_state"),
            "flow_reasons": flow_info.get("flow_reasons"),
            "flow_risks": flow_info.get("flow_risks"),
            "cycle_stage": flow_info.get("cycle_stage"),
            "ffcs_score": flow_info.get("ffcs_score"),
        },
        "FLOW_CONCURRENCY": {
            "concurrency": flow_info.get("concurrency"),
            "foreign_direction": flow_info.get("foreign_direction"),
            "institution_direction": flow_info.get("institution_direction"),
            "periods_analysis": flow_info.get("periods_analysis"),
        },
        "FLOW_SMART_MONEY": {
            "investor_breakdown": inv_breakdown,
            "divergence": flow_info.get("divergence"),
            "key_reasons": flow_info.get("key_reasons"),
            "periods_analysis": flow_info.get("periods_analysis"),
        },
        "TECH_RSI_RMI": {
            "rsi": tech_info.get("rsi"),
            "rmi": tech_info.get("rmi"),
            "mfi": tech_info.get("mfi"),
            "ma5": tech_info.get("ma5"),
            "ma20": tech_info.get("ma20"),
            "ma60": tech_info.get("ma60"),
            "ma120": tech_info.get("ma120"),
            "is_aligned_bullish": tech_info.get("is_aligned_bullish"),
            "is_aligned_bearish": tech_info.get("is_aligned_bearish"),
            "bollinger": timing_info.get("bollinger_bands"),
            "macd": tech_info.get("macd"),
            "stochastic_slow": timing_info.get("stochastic_slow"),
            "support_level": tech_info.get("support_level"),
            "resistance_level": tech_info.get("resistance_level"),
            "dist_to_support": tech_info.get("dist_to_support"),
            "dist_to_resistance": tech_info.get("dist_to_resistance"),
            "trend_analysis": tech_info.get("trend_analysis"),
            "risk_analysis": risk_info,
        },
        "RISK_ANALYSIS": {
            "flow_risks": flow_info.get("flow_risks"),
            "atr_14": risk_info.get("atr_14"),
            "atr_pct": risk_info.get("atr_pct"),
            "drawdown_from_high_pct": risk_info.get("drawdown_from_high_pct"),
            "risk_state": risk_info.get("risk_state"),
            "risk_reasons": risk_info.get("risk_reasons"),
            "trend_filter": decision_res.get("trend_filter"),
            "fundamental_flags": {
                "has_deficit": primary_fund.get("has_deficit"),
                "has_loss": primary_fund.get("has_loss"),
                "has_negative_roe": primary_fund.get("has_negative_roe"),
                "earnings_status": earn_ctx.get("status"),
                "roe": primary_fund.get("roe"),
            },
            "news_items": news_items,
            "official_items": official_items,
        },
        "FUNDAMENTAL_VALUATION": {
            "fundamental_shadow_context": shadow_ctx,
            "per": val_ctx.get("per"),
            "per_status": val_ctx.get("per_status"),
            "pbr": val_ctx.get("pbr"),
            "pbr_status": val_ctx.get("pbr_status"),
            "roe": prof_ctx.get("roe"),
            "own_history": val_ctx.get("own_history"),
            "quality_context": qual_ctx,
        },
        "NEWS_DISCLOSURE": {
            "news_items": news_items,
            "official_items": official_items,
        },
    }

    # GENERAL_SUMMARY 및 DECISION 계열은 기존 종합 Context 재사용
    default_context = {
        "decision": decision_res,
        "flow_analysis": flow_info,
        "technical_analysis": tech_info,
        "timing_analysis": timing_info,
        "cross_analysis": cross_analysis,
        "fundamental_grounding": primary_fund,
        "news_items": news_items,
        "official_items": official_items,
        "app_user_data": user_stock_info,
    }

    sec_list = list(secondary_intents or [])
    return {
        "intent": qna_intent,
        "primary_intent": qna_intent,
        "secondary_intents": sec_list,
        "primary_sources": source_Registry.get(qna_intent, default_context),
        "secondary_sources": {
            sec: source_Registry.get(sec, default_context) for sec in sec_list
        },
    }

def determine_action_opinion(intent: Optional[str], decision_data: Dict[str, Any], user_stock: Optional[Dict[str, Any]] = None) -> str:
    """
    기존 투자판단(TODAY ACTION)을 변경하지 않고 근거 중심 '의사결정 보조 의견'을 제시합니다.
    """
    decision = decision_data.get("decision", "HOLD")
    buy_score = decision_data.get("buy_score", 0)
    sell_score = decision_data.get("sell_score", 0)
    water_score = decision_data.get("watering_score", 0)

    return_rate = 0.0
    if user_stock and "return_rate" in user_stock:
        return_rate = user_stock["return_rate"]

    if intent == "BUY":
        if decision in ["BUY", "STRONG_BUY"] or buy_score >= 60:
            return "현재 데이터상 매수 검토 우세 (지지선 및 수급 개선 확인)"
        elif buy_score >= 40:
            return "현재 데이터상 분할 접근 검토 우세"
        else:
            return "현재 데이터상 관망 우세 (수급 모멘텀 확인 필요)"

    elif intent == "SELL":
        if return_rate > 20.0 and sell_score >= 40:
            return "현재 데이터상 일부 익절 검토 우세 (수익 구간 리스크 관리)"
        elif decision in ["SELL", "STRONG_SELL"] or sell_score >= 60:
            return "현재 데이터상 매도/익절 검토 우세 (저항선 및 수급 경계)"
        elif sell_score >= 40:
            return "현재 데이터상 분할 매도 검토 우세"
        else:
            return "현재 데이터상 보유 및 관망 우세"

    elif intent == "WATERING":
        if return_rate < -10.0 and (water_score >= 40 or decision == "WATERING"):
            return "현재 데이터상 분할 추가매수 검토 가능"
        elif water_score >= 50 or decision == "WATERING":
            return "현재 데이터상 분할 추가매수 검토 가능"
        else:
            return "현재 데이터상 관망 우세 (추가 진입 전 지지 확인)"

    if decision in ["BUY", "STRONG_BUY"]:
        return "현재 근거 데이터상 긍정 요인 우세 (매수 검토)"
    elif decision == "WATERING":
        return "현재 근거 데이터상 분할매수 검토 우세"
    elif decision in ["SELL", "STRONG_SELL"]:
        return "현재 근거 데이터상 매도/익절 검토 우세"
    
    return "현재 근거 데이터상 중립/관망 우세"


def format_fundamental_grounding(
    ticker: str,
    name: str,
    asset_type: str = "STOCK",
    label_prefix: str = ""
) -> Dict[str, Any]:
    """
    F8C-2: Q&A 전용 기업 재무 및 기업가치 Context Grounding 팩트 포맷터.
    - get_fundamental_shadow_context 단일 위임 (중복 계산 금지)
    - 외부 API 호출 0건 (O(1) 캐시)
    - '저평가/고평가/투자점수' 등 주관적 단어 사용 금지
    - '최근 확정연도' 시점 명시 (현재 PER과 혼동 방지)
    - Fail-safe: 오류 발생 시 재무 context만 skip하고 전체 Q&A 정상 진행
    """
    try:
        shadow_ctx = get_fundamental_shadow_context(ticker or name)
        data_state = shadow_ctx.get("data_state", "NO_FINANCE_DATA")
        resolved_asset_type = shadow_ctx.get("asset_type", asset_type)
        resolved_name = shadow_ctx.get("name", name or ticker)

        facts: List[str] = []
        analysis_paragraphs: List[str] = []
        uncertainty_items: List[str] = []

        # 1. ETF 처리
        if resolved_asset_type == "ETF" or data_state == "NOT_APPLICABLE":
            facts.append("[💡 ETF 자산 특성] ETF는 기업 고유 재무평가 대상이 아닙니다.")
            analysis_paragraphs.append("• [ETF 자산 특성]: ETF는 개별 기업 재무제표 대상이 아니므로, 수급 흐름 및 편입 섹터 지수를 중심으로 판단합니다.")
            uncertainty_items.append("ETF는 기업 고유 재무평가 대상이 아닙니다.")
            return {
                "facts": facts,
                "analysis_paragraphs": analysis_paragraphs,
                "uncertainty_items": uncertainty_items,
                "shadow_context": shadow_ctx,
                "has_deficit": False,
                "is_profitable": False,
                "name": resolved_name,
                "fiscal_period": None,
                "e_desc": "ETF 미해당",
                "quality_score": None
            }

        # 2. NO_FINANCE_DATA 처리
        if data_state != "SUCCESS":
            facts.append("[⚠️ 재무 데이터 안내] 재무 데이터 미제공으로 기업가치 비교 제한")
            analysis_paragraphs.append("• [재무 미제공 안내]: 스냅샷 재무제표가 미제공된 종목으로, 기업가치 배수 비교가 제한되며 수급 및 공시를 우선 참고합니다.")
            uncertainty_items.append("재무 데이터 미제공으로 기업가치 비교 제한")
            return {
                "facts": facts,
                "analysis_paragraphs": analysis_paragraphs,
                "uncertainty_items": uncertainty_items,
                "shadow_context": shadow_ctx,
                "has_deficit": False,
                "is_profitable": False,
                "name": resolved_name,
                "fiscal_period": None,
                "e_desc": "재무 미제공",
                "quality_score": None
            }

        # 3. STOCK & SUCCESS 정상 처리
        earnings = shadow_ctx.get("earnings_context", {})
        prof = shadow_ctx.get("profitability_context", {})
        val = shadow_ctx.get("valuation_context", {})
        own_hist = val.get("own_history", {})
        per_h = own_hist.get("per_history", {})
        pbr_h = own_hist.get("pbr_history", {})
        roe_h = own_hist.get("roe_history", {})
        quality_card = shadow_ctx.get("quality_shadow_score_card", {})

        fiscal_period = earnings.get("fiscal_period") or "최근 확정연도"
        e_status = earnings.get("status", "UNKNOWN")
        if e_status == "PROFITABLE":
            e_desc = "영업이익 및 순이익 흑자"
        elif e_status == "OPERATING_LOSS":
            e_desc = "영업적자"
        elif e_status == "NET_LOSS":
            e_desc = "당기순손실"
        else:
            e_desc = "실적 미확인"

        rev = earnings.get("revenue")
        op = earnings.get("operating_profit")
        np_val = earnings.get("net_profit")
        rev_str = f"매출 {rev:,.0f}억원" if rev is not None else "매출 결측"
        op_str = f"영업이익 {op:,.0f}억원" if op is not None else "영업이익 결측"
        np_str = f"당기순이익 {np_val:,.0f}억원" if np_val is not None else "당기순이익 결측"

        roe = prof.get("roe")
        roe_str = f"ROE {roe:.2f}%" if roe is not None else "ROE 결측"

        op_m = prof.get("operating_margin")
        np_m = prof.get("net_margin")
        margin_parts = []
        if op_m is not None:
            margin_parts.append(f"영업이익률 {op_m:.1f}%")
        if np_m is not None:
            margin_parts.append(f"순이익률 {np_m:.1f}%")
        margin_str = " / ".join(margin_parts) if margin_parts else "이익률 결측"

        q_score = quality_card.get("quality_shadow_score")
        q_avail = quality_card.get("quality_shadow_score_available")
        if q_avail and q_score is not None:
            score_str = f"재무품질 참고점수: {q_score}점/100점"
        else:
            score_str = "재무품질 참고점수: 산출 제외 (적자 또는 결측)"

        pfx = f"[{label_prefix}] " if label_prefix else ""

        # ① [기업 재무] Fact 생성
        fact_1 = (
            f"[📊 기업 재무] {pfx}최근 확정 결산: {fiscal_period} | 실적 상태: {e_desc} | "
            f"{rev_str} | {op_str} | {np_str} | {roe_str} | {margin_str} | {score_str} "
            f"[출처: DART·네이버 스냅샷 / 상태: 정상]"
        )
        facts.append(fact_1)

        # ② [기업가치 Context] Fact 생성 (F8C-1 Own-History Grounding)
        per_val = val.get("per")
        pbr_val = val.get("pbr")
        per_status = val.get("per_status")

        if per_status == "NON_POSITIVE_PER" or per_val is None or per_val <= 0:
            per_str = "최근 확정연도 PER: 적자/비양수 PER로 PER 비교 부적합"
        else:
            per_str = f"최근 확정연도 PER: {per_val:.2f}배"

        pbr_str = f"최근 확정연도 PBR: {pbr_val:.2f}배" if pbr_val is not None else "최근 확정연도 PBR: 결측"

        # PER Own-History 표현 (중복 괄호 문구 제거)
        if per_h.get("history_available"):
            p_diff = per_h.get("vs_prior_median_pct")
            p_med = per_h.get("prior_median")
            p_pos = per_h.get("position")
            if p_pos == "BELOW_PRIOR_MEDIAN":
                per_hist_str = f"이전 확정연도 양수 PER 중앙값({p_med:.2f}배) 대비 {abs(p_diff):.1f}% 낮은 위치"
            elif p_pos == "ABOVE_PRIOR_MEDIAN":
                per_hist_str = f"이전 확정연도 양수 PER 중앙값({p_med:.2f}배) 대비 {abs(p_diff):.1f}% 높은 위치"
            else:
                per_hist_str = f"이전 확정연도 양수 PER 중앙값({p_med:.2f}배) 대비 유사한 위치 ({p_diff:+.1f}%)"
        else:
            per_hist_str = "PER 과거 중앙값 비교: 과거 2개년 이상 양수 Actual 지표 부재로 비교 부적합"

        # PBR Own-History 표현 (중복 괄호 문구 제거)
        if pbr_h.get("history_available"):
            b_diff = pbr_h.get("vs_prior_median_pct")
            b_med = pbr_h.get("prior_median")
            b_pos = pbr_h.get("position")
            if b_pos == "BELOW_PRIOR_MEDIAN":
                pbr_hist_str = f"PBR 과거 중앙값({b_med:.2f}배) 대비 {abs(b_diff):.1f}% 낮은 위치"
            elif b_pos == "ABOVE_PRIOR_MEDIAN":
                pbr_hist_str = f"PBR 과거 중앙값({b_med:.2f}배) 대비 {abs(b_diff):.1f}% 높은 위치"
            else:
                pbr_hist_str = f"PBR 과거 중앙값({b_med:.2f}배) 대비 유사한 위치 ({b_diff:+.1f}%)"
        else:
            pbr_hist_str = "PBR 과거 중앙값 비교: 과거 2개년 이상 양수 Actual 지표 부재로 비교 부적합"

        # ROE Direction 표현 (Fact 1의 'ROE 10.85%' 수치 중복 방지)
        r_dir = roe_h.get("direction")
        r_chg = roe_h.get("roe_change_pct_point")
        if r_dir == "IMPROVING":
            roe_dir_str = f"수익성(ROE) 방향: 직전 결산 대비 {r_chg:+0.2f}%p 개선(IMPROVING)"
        elif r_dir == "DECLINING":
            roe_dir_str = f"수익성(ROE) 방향: 직전 결산 대비 {r_chg:+0.2f}%p 둔화(DECLINING)"
        elif r_dir == "FLAT":
            roe_dir_str = f"수익성(ROE) 방향: 직전 결산 대비 변동 없음(FLAT)"
        else:
            roe_dir_str = "수익성(ROE) 방향: 비교 불가"

        # ② [기업가치 Context] Fact 생성: fact_1에 이미 있는 roe_str 중복 제거
        fact_2 = (
            f"[📈 기업가치 Context] {pfx}{per_str} | {pbr_str} | "
            f"{per_hist_str} | {pbr_hist_str} | {roe_dir_str} "
            f"[출처: QUANT Own-History 엔진 / 상태: 정상]"
        )
        facts.append(fact_2)

        # AI 해석 문단 (F10B-2: Facts 숫자 단순 재복사 전면 배제, 정성적 상태/방향성 해석만 서술)
        if r_dir == "IMPROVING":
            roe_eval = "수익성(ROE)이 직전 결산 대비 개선되는 흐름"
        elif r_dir == "DECLINING":
            roe_eval = "수익성(ROE)이 직전 결산 대비 다소 둔화되는 흐름"
        else:
            roe_eval = "수익성(ROE)이 직전 결산과 유사한 수준을 유지"

        per_pos_eval = ""
        if per_h.get("history_available"):
            if per_h.get("position") == "BELOW_PRIOR_MEDIAN":
                per_pos_eval = "과거 자체 중앙값 대비 밸류에이션 부담이 완화된 구간"
            elif per_h.get("position") == "ABOVE_PRIOR_MEDIAN":
                per_pos_eval = "과거 자체 중앙값 대비 밸류에이션 프리미엄이 반영된 구간"
            else:
                per_pos_eval = "과거 자체 중앙값과 유사한 밸류에이션 구간"
        else:
            per_pos_eval = "과거 배수 비교 표본 부족으로 밸류에이션 위치 판단 제한"

        analysis_paragraphs.append(
            f"• [재무품질 및 기업가치 팩트 진단]: {resolved_name}의 최근 확정 결산 실적은 {e_desc} 기조이며, "
            f"{roe_eval}을 나타내고 있습니다. 자체 과거 멀티플 추이 관점에서 {per_pos_eval}에 위치하여 "
            "재무 건전성은 양호하나, 업종별 적정가치 단정은 배제합니다."
        )

        has_loss = (e_status in ["OPERATING_LOSS", "NET_LOSS"])
        has_negative_roe = (roe is not None and roe < 0)
        has_deficit = has_loss or has_negative_roe
        is_profitable = (e_status == "PROFITABLE") and not has_deficit

        return {
            "facts": facts,
            "analysis_paragraphs": analysis_paragraphs,
            "uncertainty_items": uncertainty_items,
            "shadow_context": shadow_ctx,
            "has_deficit": has_deficit,
            "has_loss": has_loss,
            "has_negative_roe": has_negative_roe,
            "roe": roe,
            "is_profitable": is_profitable,
            "name": resolved_name,
            "fiscal_period": fiscal_period,
            "e_desc": e_desc,
            "quality_score": q_score
        }
    except Exception as e:
        logger.warning(f"[QnA Engine] format_fundamental_grounding fail-safe: {e}")
        pfx = f"[{label_prefix}] " if label_prefix else ""
        return {
            "facts": [f"[📊 기업 재무] {pfx}기업 재무 Context 조회 생략 (스냅샷 미제공 또는 일시적 오류) [상태: 미확인]"],
            "analysis_paragraphs": ["• [재무 안내]: 기업 재무 데이터가 미제공되었거나 확인 불가하여 수급/기술적 지표를 우선 참조합니다."],
            "uncertainty_items": ["재무 데이터 확인 불가로 기업가치 분석 제외"],
            "shadow_context": {},
            "has_deficit": False,
            "has_loss": False,
            "has_negative_roe": False,
            "roe": None,
            "is_profitable": False,
            "name": name or ticker,
            "fiscal_period": None,
            "e_desc": "재무 미제공",
            "quality_score": None
        }


def detect_comparison_targets(
    query: str,
    current_target_name: str,
    current_target_ticker: str
) -> List[Tuple[str, str]]:
    """
    쿼리 텍스트 내에서 현재 주 타겟 외에 언급된 비교 대상 종목(최대 1개 추가)을 식별합니다.
    - 비교 의도 키워드가 없으면 4,000+ 종목 전수 스캔 생략 (Short-circuit 최적화)
    """
    targets: List[Tuple[str, str]] = []
    if not query or len(query.strip()) < 2:
        return targets

    # 비교 키워드가 없으면 전체 유니버스 탐색 건너뜀 (단일종목 질의 성능 보호)
    comparison_keywords = ["vs", "VS", "비교", "대비", "와 ", "과 ", " vs ", " VS "]
    if not any(kw in query for kw in comparison_keywords):
        return targets

    for item in STOCK_ETF_MASTER:
        m_name = item.get("name", "")
        m_tick = item.get("ticker", "")
        if not m_name or len(m_name) < 2:
            continue
        if m_name == current_target_name or m_tick == current_target_ticker:
            continue
        if m_name in query:
            targets.append((m_tick, m_name))
            if len(targets) >= 1:
                break
    return targets


def _format_flow_krw(amount: Any) -> str:
    """
    원 단위 수급 금액을 억원 단위(+1,234억 / -567억)로 포맷팅합니다.
    """
    try:
        if amount is None:
            return "0억"
        val = float(amount)
        if abs(val) >= 1_000_000:
            val_in_100m = val / 100_000_000.0
        else:
            val_in_100m = val
        return f"{val_in_100m:+,.0f}억"
    except Exception:
        return "0억"


def _build_intent_aware_facts(
    primary_intent: str,
    secondary_intents: List[str],
    current_time_str: str,
    has_user_stock: bool,
    user_stock_info: Dict[str, Any],
    has_flow_data: bool,
    flow_info: Dict[str, Any],
    tech_info: Dict[str, Any],
    timing_info: Dict[str, Any],
    decision_res: Dict[str, Any],
    cross_analysis: Dict[str, Any],
    primary_fund: Dict[str, Any],
    comp_funds: List[Dict[str, Any]],
    official_items: List[Dict[str, Any]],
    news_items: List[Dict[str, Any]],
    action_opinion: str,
    name: str,
    ticker: str,
) -> List[str]:
    """
    F10B-2: 질문 Intent에 따라 핵심 Fact의 우선순위를 재배치하고 세부 Fact를 생성합니다.
    """
    # 1. 공통 보유 팩트
    if has_user_stock:
        p_sign = "+" if user_stock_info.get("profit_loss", 0) >= 0 else ""
        user_fact = (
            f"[📱 앱 보유 데이터] {user_stock_info.get('name', name)}({user_stock_info.get('ticker', ticker)}) "
            f"평단가 {user_stock_info.get('avg_price', 0):,}원 | 수량 {user_stock_info.get('quantity', 0):,}주 | "
            f"손익 {p_sign}{user_stock_info.get('profit_loss', 0):,}원 ({p_sign}{user_stock_info.get('return_rate', 0.0):.2f}%) "
            f"[기준일시: {current_time_str} / 출처: 사용자 포트폴리오 DB / 상태: 정상]"
        )
    else:
        user_fact = (
            f"[📱 앱 보유 데이터] {name or ticker}: 현재 해당 보유 포트폴리오 데이터를 사용할 수 없습니다. (미보유 종목) "
            f"[기준일시: {current_time_str} / 출처: 포트폴리오 DB / 상태: 미확인]"
        )

    # 2. 수급 및 기술 종합 코어 팩트
    latest_close = tech_info.get("latest_close", 0)
    ffcs_score = flow_info.get("ffcs_score", 50.0)
    today_action = decision_res.get("decision", "HOLD")
    rsi_val = tech_info.get("rsi", 50.0)
    rmi_val = tech_info.get("rmi", 50.0)

    flow_core_fact = (
        f"[📊 앱 퀀트 수급 데이터] 종가: {latest_close:,}원 | TODAY ACTION: {today_action} | "
        f"FFCS: {ffcs_score}점 | RSI: {rsi_val} | RMI: {rmi_val} "
        f"[기준일시: {current_time_str} / 출처: QUANT AI 엔진 / 상태: 정상]"
    )

    # 3. 교차 분석 팩트
    status_lbl = cross_analysis.get("status_label", "중립") if cross_analysis else "중립"
    cross_fact = (
        f"[🔮 지표 교차 분석 (Cross Analysis)] 종합 진단: {status_lbl} "
        f"[기준일시: {current_time_str} / 출처: Cross Validation Engine / 상태: 정상]"
    )

    # 4. 수급 세부 팩트 (FLOW_GENERAL)
    periods_analysis = flow_info.get("periods_analysis", {})
    p_foreign = periods_analysis.get("foreign", {})
    p_inst = periods_analysis.get("institution", {})
    f5_net = p_foreign.get("5d", {}).get("net_buy", 0)
    i5_net = p_inst.get("5d", {}).get("net_buy", 0)
    f5_str = _format_flow_krw(f5_net)
    i5_str = _format_flow_krw(i5_net)
    f20_net = p_foreign.get("20d", {}).get("net_buy", 0)
    i20_net = p_inst.get("20d", {}).get("net_buy", 0)
    f_dir = flow_info.get("foreign_direction", "중립")
    i_dir = flow_info.get("institution_direction", "중립")
    cycle_stage = flow_info.get("cycle_stage", "중립")
    flow_state = flow_info.get("flow_state", "NEUTRAL")

    f5_str = _format_flow_krw(f5_net)
    i5_str = _format_flow_krw(i5_net)
    f20_str = _format_flow_krw(f20_net)
    i20_str = _format_flow_krw(i20_net)

    flow_detail_fact = (
        f"[🌊 수급 사이클 및 매수 주체] FFCS: {ffcs_score}점 | 사이클: {cycle_stage} | 수급 상태: {flow_state} | "
        f"외국인 방향: {f_dir} (5일: {f5_str} / 20일: {f20_str}) | "
        f"기관 방향: {i_dir} (5일: {i5_str} / 20일: {i20_str}) "
        f"[출처: QUANT 수급분석엔진 / 상태: 정상]"
    )

    # 5. 동조화 팩트 (FLOW_CONCURRENCY)
    conc_info = flow_info.get("concurrency", {})
    c_status = conc_info.get("status", "중립")
    c_desc = conc_info.get("description", "동조화 판단 보류")
    concurrency_fact = (
        f"[🤝 외국인·기관 동조화 (Concurrency)] 동조 상태: {c_status} | "
        f"세부 진단: {c_desc} | 5일 순매수: 외국인 {f5_str} / 기관 {i5_str} "
        f"[출처: QUANT 동조화엔진 / 상태: 정상]"
    )

    # 6. 스마트머니 팩트 (FLOW_SMART_MONEY)
    smart_money_fact = (
        f"[💼 스마트머니 및 주체별 수급] 5일 순매수: 외국인({f5_str}) / 기관({i5_str}) | "
        f"20일 누적: 외국인({f20_str}) / 기관({i20_str}) "
        f"[출처: QUANT 스마트머니 엔진 / 상태: 정상]"
    )

    # 7. 기술 지표 세부 팩트 (TECH_RSI_RMI)
    ma5 = tech_info.get("ma5", 0)
    ma20 = tech_info.get("ma20", 0)
    ma60 = tech_info.get("ma60", 0)
    mfi_val = tech_info.get("mfi", 50.0)
    ma_align = "단기 정배열" if (ma5 >= ma20 >= ma60) else ("단기 역배열" if (ma5 <= ma20 <= ma60) else "이평선 혼조")
    sup = tech_info.get("support", {}).get("price")
    res = tech_info.get("resistance", {}).get("price")
    sup_res_str = f"지지선: {sup:,}원 / 저항선: {res:,}원" if (sup and res) else "지지·저항선 산출 대기"

    tech_detail_fact = (
        f"[📈 기술적 모멘텀 및 지표] RSI(14): {rsi_val} | RMI: {rmi_val} | MFI: {mfi_val} | "
        f"이동평균: {ma_align} (MA5: {ma5:,}원 / MA20: {ma20:,}원 / MA60: {ma60:,}원) | {sup_res_str} "
        f"[출처: QUANT 기술분석엔진 / 상태: 정상]"
    )

    # 8. 리스크 팩트 (RISK_ANALYSIS)
    risk_res = tech_info.get("risk_analysis", {})
    atr_14 = risk_res.get("atr_14", 0)
    atr_pct = risk_res.get("atr_pct", 0.0)
    mdd = risk_res.get("drawdown_from_high_pct", 0.0)
    risk_st = risk_res.get("risk_state", "NORMAL")
    trend_f = decision_res.get("trend_filter", {}).get("triggered", False)

    risk_fact = (
        f"[⚠️ 리스크 및 변동성 지표] 변동성(ATR): {atr_14:,}원 ({atr_pct:.1f}%) | "
        f"고점 대비 낙폭: {mdd:.1f}% | 리스크 상태: {risk_st} | "
        f"추세역행 필터: {'작동(추가매수 억제)' if trend_f else '미작동'} "
        f"[출처: QUANT 리스크관리엔진 / 상태: 정상]"
    )

    # 9. 의사결정 팩트 (DECISION_*)
    b_sc = decision_res.get("buy_score", 0)
    s_sc = decision_res.get("sell_score", 0)
    w_sc = decision_res.get("watering_score", 0)
    decision_fact = (
        f"[🎯 종합 의사결정 판단] TODAY ACTION: {today_action} | 보조의견: {action_opinion} | "
        f"Buy Score: {b_sc}점 | Sell Score: {s_sc}점 | Watering Score: {w_sc}점 "
        f"[출처: QUANT Decision Engine / 상태: 정상]"
    )

    # 10. 뉴스 및 공시 팩트 (F10B-2 News Guard: 0건 시 근거 부족 명시)
    news_facts: List[str] = []
    for off in official_items[:2]:
        news_facts.append(f"[🌐 공시/보도자료] [{off['institution']}] {off['title']} ({off['pub_date']}) [출처: 공식 DART/정부기관 / 상태: 정상]")
    for nw in news_items[:2]:
        news_facts.append(f"[🌐 실시간 뉴스] [{nw['source']}] {nw['title']} ({nw['pub_date']}) [출처: 실시간 금융뉴스 / 상태: 정상]")
    if not news_facts:
        news_facts.append(
            f"[🌐 공시 및 실시간 뉴스] 최근 수집된 관련 뉴스 및 공시가 없어 근거가 부족합니다. "
            f"[기준일시: {current_time_str} / 출처: DART 및 뉴스검색 / 상태: 자료부족]"
        )

    # 11. 펀더멘털 팩트
    fund_facts = primary_fund.get("facts", [])
    comp_fund_facts = [f for c in comp_funds for f in c.get("facts", [])]

    # Primary Intent별 우선순위 순서 조립
    ordered_facts: List[str] = []

    if primary_intent == "FLOW_GENERAL":
        ordered_facts = [flow_detail_fact, flow_core_fact, cross_fact] + fund_facts + [tech_detail_fact, user_fact] + news_facts
    elif primary_intent == "FLOW_CONCURRENCY":
        ordered_facts = [concurrency_fact, flow_detail_fact, flow_core_fact, cross_fact, tech_detail_fact] + fund_facts + news_facts
    elif primary_intent == "FLOW_SMART_MONEY":
        ordered_facts = [smart_money_fact, flow_detail_fact, flow_core_fact, cross_fact, tech_detail_fact] + fund_facts + news_facts
    elif primary_intent == "TECH_RSI_RMI":
        ordered_facts = [tech_detail_fact, flow_core_fact, cross_fact, flow_detail_fact] + fund_facts + [user_fact] + news_facts
    elif primary_intent == "RISK_ANALYSIS":
        ordered_facts = [risk_fact, cross_fact, flow_core_fact] + fund_facts + [tech_detail_fact] + news_facts
    elif primary_intent == "FUNDAMENTAL_VALUATION":
        ordered_facts = fund_facts + [flow_core_fact, cross_fact, tech_detail_fact, flow_detail_fact] + news_facts
    elif primary_intent == "NEWS_DISCLOSURE":
        ordered_facts = news_facts + [flow_core_fact, cross_fact] + fund_facts + [tech_detail_fact]
    elif primary_intent in ("DECISION_BUY", "DECISION_SELL", "DECISION_WATERING"):
        ordered_facts = [decision_fact, flow_core_fact, cross_fact, flow_detail_fact, tech_detail_fact] + fund_facts + [risk_fact] + news_facts
    else:  # GENERAL_SUMMARY 및 기타
        ordered_facts = [user_fact, flow_core_fact, cross_fact] + fund_facts + news_facts

    if comp_fund_facts:
        ordered_facts.extend(comp_fund_facts)

    # 중복 팩트 안전 제거 (순서 보존)
    seen = set()
    result: List[str] = []
    for f in ordered_facts:
        if f not in seen:
            seen.add(f)
            result.append(f)

    return result


def _build_intent_aware_summary(
    primary_intent: str,
    secondary_intents: List[str],
    name: str,
    ticker: str,
    has_user_stock: bool,
    user_stock_info: Dict[str, Any],
    has_flow_data: bool,
    flow_info: Dict[str, Any],
    tech_info: Dict[str, Any],
    decision_res: Dict[str, Any],
    cross_analysis: Dict[str, Any],
    primary_fund: Dict[str, Any],
    official_items: List[Dict[str, Any]],
    news_items: List[Dict[str, Any]],
    action_opinion: str,
    citations: List[Dict[str, Any]],
    cross_val: Dict[str, Any],
    query_intent: Optional[str] = None,
) -> str:
    """
    F10B-2: 질문 Intent에 맞추어 Executive Summary를
    A. 직접 답변, B. 핵심 이유 1~3개, C. 보조/상충 신호 구조로 조립합니다.
    """
    inline_citations = "".join([f" [{idx+1}]" for idx in range(min(len(citations), 3))])
    conflict_prefix = "⚠️ [자료 간 내용에 차이가 있습니다] " if cross_val.get("conflict_detected") else ""
    stock_user_status = f" (내 평단가: {user_stock_info['avg_price']:,}원 / 수익률: {user_stock_info['return_rate']:.2f}%)" if has_user_stock else ""

    # 기본 수급/기술 변수
    latest_close = tech_info.get("latest_close", 0)
    ffcs_score = flow_info.get("ffcs_score", 50.0)
    today_action = decision_res.get("decision", "HOLD")
    rsi_val = tech_info.get("rsi", 50.0)
    rmi_val = tech_info.get("rmi", 50.0)
    flow_state = flow_info.get("flow_state", "NEUTRAL")
    cycle_stage = flow_info.get("cycle_stage", "중립")
    f_dir = flow_info.get("foreign_direction", "중립")
    i_dir = flow_info.get("institution_direction", "중립")

    periods_analysis = flow_info.get("periods_analysis", {})
    p_foreign = periods_analysis.get("foreign", {})
    p_inst = periods_analysis.get("institution", {})
    f5_net = p_foreign.get("5d", {}).get("net_buy", 0)
    i5_net = p_inst.get("5d", {}).get("net_buy", 0)
    f5_str = _format_flow_krw(f5_net)
    i5_str = _format_flow_krw(i5_net)

    # 교차 분석 상태 요약
    cross_lbl = cross_analysis.get("status_label", "중립") if cross_analysis else "중립"
    cross_reasons = cross_analysis.get("reasons", []) if cross_analysis else []
    cross_sub = cross_reasons[0] if cross_reasons else f"종합 지표 상태: {cross_lbl}"

    # 기술 지표 상태
    ma5 = tech_info.get("ma5", 0)
    ma20 = tech_info.get("ma20", 0)
    ma60 = tech_info.get("ma60", 0)
    ma_align = "단기 정배열" if (ma5 >= ma20 >= ma60) else ("단기 역배열" if (ma5 <= ma20 <= ma60) else "이평선 혼조")

    # 재무 변수
    e_desc = primary_fund.get("e_desc", "실적 정보 미제공")
    fiscal_period = primary_fund.get("fiscal_period", "최근 확정연도")

    # 리스크 변수
    risk_res = tech_info.get("risk_analysis", {})
    atr_pct = risk_res.get("atr_pct", 0.0)
    mdd = risk_res.get("drawdown_from_high_pct", 0.0)
    risk_st = risk_res.get("risk_state", "NORMAL")

    # GENERAL_SUMMARY는 기존 종합 리포트 형식 보존
    if primary_intent == "GENERAL_SUMMARY" or ticker == "MARKET":
        if ticker == "MARKET":
            return (
                f"{conflict_prefix}현재 주요 시황 및 매크로 동향에 대한 종합 브리핑입니다.{inline_citations}\n"
                f"하단의 관련 뉴스 및 정부 공식 자료 요약을 통해 시장의 흐름과 주요 변수를 확인하시기 바랍니다."
            )
        intent_prefix = f"💡 [보조 의견: {action_opinion}] " if query_intent else ""
        return (
            f"{conflict_prefix}{intent_prefix}'{name}'{stock_user_status}에 대한 기존 앱 데이터 & 웹 검색자료 종합 리포트입니다.{inline_citations}\n"
            f"현재 퀀트 수급 사이클 및 기술적 분석상 [{action_opinion}] 상태로 판단되며, 하단의 앱 데이터와 웹 검색자료를 함께 참고하시기 바랍니다."
        )

    # Intent별 직접 답변 + 이유 + 보조 신호 조립
    if primary_intent == "FLOW_GENERAL":
        flow_state_kr = "긍정적 개선" if flow_state in ("STRONG_IMPROVING", "IMPROVING") else ("약화" if flow_state in ("WEAKENING", "STRONG_WEAKENING") else "중립")
        ans_a = f"'{name}'의 현재 수급 동향은 [{flow_state_kr}] 상태이며, 수급 사이클은 [{cycle_stage}] 단계에 위치합니다.{inline_citations}"
        reasons_b = (
            f"1) 외국인은 최근 5일간 {f_dir}({f5_str}), 기관은 {i_dir}({i5_str}) 흐름을 나타냅니다. "
            f"2) 외국인 수급 점수(FFCS)는 {ffcs_score:.1f}점으로 수급 기반을 형성하고 있습니다."
        )
        signal_c = f"보조 신호: {cross_sub}"
        base_summary = f"{ans_a}\n• 핵심 근거: {reasons_b}\n• 점검 사항: {signal_c}"

    elif primary_intent == "FLOW_CONCURRENCY":
        conc_info = flow_info.get("concurrency", {})
        c_status = conc_info.get("status", "중립")
        c_desc = conc_info.get("description", "동조화 판단 보류")
        is_together = (f5_net > 0 and i5_net > 0) or (f5_net < 0 and i5_net < 0)
        flow_match = "동반 흐름" if is_together else "분산 흐름"
        ans_a = f"외국인과 기관의 수급 동조화(쌍끌이) 진단 결과, 현재 [{c_status}] 상태입니다.{inline_citations}"
        reasons_b = f"1) {c_desc} 2) 5일 누적 기준 외국인({f5_str})과 기관({i5_str})의 수급 방향성이 {flow_match}을 보이고 있습니다."
        signal_c = f"보조 신호: 수급 사이클 단계는 '{cycle_stage}'입니다."
        base_summary = f"{ans_a}\n• 핵심 근거: {reasons_b}\n• 점검 사항: {signal_c}"

    elif primary_intent == "FLOW_SMART_MONEY":
        lead_actor = "외국인" if abs(f5_net) >= abs(i5_net) else "기관"
        smart_tone = "유입 우세" if (f5_net + i5_net > 0) else "이탈 경계"
        ans_a = f"스마트머니(외국인 및 주요 기관 주체) 수급 진단 결과, 현재 [{smart_tone}] 기조를 보이고 있습니다.{inline_citations}"
        reasons_b = f"1) 5일 기준 외국인 {f5_str}, 기관 {i5_str}로 {lead_actor} 중심의 수급 흐름이 관측됩니다. 2) 20일 중기 누적 수급과 연계된 지속성 검증이 요구됩니다."
        signal_c = f"보조 신호: {cross_sub}"
        base_summary = f"{ans_a}\n• 핵심 근거: {reasons_b}\n• 점검 사항: {signal_c}"

    elif primary_intent == "TECH_RSI_RMI":
        rsi_zone = "과열권" if rsi_val >= 70 else ("침체/과매도권" if rsi_val <= 30 else "중립권")
        ans_a = f"RSI 및 RMI 기술적 모멘텀 진단 결과, 단기 RSI는 [{rsi_zone}], 중기 RMI는 [{rmi_val:.1f}] 구간에 위치합니다.{inline_citations}"
        reasons_b = f"1) 단기 모멘텀 지표 RSI({rsi_val:.1f})는 {rsi_zone}이며, 2) 이동평균선 배열은 {ma_align} 상태로 기술적 추세를 형성하고 있습니다."
        signal_c = f"보조 신호: {cross_sub}"
        base_summary = f"{ans_a}\n• 핵심 근거: {reasons_b}\n• 점검 사항: {signal_c}"

    elif primary_intent == "RISK_ANALYSIS":
        primary_risk = "지표 간 방향성 충돌" if cross_val.get("conflict_detected") else ("하방 가격 변동성" if mdd <= -10 else "단기 수급 이탈")
        ans_a = f"현재 데이터상 식별된 주요 위험 요인은 [{primary_risk}]이며, 종합 리스크 수준은 [{risk_st}] 상태입니다.{inline_citations}"
        reasons_b = f"1) 변동성 지표(ATR {atr_pct:.1f}%) 및 최근 고점 대비 낙폭({mdd:.1f}%). 2) {cross_sub}"
        signal_c = "대응 가이드: 단기 가격 변동성을 감안하여 일시 진입을 피하고 분할 접근 및 손절선 관리가 요구됩니다."
        base_summary = f"{ans_a}\n• 핵심 근거: {reasons_b}\n• 점검 사항: {signal_c}"

    elif primary_intent == "FUNDAMENTAL_VALUATION":
        ans_a = f"기업 실적 및 밸류에이션 분석 결과, 최근 확정 결산 기준 [{e_desc}] 상태입니다.{inline_citations}"
        reasons_b = f"1) {fiscal_period} 확정 결산 기준 {e_desc} 기조입니다. 2) 자체 과거 양수 PER/PBR 중앙값과 비교한 상대적 배수 위치를 참고할 수 있습니다."
        signal_c = "참고 안내: AI는 특정 기업의 적정주가를 단정하지 않으며, 자체 과거 시계열 기준 멀티플 위치만을 객관적으로 제시합니다."
        base_summary = f"{ans_a}\n• 핵심 근거: {reasons_b}\n• 점검 사항: {signal_c}"

    elif primary_intent == "NEWS_DISCLOSURE":
        item_count = len(official_items) + len(news_items)
        if item_count > 0:
            top_title = official_items[0]["title"] if official_items else (news_items[0]["title"] if news_items else "공시/뉴스")
            ans_a = f"최근 수집된 DART 공식 공시 및 실시간 금융뉴스 {item_count}건이 확인됩니다.{inline_citations}"
            reasons_b = f"1) 주요 헤드라인: '{top_title}' 등 관련 보도가 확인됩니다. 2) 실시간 보도는 시장 심리에 선반영될 수 있으므로 기존 수급 사이클과 병행 검토가 필요합니다."
            signal_c = f"보조 신호: 수급 사이클은 '{cycle_stage}', 투자판단은 '{today_action}' 상태입니다."
            base_summary = f"{ans_a}\n• 핵심 근거: {reasons_b}\n• 점검 사항: {signal_c}"
        else:
            ans_a = "최근 수집된 관련 뉴스 및 공시가 없어 근거가 부족합니다."
            reasons_b = "1) DART 전자공시 및 실시간 뉴스 검색에서 확인 가능한 최근 항목이 없습니다."
            signal_c = "대응 가이드: 재료 중심 판단이 어려우므로 퀀트 수급 지표와 기술적 차트 지표를 우선 기준으로 검토하시기 바랍니다."
            base_summary = f"{ans_a}\n• 핵심 근거: {reasons_b}\n• 점검 사항: {signal_c}"

    elif primary_intent == "DECISION_BUY":
        ans_a = f"현재 투자 판단 엔진 및 종합 지표 분석 결과 [{action_opinion}] 검토 의견입니다.{inline_citations}"
        reasons_b = f"1) 퀀트 엔진 판단: {today_action} (수급 점수 FFCS: {ffcs_score:.1f}점). 2) 지표 교차 종합 진단: {cross_lbl}."
        signal_c = "대응 가이드: 지지선 안착 여부를 확인하며 분할 매수로 접근하는 전략이 안전합니다."
        base_summary = f"{ans_a}\n• 핵심 근거: {reasons_b}\n• 점검 사항: {signal_c}"

    elif primary_intent == "DECISION_SELL":
        sell_score = decision_res.get("sell_score", 0)
        ans_a = f"현재 보유 포지션 관리 및 리스크 점검 결과 [{action_opinion}] 검토 의견입니다.{inline_citations}"
        reasons_b = f"1) 퀀트 엔진 판단: {today_action} (매도 점수: {sell_score}점). 2) 수급 사이클상 {cycle_stage} 단계에 위치합니다."
        signal_c = "대응 가이드: 목표 수익률 달성 또는 단기 수급 이탈 시 분할 익절/손절 관리가 유효합니다."
        base_summary = f"{ans_a}\n• 핵심 근거: {reasons_b}\n• 점검 사항: {signal_c}"

    elif primary_intent == "DECISION_WATERING":
        water_score = decision_res.get("watering_score", 0)
        ans_a = f"추가 매수(물타기) 적합성 점검 결과 [{action_opinion}] 검토 의견입니다.{inline_citations}"
        reasons_b = f"1) 추가매수 적합성 점수: {water_score}점 (TODAY ACTION: {today_action}). 2) 하락 추세 진정 및 지지선 방어 여부를 우선 확인해야 합니다."
        signal_c = "대응 가이드: 하락 추세 미진정 시 섣부른 물타기는 평균단가 대비 손실을 확대할 수 있으므로 분할 접근이 필요합니다."
        base_summary = f"{ans_a}\n• 핵심 근거: {reasons_b}\n• 점검 사항: {signal_c}"

    else:
        ans_a = f"'{name}'에 대한 기존 데이터 분석 결과 [{action_opinion}] 상태입니다.{inline_citations}"
        reasons_b = f"1) 퀀트 엔진 판단: {today_action}. 2) 수급 사이클: {cycle_stage}."
        signal_c = f"보조 신호: {cross_sub}"
        base_summary = f"{ans_a}\n• 핵심 근거: {reasons_b}\n• 점검 사항: {signal_c}"

    # Secondary Intent 보조 신호 1~2개 추가
    sec_signals: List[str] = []
    for sec in (secondary_intents or [])[:2]:
        if sec == "FLOW_GENERAL":
            sec_signals.append(f"수급 흐름은 {f_dir} 기조(5일 외인 {f5_net:+,}억/기관 {i5_net:+,}억)")
        elif sec == "FLOW_CONCURRENCY":
            conc_status = flow_info.get("concurrency", {}).get("status", "중립")
            sec_signals.append(f"외인·기관 동조화는 '{conc_status}' 상태")
        elif sec == "FLOW_SMART_MONEY":
            sec_signals.append(f"기관 5일 누적 수급은 {i5_net:+,}억원")
        elif sec == "TECH_RSI_RMI":
            sec_signals.append(f"기술 지표는 RSI {rsi_val:.1f} / RMI {rmi_val:.1f}")
        elif sec == "RISK_ANALYSIS":
            sec_signals.append(f"리스크 상태는 '{risk_st}'")
        elif sec == "FUNDAMENTAL_VALUATION":
            sec_signals.append(f"기업 실적은 {e_desc}")
        elif sec == "NEWS_DISCLOSURE":
            sec_signals.append(f"관련 공시/뉴스 {len(official_items)+len(news_items)}건 확인")

    if sec_signals:
        sec_line = " / ".join(sec_signals)
        base_summary += f"\n• 보조 관점: {sec_line}"

    return base_summary


def _build_intent_aware_analysis(
    primary_intent: str,
    secondary_intents: List[str],
    has_flow_data: bool,
    flow_info: Dict[str, Any],
    tech_info: Dict[str, Any],
    decision_res: Dict[str, Any],
    cross_analysis: Dict[str, Any],
    primary_fund: Dict[str, Any],
    comp_funds: List[Dict[str, Any]],
    citations: List[Dict[str, Any]],
    official_items: List[Dict[str, Any]],
    news_items: List[Dict[str, Any]],
    action_opinion: str,
    name: str,
) -> str:
    """
    F10B-2: Facts의 숫자를 그대로 복사하지 않고, 상태 및 방향성 해석 중심의
    차별화된 문단을 구성합니다. (Facts vs Analysis 숫자 중복률 20% 이하 목표)
    """
    paragraphs: List[str] = []

    today_action = decision_res.get("decision", "HOLD")
    flow_state = flow_info.get("flow_state", "NEUTRAL")
    cycle_stage = flow_info.get("cycle_stage", "중립")
    f_dir = flow_info.get("foreign_direction", "중립")
    i_dir = flow_info.get("institution_direction", "중립")
    ffcs_score = flow_info.get("ffcs_score", 50.0)

    # 1. Primary Intent 전용 정성 해석 문단 (Facts 숫자 미포함)
    if primary_intent == "FLOW_GENERAL":
        flow_tone = "개선되는" if flow_state in ("STRONG_IMPROVING", "IMPROVING") else ("약화되는" if flow_state in ("WEAKENING", "STRONG_WEAKENING") else "중립적인")
        paragraphs.append(
            f"• [수급 사이클 및 매수 주체 정밀 분석]: 최근 수급 흐름은 전반적으로 {flow_tone} 흐름을 보이고 있으며, "
            f"수급 사이클상 '{cycle_stage}' 구간에 위치합니다. 외국인의 {f_dir} 기조와 기관의 {i_dir} 흐름이 교차하는 가운데, "
            "단기 추세 안정화는 주요 수급 주체의 연속적인 순매수 지속 여부에 달려 있습니다."
        )
    elif primary_intent == "FLOW_CONCURRENCY":
        conc_info = flow_info.get("concurrency", {})
        c_status = conc_info.get("status", "중립")
        c_desc = conc_info.get("description", "동조화 판단 보류")
        paragraphs.append(
            f"• [외국인·기관 동조화 (쌍끌이) 심층 진단]: 외국인과 기관의 수급 동조화 상태는 현재 '{c_status}' 단계로 진단됩니다. "
            f"{c_desc} 두 주체의 매매 방향이 일치할수록 단기 시세 추세의 신뢰도가 높아지며, 한쪽의 이탈이나 엇갈린 매매는 단기 변동성을 유발할 수 있습니다."
        )
    elif primary_intent == "FLOW_SMART_MONEY":
        paragraphs.append(
            f"• [스마트머니 및 주도 주체 흐름 진단]: 주요 기관 주체와 외국인의 수급 흐름을 종합할 때, "
            "단기 자금 유입과 중기 누적 수급의 연속성을 비교 검토하는 것이 중요합니다. "
            "단기 매수세가 확인되더라도 연속적인 순매수로 이어지지 못할 경우 단기 매물 압박으로 전환될 수 있어 주의가 요구됩니다."
        )
    elif primary_intent == "TECH_RSI_RMI":
        rsi_val = tech_info.get("rsi", 50.0)
        rsi_zone = "과열권" if rsi_val >= 70 else ("침체/과매도권" if rsi_val <= 30 else "중립권")
        paragraphs.append(
            f"• [기술적 모멘텀 및 지표 정합성 진단]: 단기 모멘텀 지표는 {rsi_zone}에 머물러 있으며, "
            "중기 모멘텀 지표와 비교할 때 단기 추세의 지속성과 반등 여부를 신중히 타진하는 국면입니다. "
            "이동평균선 배열과 지지선/저항선 가격대 사이에서의 매물 소화 과정을 고려하여 분할 접근하는 전략이 적절합니다."
        )
    elif primary_intent == "RISK_ANALYSIS":
        paragraphs.append(
            f"• [위험 요인 및 변동성 정밀 진단]: 현재 확인되는 주요 리스크는 지표 간 방향성 충돌 및 가격 변동성 확대입니다. "
            "최근 고점 대비 조정 폭을 감안할 때 하방 변동성 위험에 유의해야 하며, "
            "수급 이탈 가능성과 기술적 지지선 이탈 여부에 대한 선제적 리스크 관리가 요구됩니다."
        )
    elif primary_intent == "FUNDAMENTAL_VALUATION":
        # primary_fund의 analysis_paragraphs 재사용 (앞서 숫자 복사 제거 완료)
        paragraphs.extend(primary_fund.get("analysis_paragraphs", []))
    elif primary_intent == "NEWS_DISCLOSURE":
        item_count = len(official_items) + len(news_items)
        if item_count > 0:
            paragraphs.append(
                "• [실시간 보도 및 DART 공시 진단]: 최근 확인된 공시 및 언론 보도는 기업의 최신 동향을 반영하고 있습니다. "
                "다만 단기 뉴스 이슈는 시장의 선반영 여부 및 투자 심리에 따라 변동성을 유발할 수 있으므로, "
                "객관적인 수급 사이클 및 기술적 지표와 병행 판단이 요구됩니다."
            )
        else:
            paragraphs.append(
                "• [공시 및 실시간 보도 확인 결과]: 최근 확인 가능한 공식 DART 공시 및 주요 언론사 보도가 부재하여 관련 근거가 부족합니다. "
                "단기 뉴스 재료에 의존하기보다는 기존 수급 사이클과 기술적 차트 지표를 중심으로 접근하는 것이 적절합니다."
            )
    elif primary_intent in ("DECISION_BUY", "DECISION_SELL", "DECISION_WATERING"):
        paragraphs.append(
            f"• [의사결정 보조의견 종합 진단]: 퀀트 투자판단 엔진은 현재 '{action_opinion}' 검토 의견을 제시하고 있습니다. "
            f"이는 기존 투자엔진의 판단('{today_action}')과 단기 수급 강도, 기술적 추세를 복합적으로 고려한 결과이며, "
            "시장 변동성에 대응하기 위해 섣부른 몰빵 진입을 지양하고 분할 접근 관점이 유효합니다."
        )
    else:  # GENERAL_SUMMARY
        paragraphs.append(
            f"• [수급 사이클 및 투자판단 종합 진단]: 기존 투자엔진의 판단은 '{today_action}' 관점을 제시하고 있으며, "
            "수급 사이클 및 기술적 추세를 복합적으로 고려하여 포지션을 평가하고 있습니다."
        )

    # 2. 지표 일치/충돌 분석 (Cross Analysis)
    if cross_analysis and cross_analysis.get("reasons"):
        cross_reasons = " / ".join(cross_analysis.get("reasons", []))
        paragraphs.append(f"• [지표 일치/충돌 분석]: {cross_reasons}")

    # 3. 펀더멘털 및 기업가치 진단 (FUNDAMENTAL_VALUATION이 아닌 경우 보조 진단)
    if primary_intent != "FUNDAMENTAL_VALUATION":
        paragraphs.extend(primary_fund.get("analysis_paragraphs", []))

    # 4. 수급/기술 vs 재무 충돌/정합성 진단 문단 (F8C-2)
    if primary_fund.get("has_deficit"):
        if today_action in ["BUY", "STRONG_BUY", "AVERAGE"] or ffcs_score >= 60:
            deficit_reason = f"적자/손실({primary_fund.get('e_desc')})" if primary_fund.get("has_loss") else "음수 ROE"
            conflict_msg = (
                "⚠️ [수급-재무 충돌 주의]: 단기 수급 모멘텀은 긍정적이나, "
                f"기업 실적이 최근 확정 결산 기준 {deficit_reason} 상태로 "
                "재무 건전성 리스크가 상충하고 있습니다. 기술적 반등 매매 시에도 손절선 및 비중 관리에 각별한 주의가 필요합니다."
            )
            paragraphs.append(f"• [지표 상충 진단]: {conflict_msg}")
    elif primary_fund.get("is_profitable"):
        if today_action in ["REDUCE", "STRONG_SELL", "HOLD"] or ffcs_score < 45:
            split_msg = (
                "💡 [재무-수급 분리 진단]: 기업의 본질적 재무 품질 및 이익 창출력은 견고하나, "
                "단기 외국인·기관 수급 유출 또는 기술적 조정 구간에 위치해 있습니다. "
                "무리한 조기 진입보다는 수급 턴어라운드 및 지지선 안착을 확인한 후 분할 접근이 유리합니다."
            )
            paragraphs.append(f"• [지표 분리 진단]: {split_msg}")
        elif today_action in ["BUY", "STRONG_BUY", "AVERAGE"] or ffcs_score >= 55:
            harmony_msg = "✅ [수급-재무 동반 양호]: 흑자 실적 기반의 안정적 재무품질과 함께 단기 수급 모멘텀이 긍정적으로 부합하고 있습니다."
            paragraphs.append(f"• [수급-재무 정합성]: {harmony_msg}")

    # 5. 복수 종목 비교 문단 (F8C-2)
    if comp_funds:
        c_fund = comp_funds[0]
        comp_summary = (
            f"• [종목 간 재무·가치 비교 종합]: '{primary_fund.get('name')}'(실적: {primary_fund.get('e_desc')})과 "
            f"'{c_fund.get('name')}'(실적: {c_fund.get('e_desc')})의 비교 분석 결과입니다. "
            "AI는 기존 투자판단(TODAY ACTION)을 임의 변경하거나 우열 점수를 임의 생성하지 않으며, "
            "두 종목의 실적 팩트, ROE 방향성, 과거 대비 밸류에이션 위치를 종합적으로 고려하여 의사결정을 보조합니다."
        )
        paragraphs.append(comp_summary)

    # 6. 실시간 보도 해석 (상투구 대신 실제 뉴스 유무에 따른 차별화)
    if primary_intent != "NEWS_DISCLOSURE":
        if citations:
            top_pub = citations[0].get('publisher', '언론사')
            paragraphs.append(f"• [실시간 보도 참고]: 최신 출처인 [{top_pub}] 뉴스 및 공시를 확인하여 시장 반응을 점검하고 있습니다.")
        else:
            paragraphs.append("• [공시·뉴스 참고]: 최근 확인 가능한 주요 공시 및 언론 보도가 부재하여 퀀트 수급 지표를 우선 검토합니다.")

    # 7. Secondary Intent 전용 보조 해석 문단
    for sec in (secondary_intents or [])[:2]:
        if sec == "FLOW_GENERAL" and primary_intent != "FLOW_GENERAL":
            paragraphs.append(f"• [보조 분석: 수급 흐름]: 외국인의 {f_dir} 기조와 기관의 {i_dir} 흐름이 단기 보조 신호로 작용하고 있습니다.")
        elif sec == "TECH_RSI_RMI" and primary_intent != "TECH_RSI_RMI":
            paragraphs.append("• [보조 분석: 기술 모멘텀]: 이동평균선 배열과 모멘텀 지표가 단기 변동성 구간에서 지지선 확인을 요구하고 있습니다.")
        elif sec == "RISK_ANALYSIS" and primary_intent != "RISK_ANALYSIS":
            paragraphs.append("• [보조 분석: 리스크 점검]: 지표 간 신호 충돌 및 단기 낙폭을 감안한 방어적 분할 접근이 필요합니다.")
        elif sec == "FUNDAMENTAL_VALUATION" and primary_intent != "FUNDAMENTAL_VALUATION":
            paragraphs.append(f"• [보조 분석: 기업 실적]: {primary_fund.get('e_desc')} 기조가 하방 지지력을 보강하고 있습니다.")

    return "\n".join(paragraphs)


def generate_grounded_qna_answer(
    ticker: str,
    name: str,
    query: str,
    asset_type: str = "STOCK",
    manager: str = ""
) -> Dict[str, Any]:
    """
    3차-K 신뢰도 최우선 AI Q&A 엔진 (Fact-Only, Zero Hallucination, 5단계 구조화)
    
    ① 확인된 데이터 (기준일시, 출처, 수치)
    ② 데이터에 근거한 AI 해석 (TODAY ACTION, FCS, RSI 연계)
    ③ 위험요인 / 반대 신호 (충돌 지표, 수급 이탈 등)
    ④ 데이터 부족 또는 불확실성 (미확인 데이터 명시 및 예측 불가 안내)
    ⑤ 최종 요약 (단정적 추천 배지 대신 근거 중심 요약)
    """
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. 예외 및 미래 예측 질문 감지
    is_prediction_query = any(kw in query for kw in PREDICTION_QUERY_KEYWORDS)

    if not name and not ticker and ticker != "MARKET":
        return {
            "status": "fail",
            "message": "데이터 부족으로 확인할 수 없습니다.",
            "is_grounded": False,
            "executive_summary": "데이터 부족으로 확인할 수 없습니다. (검색 종목 미지정)",
            "verified_facts": ["검색 대상 종목 또는 ETF 정보가 지정되지 않았습니다."],
            "ai_analysis": "확인할 수 있는 데이터가 부재하여 AI 해석을 제공할 수 없습니다.",
            "uncertainties": "데이터 부족으로 확인할 수 없습니다.",
            "action_opinion": "확인 불가 / 관망",
            "app_user_data": {"has_user_stock": False, "message": "현재 해당 데이터를 사용할 수 없습니다."},
            "citations": [],
            "news_items": [],
            "official_items": []
        }

    # 2. 사용자 보유 데이터 연동 (DB)
    user_stock_db = None
    if ticker != "MARKET":
        user_stock_db = get_user_portfolio_info(ticker, name)
    has_user_stock = user_stock_db is not None
    user_stock_info = {}

    if has_user_stock:
        avg_p = user_stock_db.get("avg_price", 0)
        qty = user_stock_db.get("quantity", 0)
        user_stock_info = {
            "has_user_stock": True,
            "name": user_stock_db.get("name", name),
            "ticker": user_stock_db.get("ticker", ticker),
            "avg_price": avg_p,
            "quantity": qty,
            "invested_amount": avg_p * qty,
            "current_price": avg_p,
            "eval_amount": avg_p * qty,
            "profit_loss": 0.0,
            "return_rate": 0.0,
            "sector": user_stock_db.get("sector", "기타")
        }

    # 3. 주가, 수급, 퀀트 지표, Cross Analysis 수집
    flow_data = {}
    has_flow_data = False
    if ticker != "MARKET":
        flow_data = get_stock_flow_data(name or ticker, min_days=30)
        has_flow_data = flow_data.get("data_available", False)
    
    decision_res = {}
    tech_info = {}
    flow_info = {}
    timing_info = {}
    cross_analysis = {}

    if has_flow_data:
        df = flow_data["df"]
        res_full = analyze_stock_decision(df)
        decision_res = res_full.get("decision", {})
        tech_info = res_full.get("technical_analysis", {})
        flow_info = res_full.get("flow_analysis", {})
        timing_info = res_full.get("timing_analysis", {})

        # Cross Analysis 산출
        cross_analysis = analyze_cross_indicators(flow_info, tech_info, None, decision_res)

        # 보유 종목일 경우 평가액 & 수익률 계산
        if has_user_stock:
            curr_p = tech_info.get("latest_close", user_stock_db.get("avg_price", 0))
            avg_p = user_stock_db.get("avg_price", 0)
            qty = user_stock_db.get("quantity", 0)
            invested = avg_p * qty
            eval_amt = curr_p * qty
            profit_loss = eval_amt - invested
            ret_rate = ((curr_p - avg_p) / avg_p) * 100.0 if avg_p > 0 else 0.0

            user_stock_info["current_price"] = curr_p
            user_stock_info["eval_amount"] = eval_amt
            user_stock_info["profit_loss"] = profit_loss
            user_stock_info["return_rate"] = ret_rate
    
    if not user_stock_info:
        user_stock_info = {
            "has_user_stock": False,
            "message": "현재 해당 보유 포트폴리오 데이터를 사용할 수 없습니다. (미보유 종목)"
        }

    # 4. 실시간 뉴스 및 공식자료 수집 (F9C: 5분 TTL 메모리 캐시 연동)
    news_res = _get_cached_news(ticker=ticker, name=name, query=query)
    official_res = _get_cached_official(ticker=ticker, name=name, query=query, asset_type=asset_type, manager=manager)

    news_items = news_res.get("items", []) if news_res.get("status") == "success" else []
    official_items = official_res.get("items", []) if official_res.get("status") == "success" else []

    # 5. Citation 및 교차검증
    citations = generate_citations(news_items, official_items)
    cross_val = perform_cross_validation(news_items, official_items, has_flow_data=has_flow_data)

    # 🛡️ Guardrail Check
    is_real_official = any("바로가기" not in o.get("title", "") and o.get("doc_type") != "공시 검색" for o in official_items)
    
    if not has_flow_data and not news_items and not is_real_official:
        return {
            "status": "insufficient_data",
            "message": "데이터 부족으로 확인할 수 없습니다.",
            "is_grounded": False,
            "reliability_grade": "낮음",
            "executive_summary": "최근 수집된 관련 뉴스 및 공시가 없어 근거가 부족합니다. (확인된 수급 및 공시/뉴스 부재)",
            "verified_facts": ["최근 수집된 관련 뉴스 및 DART/정부 공시 자료가 없어 근거가 부족합니다. [상태: 자료부족]"],
            "ai_analysis": "확인된 주가 및 공시 데이터가 없어 AI 해석을 제공할 수 없습니다. 최근 수집된 관련 뉴스 및 공시가 없어 근거가 부족합니다.",
            "uncertainties": "데이터 부족으로 확인할 수 없습니다.",
            "action_opinion": "관망 (자료 미존재)",
            "app_user_data": user_stock_info,
            "cross_validation": cross_val,
            "citations": citations,
            "news_items": news_items,
            "official_items": official_items
        }

    routed_intents = route_qna_intents(query)
    primary_intent = routed_intents["primary_intent"]
    secondary_intents = routed_intents["secondary_intents"]
    qna_intent = primary_intent
    query_intent = classify_decision_query(query)
    action_opinion = determine_action_opinion(query_intent, decision_res, user_stock_info if has_user_stock else None)

    # 펀더멘털 및 기업가치 Grounding Context 확보 (F8C-2)
    primary_fund = format_fundamental_grounding(ticker=ticker, name=name, asset_type=asset_type)

    # F10B-1 / F10B-1R: Intent별 기존 엔진 데이터 Source Mapping
    intent_source_map = map_intent_data_sources(
        qna_intent=primary_intent,
        flow_data=flow_data,
        flow_info=flow_info,
        tech_info=tech_info,
        timing_info=timing_info,
        decision_res=decision_res,
        cross_analysis=cross_analysis,
        primary_fund=primary_fund,
        news_items=news_items,
        official_items=official_items,
        user_stock_info=user_stock_info,
        secondary_intents=secondary_intents,
    )

    # 복수 종목 비교 질의 감지
    comp_targets = detect_comparison_targets(query=query, current_target_name=name, current_target_ticker=ticker)
    comp_funds = [
        format_fundamental_grounding(ticker=c_tick, name=c_name, asset_type="STOCK", label_prefix=c_name)
        for c_tick, c_name in comp_targets
    ]

    # ① 확인된 데이터 (F10B-2: Intent-Aware Fact 우선순위 배치 및 특화 팩트 조립)
    verified_facts = _build_intent_aware_facts(
        primary_intent=primary_intent,
        secondary_intents=secondary_intents,
        current_time_str=current_time_str,
        has_user_stock=has_user_stock,
        user_stock_info=user_stock_info,
        has_flow_data=has_flow_data,
        flow_info=flow_info,
        tech_info=tech_info,
        timing_info=timing_info,
        decision_res=decision_res,
        cross_analysis=cross_analysis,
        primary_fund=primary_fund,
        comp_funds=comp_funds,
        official_items=official_items,
        news_items=news_items,
        action_opinion=action_opinion,
        name=name,
        ticker=ticker,
    )

    # ② AI 해석 (F10B-2: Intent-Aware Analysis 및 숫자 중복 20% 이하 제거)
    ai_analysis_text = _build_intent_aware_analysis(
        primary_intent=primary_intent,
        secondary_intents=secondary_intents,
        has_flow_data=has_flow_data,
        flow_info=flow_info,
        tech_info=tech_info,
        decision_res=decision_res,
        cross_analysis=cross_analysis,
        primary_fund=primary_fund,
        comp_funds=comp_funds,
        citations=citations,
        official_items=official_items,
        news_items=news_items,
        action_opinion=action_opinion,
        name=name,
    )

    # ③ ④ 불확실성 및 위험
    uncertainties = []
    if is_prediction_query:
        uncertainties.append("⚠️ [예측 불가 안내] AI는 미래 주가나 확실한 상승/하락 여부를 단정적으로 예측할 수 없으며, 확인된 실시간 데이터에 근거한 정보만 제공합니다.")
    
    # 펀더멘털 불확실성 추가 (F8C-2)
    uncertainties.extend(primary_fund.get("uncertainty_items", []))
    if primary_fund.get("has_deficit"):
        if primary_fund.get("has_loss"):
            uncertainties.append("수급 지표와 기업 재무 실적(적자/손실) 간 상충 요인 존재")
        else:
            uncertainties.append(f"수급 지표와 기업 재무 실적(음수 ROE: {primary_fund.get('roe'):.2f}%) 간 상충 요인 존재")

    if asset_type == "ETF":
        uncertainties.append("💡 [ETF 수급 특성] ETF 종목 특성상 LP/AP 유동성 공급 및 설정·환매 자금이 포함되어 있습니다.")
        
    if cross_val.get("conflict_detected"):
        uncertainties.append("⚠️ [자료 상충] 수집된 출처 간 내용에 일부 차이가 존재하므로 주의가 필요합니다.")
    
    if not has_user_stock and ticker != "MARKET":
        uncertainties.append("현재 보유하지 않은 종목이므로 계좌 평단가 및 수익률 연동이 미적용되어 있습니다.")
    if not official_items:
        uncertainties.append("DART 및 정부기관 공식 공시 보도자료의 추가 업데이트 확인이 필요합니다.")
    if has_flow_data:
        uncertainties.append("단기 환율 변동성 및 매크로 지수 조정에 따른 지지선 이탈 위험에 주의가 필요합니다.")

    # 10. [핵심 답변 (Executive Summary)] (F10B-2: Intent-Aware Summary)
    summary_text = _build_intent_aware_summary(
        primary_intent=primary_intent,
        secondary_intents=secondary_intents,
        name=name,
        ticker=ticker,
        has_user_stock=has_user_stock,
        user_stock_info=user_stock_info,
        has_flow_data=has_flow_data,
        flow_info=flow_info,
        tech_info=tech_info,
        decision_res=decision_res,
        cross_analysis=cross_analysis,
        primary_fund=primary_fund,
        official_items=official_items,
        news_items=news_items,
        action_opinion=action_opinion,
        citations=citations,
        cross_val=cross_val,
        query_intent=query_intent,
    )

    return {
        "status": "success",
        "is_grounded": True,
        "query": query,
        "qna_intent": qna_intent,
        "primary_intent": primary_intent,
        "secondary_intents": secondary_intents,
        "intent_source_map": intent_source_map,
        "target_stock": f"{name} ({ticker})",
        "reliability_grade": cross_val["reliability_grade"],
        "action_opinion": action_opinion,
        "executive_summary": summary_text,
        "verified_facts": verified_facts,
        "ai_analysis": ai_analysis_text,
        "uncertainties": " / ".join(uncertainties),
        "app_user_data": user_stock_info,
        "cross_validation": cross_val,
        "citations": citations,
        "count_facts": len(verified_facts),
        "count_citations": len(citations),
        "news_items": news_items,
        "official_items": official_items
    }
