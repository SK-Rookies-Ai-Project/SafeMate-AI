"""Pure host policy for the forced SafeMate security-action function."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping

FUNCTION_NAME = "build_security_action_plan"
POLICY_VERSION = "2026-07-17.1"
SCHEMA_VERSION = "safemate.action_plan.v1"
MAX_ACTION_PLAN_BYTES = 4 * 1024
MAX_ITEM_CHARACTERS = 240
MAX_RESPONSE_OUTPUT_ITEMS = 16
_MAX_REASONING_BYTES = 32 * 1024
_EVENT_PATTERNS = {
    "clicked": re.compile(r"\b(?:i|we)\s+(?:clicked|click)\b|(?:저|제가|나는|내가).{0,12}(?:클릭|눌렀)", re.IGNORECASE),
    "credentials_entered": re.compile(r"\b(?:i|we)\s+(?:entered|typed|submitted).{0,40}\b(?:password|credential|code)\b|(?:저|제가|나는|내가).{0,24}(?:비밀번호|인증.{0,4}코드).{0,16}(?:입력|보냈)", re.IGNORECASE),
    "payment_sent": re.compile(r"\b(?:i|we)\s+(?:paid|sent|transferred).{0,40}\b(?:money|payment|funds)\b|(?:저|제가|나는|내가).{0,24}(?:송금|결제|돈).{0,16}(?:했|보냈)", re.IGNORECASE),
    "file_opened": re.compile(r"\b(?:i|we)\s+(?:opened|downloaded).{0,40}\b(?:file|attachment)\b|(?:저|제가|나는|내가).{0,24}(?:파일|첨부).{0,16}(?:열었|다운로드)", re.IGNORECASE),
}
_EVENT_NEGATIONS = {
    "clicked": re.compile(r"\b(?:did not|didn't|never|not)\s+(?:click|clicked)\b|(?:클릭|눌렀).{0,12}(?:않았|아니)", re.IGNORECASE),
    "credentials_entered": re.compile(r"\b(?:did not|didn't|never|not)\s+(?:enter|entered|type|typed|submit|submitted).{0,40}\b(?:password|credential|code)\b|\bnot\s+(?:my\s+)?(?:password|credential|code)\b|(?:비밀번호|인증.{0,4}코드).{0,16}(?:않았|아니)", re.IGNORECASE),
    "payment_sent": re.compile(r"\b(?:did not|didn't|never|not)\s+(?:pay|paid|send|sent|transfer|transferred).{0,40}\b(?:money|payment|funds)\b|\bnot\s+(?:any\s+)?(?:money|payment|funds)\b|(?:송금|결제|돈).{0,16}(?:않았|아니)", re.IGNORECASE),
    "file_opened": re.compile(r"\b(?:did not|didn't|never|not)\s+(?:open|opened|download|downloaded).{0,40}\b(?:file|attachment)\b|\bnot\s+(?:the\s+)?(?:file|attachment)\b|(?:파일|첨부).{0,16}(?:않았|아니)", re.IGNORECASE),
}
_NO_INTERACTION_DENIAL = re.compile(
    r"\b(?:i|we)\s+(?:did\s+not|didn't|never)\s+(?:interact(?:ed)?|engag(?:e|ed))\b"
    r"|(?:저는|저|제가|나는|내가).{0,24}상호작용.{0,12}"
    r"(?:하지\s*않았|안\s*했|않았|안했다)",
    re.IGNORECASE,
)
_NO_INTERACTION_EXCLUSIONS = re.compile(
    r"""["“”`]|(?<!n)'(?!t)|(?:\b(?:someone|they|he|she|friend|customer|victim|other person)\b|다른 사람|누군가|그 사람|지인|고객|피해자)|(?:\b(?:maybe|might|unsure|uncertain|perhaps)\b|모르겠|아마|가능성)|(?:ignore (?:previous|the above)|system prompt|instruction|프롬프트|지시를 무시)""",
    re.IGNORECASE,
)
_EXCLUSIONS = re.compile(
    r"""["“”'`]|(?:\b(?:someone|they|he|she|friend|customer|victim|other person)\b|다른 사람|누군가|그 사람|지인|고객|피해자)|(?:\b(?:did not|didn't|never|not click)\b|않았|아니|없었)|(?:\b(?:maybe|might|unsure|uncertain|perhaps)\b|모르겠|아마|가능성)|(?:ignore (?:previous|the above)|system prompt|instruction|프롬프트|지시를 무시)""",
    re.IGNORECASE,
)

USER_GOALS = (
    "verify_sender",
    "contain_account",
    "payment_fraud",
    "malware_device",
    "reporting",
    "general",
)
OBSERVED_EVENTS = (
    "no_interaction",
    "clicked",
    "credentials_entered",
    "payment_sent",
    "file_opened",
    "unknown",
)
RISK_LEVELS = ("low", "medium", "high", "unknown")

CUSTOM_FUNCTION_TOOL = {
    "type": "function",
    "name": FUNCTION_NAME,
    "description": (
        "Classify only the user's stated follow-up goal and post-analysis interaction "
        "event so the host can render bounded security actions without changing "
        "first-stage classification."
    ),
    "strict": True,
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["user_goal", "observed_event", "event_explicitly_reported"],
        "properties": {
            "user_goal": {"type": "string", "enum": list(USER_GOALS)},
            "observed_event": {"type": "string", "enum": list(OBSERVED_EVENTS)},
            "event_explicitly_reported": {"type": "boolean"},
        },
    },
}


@dataclass(frozen=True)
class ActionRequest:
    """Validated, model-extracted context with no free-form user text."""

    user_goal: str
    observed_event: str
    event_explicitly_reported: bool
    safety_escalated_by_host: bool = False
    def __post_init__(self) -> None:
        if self.user_goal not in USER_GOALS or self.observed_event not in OBSERVED_EVENTS:
            raise ValueError("invalid action request")
        if type(self.event_explicitly_reported) is not bool:
            raise ValueError("event_explicitly_reported must be a boolean")
        if type(self.safety_escalated_by_host) is not bool:
            raise ValueError("safety_escalated_by_host must be a boolean")


@dataclass(frozen=True)
class ActionContext:
    """The only first-stage projection visible to the dispatcher."""

    request_id: str | None
    risk_level: str
    def __post_init__(self) -> None:
        if self.request_id is not None and (
            not isinstance(self.request_id, str) or len(self.request_id) > 128
        ):
            raise ValueError("request_id must be null or a string of at most 128 characters")
        if self.risk_level not in RISK_LEVELS:
            raise ValueError("invalid risk_level")


def validate_action_arguments(arguments: Mapping[str, Any]) -> ActionRequest:
    """Validate the exact closed custom-function argument object."""
    if not isinstance(arguments, Mapping):
        raise ValueError("security action arguments must be an object")
    expected = {"user_goal", "observed_event", "event_explicitly_reported"}
    if set(arguments) != expected:
        raise ValueError("security action arguments must contain only required fields")

    goal = arguments["user_goal"]
    event = arguments["observed_event"]
    explicitly_reported = arguments["event_explicitly_reported"]
    if not isinstance(goal, str) or goal not in USER_GOALS:
        raise ValueError("invalid user_goal")
    if not isinstance(event, str) or event not in OBSERVED_EVENTS:
        raise ValueError("invalid observed_event")
    if type(explicitly_reported) is not bool:
        raise ValueError("event_explicitly_reported must be a boolean")

    # An unreported extracted event is not evidence.  The caller must apply any
    # phrase/negation recognition before validation and only pass a confident event.
    if not explicitly_reported:
        event = "unknown"
    return ActionRequest(goal, event, explicitly_reported)
def normalize_reported_event(
    request: ActionRequest, question: Any, history: Any
) -> ActionRequest:
    """Accept an event only when one retained user statement reports it explicitly."""
    if not isinstance(request, ActionRequest):
        raise TypeError("request must be an ActionRequest")
    if not request.event_explicitly_reported:
        return ActionRequest(request.user_goal, "unknown", False)
    statements = [question] if isinstance(question, str) else []
    if isinstance(history, list):
        statements.extend(
            item["content"] for item in history
            if isinstance(item, Mapping) and item.get("role") == "user"
            and isinstance(item.get("content"), str)
        )
    if request.observed_event == "no_interaction":
        if any(_explicit_no_interaction(statement) for statement in statements):
            return request
        return ActionRequest(request.user_goal, "unknown", False)
    pattern = _EVENT_PATTERNS.get(request.observed_event)
    negation = _EVENT_NEGATIONS.get(request.observed_event)
    clauses = (
        clause.strip()
        for statement in statements
        if _EXCLUSIONS.search(statement) is None
        for clause in re.split(r"[,;.!?\n]+", statement)
    )
    if pattern is None or negation is None or not any(
        clause and negation.search(clause) is None and pattern.search(clause)
        for clause in clauses
    ):
        return ActionRequest(request.user_goal, "unknown", False)
    return request
def _explicit_no_interaction(statement: str) -> bool:
    if _NO_INTERACTION_EXCLUSIONS.search(statement) is not None:
        return False
    if _NO_INTERACTION_DENIAL.search(statement) is None:
        return False
    return not any(pattern.search(statement) for pattern in _EVENT_PATTERNS.values())



def validate_phase_one_response(response: Any) -> tuple[list[dict[str, str]], Any] | None:
    """Validate the dependency-free strict phase-one response/replay contract."""
    if _response_value(response, "status") != "completed":
        return None
    output = _response_value(response, "output", [])
    if not isinstance(output, list) or not output or len(output) > MAX_RESPONSE_OUTPUT_ITEMS:
        return None
    calls: list[Any] = []
    replay: list[dict[str, str]] = []
    for item in output:
        kind = _response_value(item, "type")
        if kind == "reasoning":
            encrypted = _bounded_response_string(
                _response_value(item, "encrypted_content"), _MAX_REASONING_BYTES
            )
            if encrypted is None:
                return None
            replay.append({"type": "reasoning", "encrypted_content": encrypted})
        elif kind == "function_call":
            call_id = _bounded_response_string(_response_value(item, "call_id"), 256)
            arguments = _bounded_response_string(_response_value(item, "arguments"), 1024)
            if (
                _response_value(item, "name") != FUNCTION_NAME
                or _response_value(item, "status") != "completed"
                or call_id is None
                or arguments is None
            ):
                return None
            calls.append(item)
            replay.append(
                {"type": "function_call", "call_id": call_id, "name": FUNCTION_NAME, "arguments": arguments}
            )
        else:
            return None
    return (replay, calls[0]) if len(calls) == 1 else None


def _response_value(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _bounded_response_string(value: Any, maximum_bytes: int) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return value if len(value.encode("utf-8")) <= maximum_bytes else None
    except UnicodeEncodeError:
        return None


def validate_action_context(request_id: str | None, risk_level: str) -> ActionContext:
    """Validate and freeze the small immutable first-stage projection."""
    return ActionContext(request_id=request_id, risk_level=risk_level)




class SecurityActionDispatcher:
    """One-use allowlisted dispatcher for one accepted function call."""

    def __init__(self, context: ActionContext) -> None:
        if not isinstance(context, ActionContext):
            raise TypeError("dispatcher requires validated ActionContext")
        self._context = context
        self._dispatched = False

    @property
    def dispatched(self) -> bool:
        return self._dispatched

    def dispatch(self, function_name: str, request: ActionRequest) -> dict[str, Any]:
        if self._dispatched:
            raise RuntimeError("security action dispatch already executed")
        if function_name != FUNCTION_NAME:
            raise ValueError("function is not allowlisted")
        if not isinstance(request, ActionRequest):
            raise TypeError("dispatcher requires validated ActionRequest")
        plan = _build_plan(request, self._context)
        canonical_action_plan_json(plan)
        self._dispatched = True
        return plan


def build_security_action_plan(
    arguments: Mapping[str, Any], request_id: str | None, risk_level: str
) -> dict[str, Any]:
    """Validate and dispatch one standalone plan for a single function-call turn."""
    request = validate_action_arguments(arguments)
    context = validate_action_context(request_id, risk_level)
    return SecurityActionDispatcher(context).dispatch(FUNCTION_NAME, request)


def canonical_action_plan_json(plan: Mapping[str, Any]) -> str:
    """Return the bounded canonical representation used for function_call_output."""
    _validate_plan_bounds(plan)
    encoded = json.dumps(plan, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > MAX_ACTION_PLAN_BYTES:
        raise ValueError("action plan exceeds canonical byte limit")
    return encoded


def _build_plan(request: ActionRequest, context: ActionContext) -> dict[str, Any]:
    do_now = [_risk_action(context.risk_level)]
    avoid = [{"id": "avoid-untrusted-contact", "text": "의심스러운 메시지에 포함된 링크·전화번호를 사용하거나 답장 지시를 따르지 마세요."}]
    escalate = [{"id": "escalate-uncertainty", "text": "안전하게 확인할 수 없으면 공식 고객센터나 보안 담당 부서에 문의하세요."}]
    limitations: list[str] = []

    event_actions, event_escalations = _event_policy(request.observed_event)
    do_now.extend(event_actions)
    escalate.extend(event_escalations)
    goal_actions, goal_avoid = _goal_policy(request.user_goal)
    do_now.extend(goal_actions)
    avoid.extend(goal_avoid)

    if request.observed_event == "unknown":
        limitations.append("상호작용 여부가 확인되지 않았습니다. 계정·결제·기기 상태는 공식 채널에서만 확인하세요.")
    if context.risk_level == "unknown":
        limitations.append("고정된 1차 위험 수준을 판단할 수 없습니다. 적용 가능한 가장 신중한 대응을 선택하세요.")

    _validate_policy_lengths(do_now, avoid, escalate, limitations)
    for priority, item in enumerate(do_now, start=1):
        item["priority"] = priority

    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "classification_unchanged": True,
        "request_id": context.request_id,
        "risk_level": context.risk_level,
        "user_context": {
            "goal": request.user_goal,
            "observed_event": request.observed_event,
            "source": "user_reported_unverified" if request.event_explicitly_reported else "unknown",
            "safety_escalated_by_host": request.safety_escalated_by_host,
        },
        "do_now": do_now,
        "avoid": avoid,
        "escalate_when": escalate,
        "limitations": limitations,
    }


def _risk_action(risk_level: str) -> dict[str, str]:
    text_by_risk = {
        "low": "이미 알고 있는 공식 연락처로 발신자나 요청 내용을 별도로 확인하세요.",
        "medium": "추가 조치 전에 공식 웹사이트나 앱에서 관련 계정을 확인하세요.",
        "high": "공식 채널에서 계정·결제·기기를 먼저 확인하고, 의심스러운 상대와의 상호작용은 중단하세요.",
        "unknown": "정보를 제공하거나 조치하기 전에 공식 채널에서 상황을 확인하세요.",
    }
    return {"id": f"risk-{risk_level}", "text": text_by_risk[risk_level]}


def _event_policy(event: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    policies = {
        "no_interaction": ([{"id": "event-no-interaction", "text": "신고를 위해 메시지는 보관하되, 링크나 첨부 파일은 열지 마세요."}], []),
        "clicked": ([{"id": "event-clicked", "text": "페이지를 닫고 공식 웹사이트나 앱에서 계정을 확인하세요."}], [{"id": "escalate-clicked", "text": "정보 입력, 다운로드, 계정 변경을 요구한 페이지였다면 신속히 공식 채널에 문의하세요."}]),
        "credentials_entered": ([{"id": "event-credentials", "text": "공식 서비스에서 해당 비밀번호를 변경하고, 가능하면 다중 인증을 설정하세요."}], [{"id": "escalate-credentials", "text": "자격 증명을 입력했거나 낯선 계정 활동이 보이면 즉시 공식 고객센터나 보안 담당 부서에 문의하세요."}]),
        "payment_sent": ([{"id": "event-payment", "text": "공식 번호로 은행이나 결제 사업자에 연락해 피해를 신고하고 결제 중단 가능 여부를 확인하세요."}], [{"id": "escalate-payment", "text": "금전, 카드 정보, 송금이 관련됐을 수 있으면 즉시 금융기관에 문의하세요."}]),
        "file_opened": ([{"id": "event-file", "text": "안전한 경우 기기의 네트워크 연결을 끊고 승인된 보안 검사 도구를 사용하거나 IT 보안 담당자에게 문의하세요."}], [{"id": "escalate-file", "text": "파일을 열었거나 소프트웨어 설치·기기 설정 변경이 있었다면 즉시 보안 담당 부서에 문의하세요."}]),
        "unknown": ([{"id": "event-unknown", "text": "계정 활동, 결제 내역, 기기 보안 상태는 공식 채널에서만 확인하세요."}], []),
    }
    return policies[event]


def _goal_policy(goal: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    policies = {
        "verify_sender": ([{"id": "goal-verify-sender", "text": "알고 있는 공식 웹사이트·앱 또는 직접 찾은 공식 전화번호로 발신자를 확인하세요."}], []),
        "contain_account": ([{"id": "goal-contain-account", "text": "공식 계정 설정에서 로그인 기록과 활성 세션을 확인하고, 모르는 세션은 해제하세요."}], [{"id": "avoid-shared-credentials", "text": "비밀번호, 복구 코드, 다중 인증 코드를 재사용하거나 누구에게도 알려주지 마세요."}]),
        "payment_fraud": ([{"id": "goal-payment-fraud", "text": "공식 은행·결제 앱에서 최근 거래를 확인하고, 사업자에 전달할 거래 정보를 보관하세요."}], [{"id": "avoid-payment-followup", "text": "송금 관련 연락을 받더라도 추가 결제를 하거나 인증 코드를 알려주지 마세요."}]),
        "malware_device": ([{"id": "goal-malware-device", "text": "승인된 단말 보안 도구 또는 IT·보안 담당자를 통해 기기를 점검하세요."}], [{"id": "avoid-device-login", "text": "점검이 끝날 때까지 해당 기기에서 민감한 계정에 로그인하지 마세요."}]),
        "reporting": ([{"id": "goal-reporting", "text": "적절한 공식 신고 채널에 제출할 수 있도록 메시지, 발신자 정보, 관련 시각을 보관하세요."}], []),
        "general": ([{"id": "goal-general", "text": "발생한 일을 기록하고, 주장된 요청은 직접 찾은 공식 연락처로 확인하세요."}], []),
    }
    return policies[goal]


def _validate_policy_lengths(
    do_now: list[dict[str, str]],
    avoid: list[dict[str, str]],
    escalate: list[dict[str, str]],
    limitations: list[str],
) -> None:
    if not (
        1 <= len(do_now) <= 5
        and 1 <= len(avoid) <= 3
        and 1 <= len(escalate) <= 4
        and len(limitations) <= 2
    ):
        raise ValueError("action policy exceeds closed schema bounds")


def _validate_plan_bounds(plan: Mapping[str, Any]) -> None:
    expected = {
        "schema_version", "policy_version", "classification_unchanged", "request_id",
        "risk_level", "user_context", "do_now", "avoid", "escalate_when", "limitations",
    }
    if not isinstance(plan, Mapping) or set(plan) != expected:
        raise ValueError("invalid action plan schema")
    if (
        plan["schema_version"] != SCHEMA_VERSION
        or plan["policy_version"] != POLICY_VERSION
        or plan["classification_unchanged"] is not True
        or plan["risk_level"] not in RISK_LEVELS
        or (
            plan["request_id"] is not None
            and (not isinstance(plan["request_id"], str) or len(plan["request_id"]) > 128)
        )
    ):
        raise ValueError("invalid action plan schema")
    context = plan["user_context"]
    if (
        not isinstance(context, Mapping)
        or set(context) != {"goal", "observed_event", "source", "safety_escalated_by_host"}
        or context["goal"] not in USER_GOALS
        or context["observed_event"] not in OBSERVED_EVENTS
        or context["source"] not in {"user_reported_unverified", "unknown"}
        or type(context["safety_escalated_by_host"]) is not bool
    ):
        raise ValueError("invalid action plan context")
    for field, minimum, maximum in (("do_now", 1, 5), ("avoid", 1, 3), ("escalate_when", 1, 4)):
        values = plan[field]
        if not isinstance(values, list) or not minimum <= len(values) <= maximum:
            raise ValueError(f"invalid {field} bounds")
        for priority, value in enumerate(values, start=1):
            required = {"id", "text", "priority"} if field == "do_now" else {"id", "text"}
            if not isinstance(value, Mapping) or set(value) != required:
                raise ValueError(f"invalid {field} item")
            if (
                not isinstance(value["id"], str)
                or not value["id"]
                or not isinstance(value["text"], str)
                or not value["text"]
                or len(value["text"]) > MAX_ITEM_CHARACTERS
                or (field == "do_now" and value["priority"] != priority)
            ):
                raise ValueError(f"invalid {field} item")
    limitations = plan["limitations"]
    if (
        not isinstance(limitations, list)
        or len(limitations) > 2
        or any(
            not isinstance(value, str) or not value or len(value) > MAX_ITEM_CHARACTERS
            for value in limitations
        )
    ):
        raise ValueError("invalid limitations")
