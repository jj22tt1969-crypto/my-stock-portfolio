import re
from typing import List, Dict, Any

def classify_item_sentiment(title: str, summary: str) -> str:
    """단일 뉴스/공시 항목의 감성(호재, 악재, 중립)을 감지합니다."""
    text = f"{title} {summary}"
    
    positive_kws = ["상승", "급등", "순매수", "영업이익 증가", "최고가", "수혜", "흑자", "수주", "호실적", "모멘텀", "상향", "돌파", "호재"]
    negative_kws = ["하락", "급락", "순매도", "적자", "리스크", "우려", "소송", "과징금", "위험", "하향", "악재", "이탈", "경고", "폭락", "부결"]
    
    pos_count = sum(1 for kw in positive_kws if kw in text)
    neg_count = sum(1 for kw in negative_kws if kw in text)
    
    if pos_count > neg_count and pos_count >= 1:
        return "POSITIVE"
    elif neg_count > pos_count and neg_count >= 1:
        return "NEGATIVE"
    
    return "NEUTRAL"

def perform_cross_validation(
    news_items: List[Dict[str, Any]],
    official_items: List[Dict[str, Any]],
    has_flow_data: bool = True
) -> Dict[str, Any]:
    """
    STEP 7 교차검증 및 신뢰도 평가 엔진
    - 수집된 독립 출처 간 감성 및 주장을 비교 평가
    - 상충(Conflict) 발생 시 '자료 간 내용에 차이가 있습니다.' 명시
    - 유효 자료 부족 시 '확인된 자료가 부족하여 확정적으로 판단하기 어렵습니다.' 명시
    - 3단계 최종 신뢰도 (높음, 중간, 낮음) 판정
    """
    # 1. 독립 출처 그룹 파악
    sources_by_type = {}
    valid_items = []
    
    # 공식자료 (DART, GOVERNMENT, OFFICIAL)
    for off in official_items:
        st = off.get("source_type", "OFFICIAL")
        if "바로가기" in off.get("title", "") and off.get("doc_type") == "공시 검색":
            continue  # Fallback 바로가기는 실증 자료 수집에서 제외
        valid_items.append(off)
        sources_by_type.setdefault(st, []).append(off)

    # 실시간 뉴스 (NEWS)
    for news in news_items:
        st = "NEWS"
        valid_items.append(news)
        sources_by_type.setdefault(st, []).append(news)

    total_valid_sources = len(valid_items)
    independent_source_types = list(sources_by_type.keys())
    
    # 2. 자료 부족 (Insufficient Data) 평가
    is_insufficient = False
    if total_valid_sources < 2 and not has_flow_data:
        is_insufficient = True

    # 3. 출처 간 감성 및 내용 상충 (Conflict) 교차 검증
    sentiments = [classify_item_sentiment(item.get("title", ""), item.get("summary", "")) for item in valid_items]
    pos_items = sum(1 for s in sentiments if s == "POSITIVE")
    neg_items = sum(1 for s in sentiments if s == "NEGATIVE")

    conflict_detected = False
    # 독립된 두 자료 이상에서 한쪽은 호재, 한쪽은 악재가 뚜렷하게 갈리는 경우
    if pos_items >= 1 and neg_items >= 1:
        conflict_detected = True

    # 4. 5대 평가 요소 점수 계산
    # 1) 출처 존재 (Existence)
    existence_score = min(total_valid_sources * 25, 100)
    
    # 2) 출처 신뢰도 (Reliability)
    high_rel_sources = sum(1 for st in independent_source_types if st in ["DART", "GOVERNMENT", "OFFICIAL"])
    reliability_score = 90 if high_rel_sources >= 1 else (70 if "NEWS" in independent_source_types else 40)
    
    # 3) 발행일 (Recency)
    recency_score = 95
    
    # 4) 관련성 (Relevance)
    relevance_score = 90
    
    # 5) 다른 출처와의 일치 여부 (Consistency)
    if conflict_detected:
        consistency_score = 30
    elif total_valid_sources >= 2:
        consistency_score = 95
    else:
        consistency_score = 60

    # 5. 3단계 최종 답변 신뢰도 (Reliability Grade) 판정: 높음 / 중간 / 낮음
    if is_insufficient:
        reliability_grade = "낮음"
        conflict_message = "확인된 자료가 부족하여 확정적으로 판단하기 어렵습니다."
    elif conflict_detected:
        reliability_grade = "낮음"  # 상충 발생 시 신뢰도 낮음
        conflict_message = "자료 간 내용에 차이가 있습니다."
    elif total_valid_sources >= 3 and (high_rel_sources >= 1 or len(independent_source_types) >= 2):
        reliability_grade = "높음"
        conflict_message = "독립 출처 교차검증 완료 (일치)"
    elif total_valid_sources >= 1:
        reliability_grade = "중간"
        conflict_message = "일부 독립 출처 교차검증 완료"
    else:
        reliability_grade = "낮음"
        conflict_message = "확인된 자료가 부족하여 확정적으로 판단하기 어렵습니다."

    return {
        "reliability_grade": reliability_grade,  # 높음, 중간, 낮음
        "conflict_detected": conflict_detected,
        "is_insufficient": is_insufficient,
        "conflict_message": conflict_message,
        "valid_source_count": total_valid_sources,
        "independent_type_count": len(independent_source_types),
        "scores": {
            "existence": existence_score,
            "reliability": reliability_score,
            "recency": recency_score,
            "relevance": relevance_score,
            "consistency": consistency_score
        }
    }


def analyze_cross_indicators(
    flow_analysis: Dict[str, Any],
    technical_analysis: Dict[str, Any],
    smart_flow_analysis: Dict[str, Any] = None,
    decision_analysis: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    3차-J FCS + RSI/RMI + Smart Money 종합분석 (Cross Analysis)
    
    - 기존 연산식/점수/신호 변형 0건
    - 지표 간 방향(상승/하락/중립) 및 일치/충돌 설명 문구 도출
    """
    if not flow_analysis or not technical_analysis:
        return {
            "available": False,
            "status_label": "데이터 부족 / 판단 보류",
            "status_color": "#94a3b8",
            "indicators": {},
            "reasons": ["수급 및 기술적 지표 수집 대기 중 (판단 보류)"]
        }

    ffcs = flow_analysis.get("ffcs_score", 50.0)
    rsi = technical_analysis.get("rsi", 50.0)
    rmi = technical_analysis.get("rmi", 50.0)
    
    smart_available = smart_flow_analysis.get("available", False) if smart_flow_analysis else False
    smart_score = smart_flow_analysis.get("score") if smart_available else None
    
    def get_direction(val, high_th=55.0, low_th=45.0):
        if val is None: return "NEUTRAL", "➡️ 중립"
        if val >= high_th: return "UP", "⬆️ 상승"
        elif val <= low_th: return "DOWN", "⬇️ 하락"
        return "NEUTRAL", "➡️ 중립"

    fcs_dir, fcs_dir_label = get_direction(ffcs, 55.0, 45.0)
    rsi_dir, rsi_dir_label = get_direction(rsi, 55.0, 45.0)
    rmi_dir, rmi_dir_label = get_direction(rmi, 55.0, 45.0)
    smart_dir, smart_dir_label = get_direction(smart_score, 60.0, 40.0) if smart_score is not None else ("NEUTRAL", "➡️ 중립")

    reasons = []
    
    price_change_pct = technical_analysis.get("price_change_pct", 0.0)
    is_contrarian = (price_change_pct < -2.0 and smart_score is not None and smart_score >= 60.0)
    is_smart_risk = (ffcs >= 55.0 and smart_score is not None and smart_score < 35.0)

    is_all_pos = (fcs_dir == "UP" and rsi_dir == "UP" and rmi_dir == "UP" and (smart_dir == "UP" or smart_score is None))
    is_all_neg = (fcs_dir == "DOWN" and rsi_dir == "DOWN" and rmi_dir == "DOWN" and (smart_dir == "DOWN" or smart_score is None))

    dirs = [fcs_dir, rsi_dir, rmi_dir]
    if smart_score is not None: dirs.append(smart_dir)
    has_up = "UP" in dirs
    has_down = "DOWN" in dirs
    is_conflict = (has_up and has_down)

    if is_contrarian:
        status_label = "⚡ 역발상 수급 유입 가능성"
        status_color = "#3b82f6"
        reasons.append("주가 하락에도 큰손 수급 유입 포착 (단기 반등 유효 구간)")
    elif is_smart_risk:
        status_label = "⚠️ 기존 신호 대비 수급 위험 증가"
        status_color = "#f97316"
        reasons.append("기존 FCS 수급은 긍정적이나 큰손 세부 수급(Smart Money) 지지 부재 (수급 경계 필요)")
    elif is_all_pos:
        status_label = "🟢 기술·수급 동시 긍정"
        status_color = "#22c55e"
        reasons.append("FCS 수급, 기술적 지표(RSI/RMI), 큰손 수급이 모두 긍정적 방향 (추세 지속 가능성 우수)")
    elif is_all_neg:
        status_label = "🔴 기술·수급 동시 약화"
        status_color = "#ef4444"
        reasons.append("FCS 수급, 기술적 지표, 큰손 자금이 동반 하향 약화 (위험 관리 및 관망 필요)")
    elif is_conflict:
        status_label = "⚠️ 지표 간 신호 충돌 / 추가 확인 필요"
        status_color = "#eab308"
        reasons.append("수급 지표와 기술적 차트 지표 간 방향성 상충 (단기 혼조세, 추세 확정 전 신중 접근)")
    else:
        status_label = "🟡 지표 중립 / 혼조"
        status_color = "#94a3b8"
        reasons.append("주요 수급 및 기술 지표 평이 수준 유지")

    return {
        "available": True,
        "status_label": status_label,
        "status_color": status_color,
        "indicators": {
            "ffcs": {"val": ffcs, "dir": fcs_dir, "label": fcs_dir_label},
            "rsi": {"val": rsi, "dir": rsi_dir, "label": rsi_dir_label},
            "rmi": {"val": rmi, "dir": rmi_dir, "label": rmi_dir_label},
            "smart_money": {"val": smart_score, "dir": smart_dir, "label": smart_dir_label if smart_available else "미확인"}
        },
        "reasons": reasons
    }
