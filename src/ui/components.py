"""Reusable Streamlit presentation components."""

from __future__ import annotations

import streamlit as st

from src.services.web_search import is_official_source_url
from src.ui.visualizations import (
    create_message_feature_chart,
    create_message_probability_chart,
    create_url_contribution_chart,
    create_url_feature_chart,
    create_url_risk_chart,
)


MAX_PREVIEW_URLS = 20

RISK_LABELS = {
    "low": "낮은 주의",
    "medium": "주의",
    "high": "높은 주의",
    "unknown": "판단 불가",
}


def build_chat_suggestions(result: dict) -> list[str]:
    """Create concise follow-up questions from the completed analysis."""
    risk_level = result.get("overall_risk", {}).get("level", "unknown")
    input_type = result.get("input_type", "sms")
    url_analyses = result.get("url_analysis", [])
    has_url = bool(url_analyses)
    has_href_mismatch = any(
        item.get("display_href_mismatch") for item in url_analyses
    )

    suggestions: list[str] = []
    if risk_level == "high":
        suggestions.extend(
            [
                "지금 가장 먼저 해야 할 일은 무엇인가요?",
                "이미 링크를 눌렀다면 어떻게 해야 하나요?",
            ]
        )
    elif risk_level == "low":
        suggestions.append("추가로 확인해야 할 위험 요소가 있나요?")
    else:
        suggestions.append("왜 주의가 필요한지 쉽게 설명해 주세요.")

    if has_href_mismatch:
        suggestions.append("표시 주소와 실제 연결 주소가 왜 다른가요?")
    elif has_url:
        suggestions.append("이 URL에서 어떤 위험 신호가 발견됐나요?")

    if input_type == "email":
        suggestions.append("이 이메일의 발신자를 안전하게 확인하는 방법은 무엇인가요?")
    else:
        suggestions.append("이 문자가 정상인지 확인하는 방법을 알려주세요.")

    suggestions.append("최신 유사 피해 사례와 공식 대응 방법을 찾아주세요.")
    return list(dict.fromkeys(suggestions))[:4]


def render_data_notice() -> None:
    st.info(
        "입력한 문자 또는 이메일 내용은 분석 과정에서 외부 AI 서비스로 "
        "전송될 수 있습니다. 실제 비밀번호·계좌정보 등 민감정보는 입력하지 마세요."
    )


def render_preview(prepared_input: dict) -> None:
    preview = prepared_input["preview"]
    st.subheader("입력 미리보기")
    if prepared_input["input_type"] == "email":
        first, second = st.columns(2)
        first.text_input("발신자", value=preview.get("from", ""), disabled=True)
        second.text_input("제목", value=preview.get("subject", ""), disabled=True)
    st.text_area("본문", value=preview.get("body", ""), height=220, disabled=True)
    render_url_candidates(preview.get("url_candidates", []))


def render_url_candidates(candidates: list[dict]) -> None:
    st.markdown("#### 추출된 URL 후보")
    if not candidates:
        st.caption("입력에서 URL이 발견되지 않았습니다. 본문 분석은 계속할 수 있습니다.")
        return
    visible_candidates = candidates[:MAX_PREVIEW_URLS]
    for index, candidate in enumerate(visible_candidates, start=1):
        st.code(f"{index}. {candidate['url']} ({candidate['source_type']})", language=None)
        if candidate.get("display_href_mismatch"):
            st.warning(
                "링크에 표시된 주소와 실제 연결 도메인이 다릅니다: "
                f"{candidate.get('displayed_domain', '확인 불가')} → "
                f"{candidate.get('destination_domain', '확인 불가')}"
            )
    hidden_count = len(candidates) - len(visible_candidates)
    if hidden_count:
        st.caption(
            f"화면이 지나치게 길어지는 것을 막기 위해 처음 {MAX_PREVIEW_URLS}개만 "
            f"표시합니다. 나머지 {hidden_count}개는 분석 요청에 포함됩니다."
        )


def render_analysis_result(result: dict) -> None:
    risk = result.get("overall_risk", {})
    level = risk.get("level", "unknown")
    score = risk.get("score")

    st.divider()
    st.subheader("분석 결과")
    first, second = st.columns(2)
    first.metric("종합 주의 수준", RISK_LABELS.get(level, level))
    second.metric("종합 점수", "분석 불가" if score is None else f"{score:.0%}")
    st.text(str(result.get("summary", "분석 요약이 없습니다.")))

    st.markdown("#### 왜 주의해야 하나요?")
    for reason in result.get("risk_reasons", [])[:5]:
        st.text(f"• {reason}")

    st.markdown("#### 지금 무엇을 해야 하나요?")
    for index, action in enumerate(result.get("recommended_actions", [])[:5], start=1):
        st.text(f"{index}. {action}")

    message_tab, url_tab, evidence_tab, limitation_tab = st.tabs(
        ["문자·이메일 분석", "URL 분석", "공식 출처", "분석 한계"]
    )

    with message_tab:
        _render_message_analysis(result.get("message_analysis", {}))
    with url_tab:
        _render_url_analysis(result)
    with evidence_tab:
        _render_evidence(result)
    with limitation_tab:
        _render_limitations(result)


def _render_message_analysis(analysis: dict) -> None:
    if not analysis:
        st.info("메시지 분석 결과가 없습니다.")
        return
    label = analysis.get("label", "unknown")
    display_label = {
        "normal": "정상",
        "phishing": "스팸·사기 의심",
        "unknown": "판단 불가",
    }.get(label, str(label))
    st.text(f"분류: {display_label}")
    probability = analysis.get("phishing_probability")
    st.text(
        "스팸·사기 통합 점수: "
        + ("분석 불가" if probability is None else f"{probability:.0%}")
    )
    st.caption(
        "광고성 스팸, 사기, 피싱을 포함한 통합 분류 결과이며 "
        "피싱만의 확률을 의미하지 않습니다."
    )
    probability_chart = create_message_probability_chart(analysis)
    if probability_chart is not None:
        st.pyplot(probability_chart, clear_figure=True)

    signals = analysis.get("signals", [])
    if signals:
        st.text("위험 신호: " + ", ".join(str(signal) for signal in signals))

    top_features = analysis.get("top_features", [])
    feature_chart = create_message_feature_chart(top_features)
    if feature_chart is not None:
        st.pyplot(feature_chart, clear_figure=True)
    elif "top_features" in analysis:
        st.caption("현재 모델에서는 단어별 기여도를 제공하지 않습니다.")
    st.text(f"모델 버전: {analysis.get('model_version', 'unknown')}")


def _render_url_analysis(result: dict) -> None:
    summary = result.get("url_analysis_summary", {})
    if summary:
        st.caption(
            f"후보 {summary.get('candidate_count', 0)}개 중 "
            f"{summary.get('analyzed_count', 0)}개 분석, "
            f"{summary.get('omitted_url_count', 0)}개 제외"
        )
    analyses = result.get("url_analysis", [])
    if not analyses:
        st.info("분석할 URL이 없습니다.")
        return

    risk_chart = create_url_risk_chart(analyses)
    if risk_chart is not None:
        st.pyplot(risk_chart, clear_figure=True)

    for analysis in analyses:
        with st.container(border=True):
            st.code(analysis.get("url", ""), language=None)
            st.text(f"판정: {analysis.get('label', 'unknown')}")
            score = analysis.get("risk_score")
            st.text(
                "위험 점수: "
                + ("분석 불가" if score is None else f"{score:.0%}")
            )
            if analysis.get("display_href_mismatch"):
                st.warning(
                    "표시 도메인과 실제 연결 도메인이 다릅니다: "
                    f"{analysis.get('displayed_domain', '확인 불가')} → "
                    f"{analysis.get('destination_domain', '확인 불가')}"
                )
            for signal in analysis.get("signals", []):
                st.text(f"• {signal}")

            features = analysis.get("features", [])
            feature_chart = create_url_feature_chart(features)
            contribution_chart = create_url_contribution_chart(features)
            if feature_chart is not None:
                st.pyplot(feature_chart, clear_figure=True)
            if contribution_chart is not None:
                st.pyplot(contribution_chart, clear_figure=True)
            elif features:
                st.caption("현재 모델에서는 URL 특징별 기여도를 제공하지 않습니다.")


def _render_evidence(result: dict) -> None:
    web_evidence = result.get("web_evidence", [])
    file_evidence = result.get("file_evidence", [])
    if not web_evidence and not file_evidence:
        st.info("현재 표시할 공식 출처가 없습니다.")
        return

    if web_evidence:
        st.markdown("#### 최신 위협 사례")
    for item in web_evidence:
        with st.container(border=True):
            st.text(str(item.get("title", "제목 없음")))
            organization = item.get("organization", "기관 정보 없음")
            published_at = item.get("published_at")
            st.text(
                organization
                if not published_at
                else f"{organization} · 게시일 {published_at}"
            )
            if item.get("summary"):
                st.text(str(item["summary"]))
            source_url = _safe_official_http_url(item.get("url"))
            if source_url:
                st.link_button("공식 출처 열기", source_url)
            elif item.get("url"):
                st.caption("검증된 공식 HTTPS 도메인이 아니어서 링크를 비활성화했습니다.")

    if file_evidence:
        st.markdown("#### 공식 대응 지침")
    for item in file_evidence:
        with st.container(border=True):
            st.text(str(item.get("title", "제목 없음")))
            st.text(str(item.get("organization", "기관 정보 없음")))
            location = _format_file_location(item)
            if location:
                st.text(f"문서 위치: {location}")
            if item.get("excerpt"):
                st.text(str(item["excerpt"]))
            external_url = _safe_official_http_url(item.get("external_url"))
            if external_url:
                st.link_button("외부 원문 열기", external_url)


def _safe_official_http_url(value: object) -> str | None:
    if not is_official_source_url(value):
        return None
    return str(value).strip()


def render_chat_sources(citations: list[dict], tools_used: list[str]) -> None:
    """Display tool activity and user-visible citations for a chat response."""
    labels = {
        "web_search": "웹 검색",
        "file_search": "보안 문서 검색",
    }
    visible_tools = [labels[item] for item in tools_used if item in labels]
    if visible_tools:
        st.caption("사용한 도구: " + " · ".join(visible_tools))

    if not citations:
        return
    with st.expander("참고 출처"):
        for citation in citations:
            if citation.get("type") == "url":
                url = _safe_official_http_url(citation.get("url"))
                if url:
                    st.text(str(citation.get("title", "공식 출처")))
                    st.link_button("공식 출처 열기", url)
            elif citation.get("type") == "file":
                st.text(str(citation.get("title", "등록된 보안 문서")))


def _format_file_location(item: dict) -> str:
    parts: list[str] = []
    if item.get("filename"):
        parts.append(str(item["filename"]))
    if item.get("page") is not None:
        parts.append(f"{item['page']}쪽")
    return " · ".join(parts)


def _render_limitations(result: dict) -> None:
    for limitation in result.get("limitations", []):
        st.warning("분석 한계")
        st.text(str(limitation.get("message", "분석 한계 정보가 없습니다.")))
    for error in result.get("errors", []):
        st.error("일부 분석 실패")
        st.text(str(error.get("message", "일부 분석에 실패했습니다.")))
