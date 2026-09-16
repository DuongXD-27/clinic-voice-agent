from callbot.engine.types import CallState

TRANSITIONS: dict[CallState, set[CallState]] = {
    "AWAITING_IDENTITY": {
        "AWAITING_IDENTITY",
        "AWAITING_INTENT",
        "OFFERING_SLOTS",
        "CLOSING",
        "ENDED",
    },
    "AWAITING_INTENT": {
        "AWAITING_INTENT",
        "AWAITING_CONFIRMATION",
        "OFFERING_SLOTS",
        "CLOSING",
        "ENDED",
    },
    "AWAITING_CONFIRMATION": {
        "AWAITING_CONFIRMATION",
        "AWAITING_INTENT",
        "OFFERING_SLOTS",
        "CLOSING",
        "ENDED",
    },
    "OFFERING_SLOTS": {
        "OFFERING_SLOTS",
        "AWAITING_CONFIRMATION",
        "AWAITING_INTENT",
        "CLOSING",
        "ENDED",
    },
    "CLOSING": {"ENDED"},
    "ENDED": set(),
}


class IllegalTransition(Exception):
    pass


def ensure_transition(current: CallState, target: CallState) -> None:
    if target not in TRANSITIONS[current]:
        raise IllegalTransition(f"{current} -> {target}")
