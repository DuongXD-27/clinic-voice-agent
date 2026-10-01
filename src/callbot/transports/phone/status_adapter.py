"""Forward normalized dial results to the same core used by HTTP and LiveKit."""

from callbot.engine import BotAction, CallerInput, CallOrchestrator, PhoneStatus


class PhoneStatusAdapter:
    """A future provider maps its events to PhoneStatus and supplies the next turn.

    Core owns ordering, locking, policy, writes and terminal-call rejection. A duplicate
    terminal event raises CallEnded under the existing session retention policy.
    """

    def __init__(self, orchestrator: CallOrchestrator) -> None:
        self._orchestrator = orchestrator

    def handle_status(self, call_id: str, *, turn: int, status: PhoneStatus) -> BotAction:
        return self._orchestrator.handle_turn(call_id, CallerInput(turn=turn, phone_status=status))
