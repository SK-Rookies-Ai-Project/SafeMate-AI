from __future__ import annotations

import logging
from uuid import uuid4

import streamlit as st

from src.analyzers.file_parser import EmlValidationError, parse_eml
from src.analyzers.input_parser import (
    InputValidationError,
    create_input_digest,
    prepare_sms_input,
)
from src.config import MAX_SMS_CHARS
from src.services.openai_client import (
    MAX_CHAT_QUESTION_CHARS,
    OpenAISecurityChatClient,
)
from src.ui.components import (
    build_chat_suggestions,
    render_analysis_result,
    render_chat_sources,
    render_data_notice,
    render_preview,
)
from src.ui.mock_client import MockAnalysisClient, build_analysis_request


logger = logging.getLogger(__name__)

DEFAULT_STATE = {
    "input_type": "sms",
    "sms_text": "",
    "current_input_digest": None,
    "last_analyzed_digest": None,
    "analysis_status": "idle",
    "analysis_result": None,
    "analysis_error": None,
    "chat_messages": [],
    "chat_error": None,
    "uploader_key": 0,
}


def initialize_state() -> None:
    for key, value in DEFAULT_STATE.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_analysis_state() -> None:
    st.session_state.current_input_digest = None
    st.session_state.last_analyzed_digest = None
    st.session_state.analysis_status = "idle"
    st.session_state.analysis_result = None
    st.session_state.analysis_error = None
    clear_chat_state()


def clear_chat_state() -> None:
    st.session_state.chat_messages = []
    st.session_state.chat_error = None


def update_current_input_digest(digest: str | None) -> None:
    """Clear stale results whenever the selected input content changes."""
    previous_digest = st.session_state.current_input_digest
    if previous_digest != digest:
        st.session_state.last_analyzed_digest = None
        st.session_state.analysis_status = "idle"
        st.session_state.analysis_result = None
        st.session_state.analysis_error = None
        clear_chat_state()
    st.session_state.current_input_digest = digest


def handle_input_type_change() -> None:
    st.session_state.sms_text = ""
    st.session_state.uploader_key += 1
    clear_analysis_state()


def reset_all() -> None:
    current_type = st.session_state.get("input_type", "sms")
    uploader_key = st.session_state.get("uploader_key", 0) + 1
    for key, value in DEFAULT_STATE.items():
        st.session_state[key] = value
    st.session_state.input_type = current_type
    st.session_state.uploader_key = uploader_key


def parse_selected_input() -> tuple[dict | None, str | None]:
    if st.session_state.input_type == "sms":
        raw_text = st.session_state.sms_text
        if not raw_text.strip():
            update_current_input_digest(None)
            return None, None
        try:
            prepared = prepare_sms_input(raw_text)
        except InputValidationError as exc:
            update_current_input_digest(None)
            return None, str(exc)
        digest = create_input_digest("sms", raw_text.strip().encode("utf-8"))
        update_current_input_digest(digest)
        return prepared, None

    uploaded_file = st.session_state.get(
        f"eml_uploader_{st.session_state.uploader_key}"
    )
    if uploaded_file is None:
        update_current_input_digest(None)
        return None, None
    file_bytes = uploaded_file.getvalue()
    try:
        prepared = parse_eml(file_bytes, uploaded_file.name)
    except EmlValidationError as exc:
        update_current_input_digest(None)
        return None, str(exc)
    digest = create_input_digest("email", file_bytes)
    update_current_input_digest(digest)
    return prepared, None


def render_followup_chat() -> None:
    """Render chat only after the independent analysis stage has completed."""
    st.divider()
    st.subheader("분석 결과에 대해 SafeMate와 대화하기")
    st.caption(
        "1차 보안 판정은 이미 완료되었습니다. 아래 대화는 그 결과를 바꾸지 않고, "
        "등록된 보안 문서와 최신 웹 자료를 활용해 후속 대응을 돕습니다."
    )

    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                render_chat_sources(
                    message.get("citations", []),
                    message.get("tools_used", []),
                )

    if st.session_state.chat_error:
        st.error(st.session_state.chat_error)

    st.markdown("#### 이런 질문으로 시작해 보세요")
    suggestions = build_chat_suggestions(st.session_state.analysis_result)
    suggestion_columns = st.columns(2)
    suggested_question = None
    for index, suggestion in enumerate(suggestions):
        if suggestion_columns[index % 2].button(
            suggestion,
            key=f"chat_suggestion_{index}",
            use_container_width=True,
            help="클릭하면 바로 SafeMate에게 질문합니다.",
        ):
            suggested_question = suggestion

    typed_question = st.chat_input(
        "분석 결과에 대해 궁금한 점을 직접 입력하세요.",
        max_chars=MAX_CHAT_QUESTION_CHARS,
        key="security_followup_chat",
    )
    question = suggested_question or typed_question
    if not question:
        return

    st.session_state.chat_error = None
    previous_history = list(st.session_state.chat_messages)
    st.session_state.chat_messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    try:
        with st.chat_message("assistant"):
            with st.spinner("공식 자료와 최신 정보를 확인하고 있습니다."):
                reply = OpenAISecurityChatClient().ask(
                    question=question,
                    analysis_result=st.session_state.analysis_result,
                    history=previous_history,
                )
            st.markdown(reply["text"])
            render_chat_sources(reply["citations"], reply["tools_used"])
        st.session_state.chat_messages.append(
            {
                "role": "assistant",
                "content": reply["text"],
                "citations": reply["citations"],
                "tools_used": reply["tools_used"],
            }
        )
    except Exception as exc:
        logger.error("security_chat_failed exception_type=%s", type(exc).__name__)
        st.session_state.chat_error = (
            "후속 답변을 생성하지 못했습니다. API 설정과 네트워크 상태를 확인한 뒤 "
            "다시 질문해 주세요."
        )
        st.error(st.session_state.chat_error)


st.set_page_config(page_title="SafeMate AI", page_icon="🛡️", layout="wide")
initialize_state()
st.title("🛡️ SafeMate AI")
st.caption("의심스러운 문자·이메일·URL을 분석하는 교육용 보안 비서")
render_data_notice()

st.radio(
    "분석할 입력 유형을 선택하세요.",
    options=["sms", "email"],
    format_func=lambda value: {"sms": "문자 메시지", "email": "이메일 파일"}[value],
    horizontal=True,
    key="input_type",
    on_change=handle_input_type_change,
)

if st.session_state.input_type == "sms":
    st.text_area(
        "받은 문자 내용을 붙여넣어 주세요.",
        placeholder="문자 내용을 URL까지 포함하여 그대로 붙여넣어 주세요.",
        height=200,
        max_chars=MAX_SMS_CHARS,
        key="sms_text",
    )
else:
    st.file_uploader(
        "이메일 파일을 선택하세요.",
        type=["eml"],
        key=f"eml_uploader_{st.session_state.uploader_key}",
        help="확장자뿐 아니라 파일 크기, 내용 시그니처와 이메일 구조를 함께 검사합니다.",
    )

prepared_input, input_error = parse_selected_input()
if input_error:
    st.error(input_error)
if prepared_input:
    render_preview(prepared_input)

left, right = st.columns(2)
analyze_clicked = left.button(
    "분석 시작",
    type="primary",
    use_container_width=True,
    disabled=prepared_input is None or input_error is not None,
)
right.button(
    "초기화",
    use_container_width=True,
    on_click=reset_all,
)

if analyze_clicked and prepared_input is not None:
    request = build_analysis_request(prepared_input, f"analysis-{uuid4().hex[:12]}")
    st.session_state.analysis_status = "analyzing"
    st.session_state.analysis_error = None
    clear_chat_state()
    try:
        with st.spinner("입력 내용을 분석하고 있습니다."):
            result = MockAnalysisClient().analyze(request)
        st.session_state.analysis_result = result
        st.session_state.analysis_status = result.get("status", "success")
        st.session_state.last_analyzed_digest = st.session_state.current_input_digest
    except Exception as exc:
        logger.error(
            "analysis_failed request_id=%s exception_type=%s",
            request["request_id"],
            type(exc).__name__,
        )
        st.session_state.analysis_status = "error"
        st.session_state.analysis_result = None
        st.session_state.analysis_error = (
            "분석 중 오류가 발생했습니다. 입력을 유지한 채 다시 시도해 주세요."
        )

if st.session_state.analysis_error:
    st.error(st.session_state.analysis_error)
if st.session_state.analysis_result:
    render_analysis_result(st.session_state.analysis_result)
    render_followup_chat()
