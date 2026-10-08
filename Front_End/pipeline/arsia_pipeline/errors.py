"""Structured, bounded errors crossing the deterministic import boundary."""


class NeedsInput(Exception):
    code = "evidence_needed"
    def __init__(self, message, questions=None, details=None):
        super().__init__(message)
        self.message = message
        self.questions = [message] if questions is None else questions
        self.details = details or {}


class BudgetExhausted(NeedsInput):
    code = "budget_exhausted"

    def __init__(self, message, details=None):
        super().__init__(message, [], details)


class UnsupportedCapability(NeedsInput):
    """A reviewed implementation is required, not another publisher quote."""
    def __init__(self, code, message):
        self.code = code
        super().__init__(message, [], {'blockers': [{
            'code': code, 'kind': 'unsupported_capability', 'message': message,
            'responsible_party': 'system',
            'resumable_when': 'A reviewed reader or execution plan supports this source representation.',
            'details': {},
        }]})


class AgentStalled(BudgetExhausted):
    code = "agent_stalled"


class ModelUnavailable(BudgetExhausted):
    code = "model_unavailable"


class ValidationFailure(Exception):
    def __init__(self, message, qa=None, details=None):
        super().__init__(message)
        self.message = message
        self.qa = qa or [{"code": "VALIDATION", "status": "block", "message": message}]
        self.details = details or {}


class ImportCancelled(Exception):
    pass
