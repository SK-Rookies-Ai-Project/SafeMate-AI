"""Reusable Streamlit presentation components."""

from __future__ import annotations

from urllib.parse import urlparse

import streamlit as st


MAX_PREVIEW_URLS = 20

RISK_LABELS = {
    "low": "낮은 주의",
    "medium": "주의",
    "high": "높은 주의",
    "unknown": "판단 불가",
}


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
    st.write(result.get("summary", "분석 요약이 없습니다."))

    st.markdown("#### 왜 주의해야 하나요?")
    for reason in result.get("risk_reasons", [])[:5]:
        st.markdown(f"- {reason}")

    st.markdown("#### 지금 무엇을 해야 하나요?")
    for index, action in enumerate(result.get("recommended_actions", [])[:5], start=1):
        st.markdown(f"{index}. {action}")

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
    st.write(f"분류: `{analysis.get('label', 'unknown')}`")
    probability = analysis.get("phishing_probability")
    st.write("피싱 확률:", "분석 불가" if probability is None else f"{probability:.0%}")
    signals = analysis.get("signals", [])
    if signals:
        st.write("위험 신호:", ", ".join(signals))
    st.caption(f"모델 버전: {analysis.get('model_version', 'unknown')}")


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
    for analysis in analyses:
        with st.container(border=True):
            st.code(analysis.get("url", ""), language=None)
            st.write(f"판정: `{analysis.get('label', 'unknown')}`")
            score = analysis.get("risk_score")
            st.write("위험 점수:", "분석 불가" if score is None else f"{score:.0%}")
            for signal in analysis.get("signals", []):
                st.markdown(f"- {signal}")


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
            st.markdown(f"**{item.get('title', '제목 없음')}**")
            organization = item.get("organization", "기관 정보 없음")
            published_at = item.get("published_at")
            st.caption(
                organization
                if not published_at
                else f"{organization} · 게시일 {published_at}"
            )
            if item.get("summary"):
                st.write(item["summary"])
            source_url = _safe_http_url(item.get("url"))
            if source_url:
                st.link_button("공식 출처 열기", source_url)
            elif item.get("url"):
                st.caption("안전한 HTTP/HTTPS 주소가 아니어서 링크를 비활성화했습니다.")

    if file_evidence:
        st.markdown("#### 공식 대응 지침")
    for item in file_evidence:
        with st.container(border=True):
            st.markdown(f"**{item.get('title', '제목 없음')}**")
            st.caption(item.get("organization", "기관 정보 없음"))
            location = _format_file_location(item)
            if location:
                st.write(f"문서 위치: {location}")
            if item.get("excerpt"):
                st.markdown(f"> {item['excerpt']}")
            external_url = _safe_http_url(item.get("external_url"))
            if external_url:
                st.link_button("외부 원문 열기", external_url)


def _safe_http_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value.strip()


def _format_file_location(item: dict) -> str:
    parts: list[str] = []
    if item.get("filename"):
        parts.append(str(item["filename"]))
    if item.get("page") is not None:
        parts.append(f"{item['page']}쪽")
    return " · ".join(parts)


def _render_limitations(result: dict) -> None:
    for limitation in result.get("limitations", []):
        st.warning(limitation.get("message", "분석 한계 정보가 없습니다."))
    for error in result.get("errors", []):
        st.error(error.get("message", "일부 분석에 실패했습니다."))
