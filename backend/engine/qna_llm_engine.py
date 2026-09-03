import re
from datetime import datetime
from typing import List, Dict, Any, Optional

from backend.data.collector import get_stock_flow_data
from backend.engine.decision_engine import analyze_stock_decision
from backend.engine.smart_flow_engine import analyze_smart_money_flow
from backend.engine.cross_validation_engine import analyze_cross_indicators, perform_cross_validation
from backend.engine.news_engine import fetch_qna_stock_news
from backend.engine.official_engine import fetch_official_documents
from backend.engine.citation_engine import generate_citations
from backend.db import database as db

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
    stock = None
    if ticker:
        stock = db.get_stock_by_ticker(ticker)
    if not stock and name:
        all_stocks = db.get_all_stocks(asset_type="ALL")
        for s in all_stocks:
            if s["name"] == name:
                stock = s
                break
    return stock

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
    ② 데이터에 근거한 AI 해석 (TODAY ACTION, FCS, RSI, Smart Money 연계)
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
            "citations": []
        }

    # 2. 사용자 보유 데이터 연동 (DB)
    user_stock_db = None
    if ticker != "MARKET":
        user_stock_db = get_user_portfolio_info(ticker, name)
    has_user_stock = user_stock_db is not None
    user_stock_info = {}

    # 3. 주가, 수급, 퀀트 지표, Smart Money, Cross Analysis 수집
    flow_data = {}
    has_flow_data = False
    if ticker != "MARKET":
        flow_data = get_stock_flow_data(name or ticker, min_days=30)
        has_flow_data = flow_data.get("data_available", False)
    
    decision_res = {}
    tech_info = {}
    flow_info = {}
    smart_flow = {}
    cross_analysis = {}

    if has_flow_data:
        df = flow_data["df"]
        res_full = analyze_stock_decision(df)
        decision_res = res_full.get("decision", {})
        tech_info = res_full.get("technical_analysis", {})
        flow_info = res_full.get("flow_analysis", {})

        # Smart Money Flow 및 Cross Analysis 산출
        smart_flow = analyze_smart_money_flow(flow_data.get("investor_breakdown"), df, asset_type=asset_type)
        cross_analysis = analyze_cross_indicators(flow_info, tech_info, smart_flow, decision_res)

        # 보유 종목일 경우 평가액 & 수익률 계산
        if has_user_stock:
            curr_p = tech_info.get("latest_close", user_stock_db["avg_price"])
            avg_p = user_stock_db["avg_price"]
            qty = user_stock_db["quantity"]
            invested = avg_p * qty
            eval_amt = curr_p * qty
            profit_loss = eval_amt - invested
            ret_rate = ((curr_p - avg_p) / avg_p) * 100.0 if avg_p > 0 else 0.0

            user_stock_info = {
                "has_user_stock": True,
                "name": user_stock_db["name"],
                "ticker": user_stock_db["ticker"],
                "avg_price": avg_p,
                "quantity": qty,
                "invested_amount": invested,
                "current_price": curr_p,
                "eval_amount": eval_amt,
                "profit_loss": profit_loss,
                "return_rate": ret_rate,
                "sector": user_stock_db.get("sector", "기타")
            }
    
    if not user_stock_info:
        user_stock_info = {
            "has_user_stock": False,
            "message": "현재 해당 보유 포트폴리오 데이터를 사용할 수 없습니다. (미보유 종목)"
        }

    # 4. 실시간 뉴스 및 공식자료 수집
    news_res = fetch_qna_stock_news(ticker=ticker, name=name, query=query)
    official_res = fetch_official_documents(ticker=ticker, name=name, query=query, asset_type=asset_type, manager=manager)

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
            "citations": citations
        }

    query_intent = classify_decision_query(query)
    action_opinion = determine_action_opinion(query_intent, decision_res, user_stock_info if has_user_stock else None)

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
        smart_score = smart_flow.get("score") if smart_flow else None
        smart_label = smart_flow.get("signal_label", "미확인") if smart_flow else "미확인"
        smart_score_str = f"{smart_score}점 ({smart_label})" if smart_score is not None else "데이터 부족 (판단 보류)"
        
        verified_facts.append(
            f"[📊 앱 퀀트 수급 데이터] 종가: {latest_close:,}원 | TODAY ACTION: {today_action} | "
            f"FFCS: {ffcs_score}점 | RSI: {rsi_val} | RMI: {rmi_val} | Smart Money: {smart_score_str} "
            f"[기준일시: {current_time_str} / 출처: QUANT AI 엔진 / 상태: 정상]"
        )

    if cross_analysis and cross_analysis.get("available"):
        status_lbl = cross_analysis.get("status_label", "중립")
        verified_facts.append(
            f"[🔮 지표 교차 분석 (Cross Analysis)] 종합 진단: {status_lbl} "
            f"[기준일시: {current_time_str} / 출처: Cross Validation Engine / 상태: 정상]"
        )

    for off in official_items[:2]:
        verified_facts.append(f"[🌐 공시/보도자료] [{off['institution']}] {off['title']} ({off['pub_date']}) [출처: 공식 DART/정부기관 / 상태: 정상]")

    for news in news_items[:2]:
        verified_facts.append(f"[🌐 실시간 뉴스] [{news['source']}] {news['title']} ({news['pub_date']}) [출처: 실시간 금융뉴스 / 상태: 정상]")

    # ② AI 해석
    ai_analysis_paragraphs = []
    if has_flow_data:
        today_action = decision_res.get("decision", "HOLD")
        ffcs_score = flow_info.get("ffcs_score", 50.0)
        smart_score = smart_flow.get("score") if smart_flow else None
        ai_analysis_paragraphs.append(
            f"• [엔진 결과 및 수급 해석]: 기존 투자엔진의 판단은 '{today_action}'(FFCS {ffcs_score}점)이며, "
            f"큰손 수급(Smart Money Score)은 {smart_score if smart_score is not None else '미확인'}점 수준을 기록하고 있습니다."
        )
        if cross_analysis and cross_analysis.get("reasons"):
            cross_reasons = " / ".join(cross_analysis.get("reasons", []))
            ai_analysis_paragraphs.append(f"• [지표 일치/충돌 분석]: {cross_reasons}")

    if citations:
        top_pub = citations[0]['publisher']
        ai_analysis_paragraphs.append(f"• [실시간 보도 해석]: 최신 출처인 [{top_pub}] 뉴스 및 공시 검증 결과 관련 이슈가 확인됩니다.")

    # ③ ④ 불확실성 및 위험
    uncertainties = []
    if is_prediction_query:
        uncertainties.append("⚠️ [예측 불가 안내] AI는 미래 주가나 확실한 상승/하락 여부를 단정적으로 예측할 수 없으며, 확인된 실시간 데이터에 근거한 정보만 제공합니다.")
    if smart_flow and not smart_flow.get("is_detail_available"):
        uncertainties.append("⚠️ [수급 미확인] 기관 세부 주체 수급 데이터가 미확인 상태이므로 기관 전체 합계 수급을 보조로 참조합니다.")
    
    if asset_type == "ETF" or (smart_flow and smart_flow.get("is_etf")):
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
        "count_citations": len(citations)
    }
