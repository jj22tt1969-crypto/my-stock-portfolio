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
