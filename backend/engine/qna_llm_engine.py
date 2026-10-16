import re
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from backend.data.collector import get_stock_flow_data
from backend.engine.decision_engine import analyze_stock_decision
from backend.engine.cross_validation_engine import analyze_cross_indicators, perform_cross_validation
from backend.engine.news_engine import fetch_qna_stock_news
from backend.engine.official_engine import fetch_official_documents
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
    key = f"{ticker or name}_{asset_type}".strip().upper()
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

# 금융 질문 의사결정 보조 키워드 매핑
DECISION_QUERY_KEYWORDS = {
    "BUY": ["사?", "사야", "매수", "진입", "매수해도", "살까"],
    "SELL": ["팔아?", "팔아야", "매도", "익절", "손절", "팔까"],
    "WATERING": ["물타기", "추매", "추가매수", "평단가", "더 사"],
}

# 미래 예측 / 환각 유발 질문 감지 키워드
PREDICTION_QUERY_KEYWORDS = ["확실히", "무조건", "얼마까지", "상향", "상장폐지", "대박", "보장", "내일 오르", "내일 떨어"]

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
    """질문에 포함된 의사결정 의도(BUY, SELL, WATERING)를 감지합니다."""
    for intent, kws in DECISION_QUERY_KEYWORDS.items():
        for kw in kws:
            if kw in query:
                return intent
    return None

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

        # PER Own-History 표현
        if per_h.get("history_available"):
            p_diff = per_h.get("vs_prior_median_pct")
            p_med = per_h.get("prior_median")
            p_pos = per_h.get("position")
            if p_pos == "BELOW_PRIOR_MEDIAN":
                per_hist_str = f"이전 확정연도 양수 PER 중앙값({p_med:.2f}배)보다 {abs(p_diff):.1f}% 낮은 위치 (자사 과거 확정연도 중앙값보다 낮은 위치)"
            elif p_pos == "ABOVE_PRIOR_MEDIAN":
                per_hist_str = f"이전 확정연도 양수 PER 중앙값({p_med:.2f}배)보다 {abs(p_diff):.1f}% 높은 위치 (자사 과거 확정연도 중앙값보다 높은 위치)"
            else:
                per_hist_str = f"이전 확정연도 양수 PER 중앙값({p_med:.2f}배)과 유사한 위치 ({p_diff:+.1f}%)"
        else:
            per_hist_str = "PER 과거 중앙값 비교: 과거 2개년 이상 양수 Actual 지표 부재로 비교 부적합"

        # PBR Own-History 표현
        if pbr_h.get("history_available"):
            b_diff = pbr_h.get("vs_prior_median_pct")
            b_med = pbr_h.get("prior_median")
            b_pos = pbr_h.get("position")
            if b_pos == "BELOW_PRIOR_MEDIAN":
                pbr_hist_str = f"PBR 과거 중앙값({b_med:.2f}배) 대비 {abs(b_diff):.1f}% 낮은 위치 (자사 과거 확정연도 중앙값보다 낮은 위치)"
            elif b_pos == "ABOVE_PRIOR_MEDIAN":
                pbr_hist_str = f"PBR 과거 중앙값({b_med:.2f}배) 대비 {abs(b_diff):.1f}% 높은 위치 (자사 과거 확정연도 중앙값보다 높은 위치)"
            else:
                pbr_hist_str = f"PBR 과거 중앙값({b_med:.2f}배)과 유사한 위치 ({b_diff:+.1f}%)"
        else:
            pbr_hist_str = "PBR 과거 중앙값 비교: 과거 2개년 이상 양수 Actual 지표 부재로 비교 부적합"

        # ROE Direction 표현
        r_dir = roe_h.get("direction")
        r_chg = roe_h.get("roe_change_pct_point")
        if r_dir == "IMPROVING":
            roe_dir_str = f"ROE 방향성: 직전 결산 대비 {r_chg:+0.2f}%p 개선(IMPROVING)"
        elif r_dir == "DECLINING":
            roe_dir_str = f"ROE 방향성: 직전 결산 대비 {r_chg:+0.2f}%p 둔화(DECLINING)"
        elif r_dir == "FLAT":
            roe_dir_str = f"ROE 방향성: 직전 결산 대비 변동 없음(FLAT)"
        else:
            roe_dir_str = "ROE 방향성: 비교 불가"

        fact_2 = (
            f"[📈 기업가치 Context] {pfx}{per_str} | {pbr_str} | {roe_str} | "
            f"{per_hist_str} | {pbr_hist_str} | {roe_dir_str} "
            f"[출처: QUANT Own-History 엔진 / 상태: 정상]"
        )
        facts.append(fact_2)

        # AI 해석 문단
        analysis_paragraphs.append(
            f"• [재무품질 및 기업가치 팩트 진단]: {resolved_name}의 최근 확정 결산({fiscal_period}) 실적은 {e_desc} 상태이며, "
            f"{score_str}을 기록하고 있습니다. 가치배수는 {per_str}, {pbr_str} 수준이며 {roe_dir_str}입니다. "
            f"자체 과거 배수 비교상 PER은 {per_hist_str}에 위치합니다. (단, 업종별 적정가치 단정은 배제)"
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
    cross_analysis = {}

    if has_flow_data:
        df = flow_data["df"]
        res_full = analyze_stock_decision(df)
        decision_res = res_full.get("decision", {})
        tech_info = res_full.get("technical_analysis", {})
        flow_info = res_full.get("flow_analysis", {})

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
            "executive_summary": "데이터 부족으로 확인할 수 없습니다. (확인된 수급 및 공시/뉴스 부재)",
            "verified_facts": ["검색된 최신 뉴스 및 DART/정부 공시 자료가 부재합니다. [상태: 미확인]"],
            "ai_analysis": "확인된 주가 및 공시 데이터가 없어 AI 해석을 제공할 수 없습니다.",
            "uncertainties": "데이터 부족으로 확인할 수 없습니다.",
            "action_opinion": "관망 (자료 미존재)",
            "app_user_data": user_stock_info,
            "cross_validation": cross_val,
            "citations": citations,
            "news_items": news_items,
            "official_items": official_items
        }

    query_intent = classify_decision_query(query)
    action_opinion = determine_action_opinion(query_intent, decision_res, user_stock_info if has_user_stock else None)

    # 펀더멘털 및 기업가치 Grounding Context 확보 (F8C-2)
    primary_fund = format_fundamental_grounding(ticker=ticker, name=name, asset_type=asset_type)

    # 복수 종목 비교 질의 감지
    comp_targets = detect_comparison_targets(query=query, current_target_name=name, current_target_ticker=ticker)
    comp_funds = [
        format_fundamental_grounding(ticker=c_tick, name=c_name, asset_type="STOCK", label_prefix=c_name)
        for c_tick, c_name in comp_targets
    ]

    # ① 확인된 데이터
    verified_facts = []
    if has_user_stock:
        p_sign = "+" if user_stock_info["profit_loss"] >= 0 else ""
        verified_facts.append(
            f"[📱 앱 보유 데이터] {user_stock_info['name']}({user_stock_info['ticker']}) "
            f"평단가 {user_stock_info['avg_price']:,}원 | 수량 {user_stock_info['quantity']:,}주 | "
            f"손익 {p_sign}{user_stock_info['profit_loss']:,}원 ({p_sign}{user_stock_info['return_rate']:.2f}%) "
            f"[기준일시: {current_time_str} / 출처: 사용자 포트폴리오 DB / 상태: 정상]"
        )
    else:
        verified_facts.append(
            f"[📱 앱 보유 데이터] {name or ticker}: 현재 해당 보유 포트폴리오 데이터를 사용할 수 없습니다. (미보유 종목) "
            f"[기준일시: {current_time_str} / 출처: 포트폴리오 DB / 상태: 미확인]"
        )

    if has_flow_data:
        latest_close = tech_info.get("latest_close", 0)
        ffcs_score = flow_info.get("ffcs_score", 50.0)
        today_action = decision_res.get("decision", "HOLD")
        rsi_val = tech_info.get("rsi", 50.0)
        rmi_val = tech_info.get("rmi", 50.0)
        
        verified_facts.append(
            f"[📊 앱 퀀트 수급 데이터] 종가: {latest_close:,}원 | TODAY ACTION: {today_action} | "
            f"FFCS: {ffcs_score}점 | RSI: {rsi_val} | RMI: {rmi_val} "
            f"[기준일시: {current_time_str} / 출처: QUANT AI 엔진 / 상태: 정상]"
        )

    if cross_analysis and cross_analysis.get("available"):
        status_lbl = cross_analysis.get("status_label", "중립")
        verified_facts.append(
            f"[🔮 지표 교차 분석 (Cross Analysis)] 종합 진단: {status_lbl} "
            f"[기준일시: {current_time_str} / 출처: Cross Validation Engine / 상태: 정상]"
        )

    # 펀더멘털 및 기업가치 팩트 추가 (F8C-2)
    verified_facts.extend(primary_fund["facts"])

    # 비교 종목 팩트 추가 (F8C-2 복수 종목 질의 지원)
    for c_fund in comp_funds:
        verified_facts.extend(c_fund["facts"])

    for off in official_items[:2]:
        verified_facts.append(f"[🌐 공시/보도자료] [{off['institution']}] {off['title']} ({off['pub_date']}) [출처: 공식 DART/정부기관 / 상태: 정상]")

    for news in news_items[:2]:
        verified_facts.append(f"[🌐 실시간 뉴스] [{news['source']}] {news['title']} ({news['pub_date']}) [출처: 실시간 금융뉴스 / 상태: 정상]")

    # ② AI 해석
    ai_analysis_paragraphs = []
    today_action = decision_res.get("decision", "HOLD")
    ffcs_score = flow_info.get("ffcs_score", 50.0)

    if has_flow_data:
        ai_analysis_paragraphs.append(
            f"• [엔진 결과 및 수급 해석]: 기존 투자엔진의 판단은 '{today_action}'(FFCS {ffcs_score}점) 수준을 기록하고 있습니다."
        )
        if cross_analysis and cross_analysis.get("reasons"):
            cross_reasons = " / ".join(cross_analysis.get("reasons", []))
            ai_analysis_paragraphs.append(f"• [지표 일치/충돌 분석]: {cross_reasons}")

    # 펀더멘털 및 기업가치 진단 문단 추가 (F8C-2)
    ai_analysis_paragraphs.extend(primary_fund["analysis_paragraphs"])

    # 수급/기술 vs 재무 충돌 진단 문단 (F8C-2)
    if primary_fund.get("has_deficit"):
        if today_action in ["BUY", "STRONG_BUY", "AVERAGE"] or ffcs_score >= 60:
            if primary_fund.get("has_loss"):
                deficit_reason = f"적자/손실({primary_fund.get('e_desc')})"
            else:
                deficit_reason = f"음수 ROE({primary_fund.get('roe'):.2f}%)"
            conflict_msg = (
                "⚠️ [수급-재무 충돌 주의]: 단기 수급 모멘텀(FFCS/TODAY ACTION)은 긍정적이나, "
                f"기업 실적이 최근 확정 결산({primary_fund.get('fiscal_period')}) 기준 {deficit_reason} 상태로 "
                "재무 건전성 리스크가 상충하고 있습니다. 기술적 반등 매매 시에도 손절선 및 비중 관리에 각별한 주의가 필요합니다."
            )
            ai_analysis_paragraphs.append(f"• [지표 상충 진단]: {conflict_msg}")
    elif primary_fund.get("is_profitable"):
        if today_action in ["REDUCE", "STRONG_SELL", "HOLD"] or ffcs_score < 45:
            split_msg = (
                "💡 [재무-수급 분리 진단]: 기업의 본질적 재무 품질 및 이익 창출력은 견고하나, "
                "단기 외국인·기관 수급 유출 또는 기술적 조정 구간에 위치해 있습니다. "
                "무리한 조기 진입보다는 수급 턴어라운드 및 지지선 안착을 확인한 후 분할 접근이 유리합니다."
            )
            ai_analysis_paragraphs.append(f"• [지표 분리 진단]: {split_msg}")
        elif today_action in ["BUY", "STRONG_BUY", "AVERAGE"] or ffcs_score >= 55:
            harmony_msg = (
                "✅ [수급-재무 동반 양호]: 흑자 실적 기반의 안정적 재무품질과 함께 단기 수급 모멘텀이 긍정적으로 부합하고 있습니다."
            )
            ai_analysis_paragraphs.append(f"• [수급-재무 정합성]: {harmony_msg}")

    # 복수 종목 비교 문단 추가 (F8C-2)
    if comp_funds:
        c_fund = comp_funds[0]
        p_qscore = primary_fund.get("quality_score")
        c_qscore = c_fund.get("quality_score")
        p_score_str = f"{p_qscore}점" if p_qscore is not None else "제외"
        c_score_str = f"{c_qscore}점" if c_qscore is not None else "제외"
        comp_summary = (
            f"• [종목 간 재무·가치 비교 종합]: '{primary_fund.get('name')}'(재무품질: {p_score_str}, 실적: {primary_fund.get('e_desc')})과 "
            f"'{c_fund.get('name')}'(재무품질: {c_score_str}, 실적: {c_fund.get('e_desc')})의 비교 분석 결과입니다. "
            "AI는 기존 투자판단(TODAY ACTION)을 임의 변경하거나 우열 점수를 임의 생성하지 않으며, "
            "두 종목의 실적 팩트, ROE 방향성, 과거 대비 밸류에이션 위치를 종합적으로 고려하여 의사결정을 보조합니다."
        )
        ai_analysis_paragraphs.append(comp_summary)

    if citations:
        top_pub = citations[0]['publisher']
        ai_analysis_paragraphs.append(f"• [실시간 보도 해석]: 최신 출처인 [{top_pub}] 뉴스 및 공시 검증 결과 관련 이슈가 확인됩니다.")

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

    # 10. [핵심 답변 (Executive Summary)]
    inline_citations = "".join([f" [{idx+1}]" for idx in range(min(len(citations), 3))])
    intent_prefix = f"💡 [보조 의견: {action_opinion}] " if query_intent and ticker != "MARKET" else ""
    conflict_prefix = "⚠️ [자료 간 내용에 차이가 있습니다] " if cross_val.get("conflict_detected") else ""

    stock_user_status = f" (내 평단가: {user_stock_info['avg_price']:,}원 / 수익률: {user_stock_info['return_rate']:.2f}%)" if has_user_stock else ""

    if ticker == "MARKET":
        summary_text = (
            f"{conflict_prefix}현재 주요 시황 및 매크로 동향에 대한 종합 브리핑입니다.{inline_citations}\n"
            f"하단의 관련 뉴스 및 정부 공식 자료 요약을 통해 시장의 흐름과 주요 변수를 확인하시기 바랍니다."
        )
        action_opinion = "시황 브리핑"
    else:
        summary_text = (
            f"{conflict_prefix}{intent_prefix}'{name}'{stock_user_status}에 대한 기존 앱 데이터 & 웹 검색자료 종합 리포트입니다.{inline_citations}\n"
            f"현재 퀀트 수급 사이클 및 기술적 분석상 [{action_opinion}] 상태로 판단되며, 하단의 앱 데이터와 웹 검색자료를 함께 참고하시기 바랍니다."
        )

    return {
        "status": "success",
        "is_grounded": True,
        "query": query,
        "target_stock": f"{name} ({ticker})",
        "reliability_grade": cross_val["reliability_grade"],
        "action_opinion": action_opinion,
        "executive_summary": summary_text,
        "verified_facts": verified_facts,
        "ai_analysis": "\n".join(ai_analysis_paragraphs),
        "uncertainties": " / ".join(uncertainties),
        "app_user_data": user_stock_info,
        "cross_validation": cross_val,
        "citations": citations,
        "count_facts": len(verified_facts),
        "count_citations": len(citations),
        "news_items": news_items,
        "official_items": official_items
    }
