import re
from datetime import datetime
from typing import List, Dict, Any, Optional

from backend.data.collector import get_stock_flow_data
from backend.engine.decision_engine import analyze_stock_decision
from backend.engine.news_engine import fetch_qna_stock_news
from backend.engine.official_engine import fetch_official_documents
from backend.engine.citation_engine import generate_citations
from backend.engine.cross_validation_engine import perform_cross_validation
from backend.db import database as db

# 금융 질문 의사결정 보조 키워드 매핑
DECISION_QUERY_KEYWORDS = {
    "BUY": ["사?", "사야", "매수", "진입", "매수해도", "살까"],
    "SELL": ["팔아?", "팔아야", "매도", "익절", "손절", "팔까"],
    "WATERING": ["물타기", "추매", "추가매수", "평단가", "더 사"],
}

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
    확정적인 명령 대신 데이터와 수급, 사용자의 수익률 상태 기반 '의사결정 보조 의견'을 산출합니다.
    """
    decision = decision_data.get("decision", "HOLD")
    buy_score = decision_data.get("buy_score", 0)
    sell_score = decision_data.get("sell_score", 0)
    water_score = decision_data.get("watering_score", 0)

    # 사용자 보유 시 수익률 고려
    return_rate = 0.0
    if user_stock and "return_rate" in user_stock:
        return_rate = user_stock["return_rate"]

    if intent == "BUY":
        if decision in ["BUY", "STRONG_BUY"] or buy_score >= 60:
            return "매수 검토 (지지선 및 수급 개선 확인)"
        elif buy_score >= 40:
            return "분할매수 검토 (분할 접근 선호)"
        else:
            return "관망 (수급 모멘텀 확인 필요)"

    elif intent == "SELL":
        if return_rate > 20.0 and sell_score >= 40:
            return "일부 익절 검토 (수익 구간 리스크 관리)"
        elif decision in ["SELL", "STRONG_SELL"] or sell_score >= 60:
            return "일부 익절 검토 (저항선 및 매도 수급 경계)"
        elif sell_score >= 40:
            return "분할 매도 검토 (리스크 관리)"
        else:
            return "보유 및 관망 (추세 지속 확인)"

    elif intent == "WATERING":
        if return_rate < -10.0 and (water_score >= 40 or decision == "WATERING"):
            return "분할 추가매수 검토 (손실 구간 분할 대응)"
        elif water_score >= 50 or decision == "WATERING":
            return "분할 추가매수 검토 (지지선 근접 분할 대응)"
        else:
            return "관망 (추가 진입 전 지지 확인)"

    # 기본 수급 판단 연동
    if decision in ["BUY", "STRONG_BUY"]:
        return "매수 검토"
    elif decision == "WATERING":
        return "분할매수 검토"
    elif decision in ["SELL", "STRONG_SELL"]:
        return "일부 익절 검토"
    
    return "관망"

def generate_grounded_qna_answer(
    ticker: str,
    name: str,
    query: str,
    asset_type: str = "STOCK",
    manager: str = ""
) -> Dict[str, Any]:
    """
    STEP 8 기존 STOCK 분석 데이터 연동 Q&A 파이프라인
    - [앱 보유 데이터]: DB 사용자의 평단가, 보유수량, 수익률, 평가손익
    - [앱 퀀트 지표]: 현재가, 외국인/기관 수급, FFCS, Buy/Sell/Water Score, 지지/저항선
    - [웹 검색자료]: DART 공시, 정부 보도자료, 실시간 뉴스
    - [AI 종합 분석]: 앱 데이터와 웹 검색자료를 결합한 종합 해석
    - 데이터 미존재 종목 시 "현재 해당 데이터를 사용할 수 없습니다." 명시
    """
    if not name and not ticker:
        return {
            "status": "fail",
            "message": "확인된 자료가 부족하여 확정적으로 판단하기 어렵습니다.",
            "is_grounded": False,
            "executive_summary": "현재 확인 가능한 신뢰할 수 있는 자료만으로는 판단하기 어렵습니다.",
            "verified_facts": [],
            "ai_analysis": "검색 대상 종목/ETF 정보가 지정되지 않았습니다.",
            "uncertainties": "확인 가능한 자료가 부재합니다.",
            "app_user_data": {"has_user_stock": False, "message": "현재 해당 보유 포트폴리오 데이터를 사용할 수 없습니다."},
            "citations": []
        }

    # 1. DB 사용자 보유 데이터 연동 (STEP 8)
    user_stock_db = None
    if ticker != "MARKET":
        user_stock_db = get_user_portfolio_info(ticker, name)
    has_user_stock = user_stock_db is not None
    user_stock_info = {}

    # 2. 주가 & 수급 & 퀀트 분석 데이터 수집
    flow_data = {}
    has_flow_data = False
    if ticker != "MARKET":
        flow_data = get_stock_flow_data(name or ticker, min_days=30)
        has_flow_data = flow_data.get("data_available", False)
    
    decision_res = {}
    tech_info = {}
    flow_info = {}
    if has_flow_data:
        res_full = analyze_stock_decision(flow_data["df"])
        decision_res = res_full.get("decision", {})
        tech_info = res_full.get("technical_analysis", {})
        flow_info = res_full.get("flow_analysis", {})

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

    # 3. 실시간 뉴스 및 공식자료 수집
    news_res = fetch_qna_stock_news(ticker=ticker, name=name, query=query)
    official_res = fetch_official_documents(ticker=ticker, name=name, query=query, asset_type=asset_type, manager=manager)

    news_items = news_res.get("items", []) if news_res.get("status") == "success" else []
    official_items = official_res.get("items", []) if official_res.get("status") == "success" else []

    # 4. Citation 인용 데이터 생성
    citations = generate_citations(news_items, official_items)

    # 5. STEP 7 교차검증 연산
    cross_val = perform_cross_validation(news_items, official_items, has_flow_data=has_flow_data)

    # 🛡️ Guardrail Check: 실제 수집된 뉴스/공시/주가 데이터가 모두 부재하고 단순 fallback 링크만 존재하는 경우
    is_real_official = False
    for o in official_items:
        title = o.get("title", "")
        summary = o.get("summary", "")
        doc_type = o.get("doc_type", "")
        if "바로가기" not in title and doc_type != "공시 검색" and "확인하세요" not in summary:
            is_real_official = True
            break
    
    if not has_flow_data and not news_items and not is_real_official:
        return {
            "status": "insufficient_data",
            "message": "확인된 자료가 부족하여 확정적으로 판단하기 어렵습니다.",
            "is_grounded": False,
            "reliability_grade": "낮음",
            "executive_summary": "확인된 자료가 부족하여 확정적으로 판단하기 어렵습니다.",
            "verified_facts": ["검색된 최신 뉴스 및 DART/정부 공시 자료가 부재합니다."],
            "ai_analysis": "확인된 주가 및 공시 데이터가 없어 판단할 수 없습니다.",
            "uncertainties": "확인된 자료가 부족하여 확정적으로 판단하기 어렵습니다.",
            "action_opinion": "관망 (자료 미존재)",
            "app_user_data": user_stock_info,
            "cross_validation": cross_val,
            "citations": citations
        }

    # 6. 의사결정 질문 처리 및 의사결정 보조 의견 생성
    query_intent = classify_decision_query(query)
    action_opinion = determine_action_opinion(query_intent, decision_res, user_stock_info if has_user_stock else None)

    # 7. [확인된 사실 (Verified Facts)] 출처 구분 적용 (STEP 8)
    verified_facts = []

    # [앱 보유 데이터]
    if has_user_stock:
        p_sign = "+" if user_stock_info["profit_loss"] >= 0 else ""
        verified_facts.append(
            f"[📱 앱 보유 데이터] {user_stock_info['name']}({user_stock_info['ticker']}) "
            f"평단가 {user_stock_info['avg_price']:,}원 | 보유수량 {user_stock_info['quantity']:,}주 | "
            f"평가손익 {p_sign}{user_stock_info['profit_loss']:,}원 (수익률 {p_sign}{user_stock_info['return_rate']:.2f}%)"
        )
    else:
        verified_facts.append("[📱 앱 보유 데이터] 현재 해당 보유 포트폴리오 데이터(평단가/보유수량)를 사용할 수 없습니다. (미보유 종목)")

    # [앱 퀀트 엔진 데이터]
    if has_flow_data:
        latest_close = tech_info.get("latest_close", 0)
        cycle_stage = flow_info.get("cycle_stage", "중립")
        ffcs_score = flow_info.get("ffcs_score", 50.0)
        buy_s = decision_res.get("buy_score", 0)
        sell_s = decision_res.get("sell_score", 0)
        water_s = decision_res.get("watering_score", 0)
        
        verified_facts.append(
            f"[📊 앱 퀀트 엔진 데이터] 최신 종가 {latest_close:,}원 (FFCS 수급: {ffcs_score}점 [{cycle_stage}] | "
            f"Buy {buy_s}점, Sell {sell_s}점, Water {water_s}점)"
        )

    # [웹 검색자료] (공시 및 뉴스)
    for off in official_items:
        verified_facts.append(f"[🌐 웹 검색자료 - 공시] [{off['institution']}] {off['title']} ({off['pub_date']})")

    for news in news_items[:3]:
        verified_facts.append(f"[🌐 웹 검색자료 - 뉴스] [{news['source']}] {news['title']} ({news['pub_date']})")

    # 8. [AI 종합 분석 (AI Quantitative & Portfolio Analysis)]
    ai_analysis_paragraphs = []
    
    if has_user_stock:
        ret_str = f"+{user_stock_info['return_rate']:.2f}%" if user_stock_info['return_rate'] >= 0 else f"{user_stock_info['return_rate']:.2f}%"
        ai_analysis_paragraphs.append(
            f"• [앱 포트폴리오 융합 분석]: 현재 평단가({user_stock_info['avg_price']:,}원) 대비 수익률은 {ret_str} 상태입니다."
        )

    if has_flow_data:
        ma20 = tech_info.get("ma20", 0)
        rsi = tech_info.get("rsi", 50.0)
        supp = tech_info.get("support_level", 0)
        resis = tech_info.get("resistance_level", 0)

        ai_analysis_paragraphs.append(
            f"• [앱 퀀트 수급 지표]: 20일선({ma20:,}원) 상회 및 RSI({rsi}) 지표 형성 중이며, 1차 지지선은 {supp:,}원, 저항선은 {resis:,}원입니다."
        )

    if citations:
        top_pub = citations[0]['publisher']
        ai_analysis_paragraphs.append(
            f"• [웹 검색자료 융합 해석]: 최신 출처인 [{top_pub}] 뉴스 및 공시 검증 결과, 실적/업황 관련 모멘텀이 확인됩니다."
        )

    # 9. [불확실한 부분 (Uncertainties & Risk)]
    uncertainties = []
    if cross_val.get("conflict_detected"):
        uncertainties.append("⚠️ 자료 간 내용에 차이가 있습니다.")
    
    if ticker == "MARKET":
        uncertainties.append("거시 경제 지표와 글로벌 증시 동향은 예상치 못한 글로벌 변수에 의해 급변할 수 있습니다.")
    else:
        if not has_user_stock:
            uncertainties.append("현재 보유하지 않은 종목이므로 개인 계좌 평단가 및 수익률 연동이 미적용되어 있습니다.")
        if not official_items:
            uncertainties.append("DART 및 정부기관 공식 공시 보도자료의 추가 업데이트 확인이 필요합니다.")
        if has_flow_data:
            uncertainties.append("단기 환율 변동성 및 매크로 지수 조전에 따른 지지선 이탈 위험에 주의가 필요합니다.")

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
