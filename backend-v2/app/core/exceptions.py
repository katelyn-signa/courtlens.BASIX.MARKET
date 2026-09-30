"""Shared application exceptions. Each maps to a predictable API error."""

from typing import Any, Optional


class AppError(Exception):
    status_code = 500
    code = "APP_ERROR"
    default_message = "Application error."

    def __init__(self, message: Optional[str] = None, *, details: Optional[Any] = None,
                 code: Optional[str] = None):
        self.message = message or self.default_message
        self.details = details
        if code:
            self.code = code
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class CaseNotFoundError(NotFoundError):
    code = "CASE_NOT_FOUND"
    default_message = "Case not found."


class DocumentNotFoundError(NotFoundError):
    code = "DOCUMENT_NOT_FOUND"
    default_message = "Document not found."


class AnalysisRunNotFoundError(NotFoundError):
    code = "ANALYSIS_RUN_NOT_FOUND"
    default_message = "Analysis run not found."


class ReviewNotFoundError(NotFoundError):
    code = "REVIEW_NOT_FOUND"
    default_message = "Review not found."


class InvalidStateTransitionError(AppError):
    status_code = 409
    code = "INVALID_STATE_TRANSITION"
    default_message = "That state transition is not allowed."


class InvalidInputError(AppError):
    status_code = 422
    code = "INVALID_INPUT"
    default_message = "Invalid input."


class DuplicateRequestError(AppError):
    status_code = 409
    code = "DUPLICATE_REQUEST"
    default_message = "A conflicting or duplicate request already exists."


class DatabaseIntegrityError(AppError):
    status_code = 409
    code = "DATABASE_INTEGRITY_ERROR"
    default_message = "The request conflicts with existing data."


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = "UNSUPPORTED_FILE_TYPE"
    default_message = "Unsupported file type."


class FileTooLargeError(AppError):
    status_code = 413
    code = "FILE_TOO_LARGE"
    default_message = "File exceeds the maximum permitted size."


class IntegrationConfigurationError(AppError):
    status_code = 503
    code = "MISSING_INTEGRATION_CONFIGURATION"
    default_message = "A required integration is not configured."


class AuthenticationError(AppError):
    status_code = 401
    code = "AUTHENTICATION_REQUIRED"
    default_message = "Missing or invalid credentials."


class PermissionDeniedError(AppError):
    status_code = 403
    code = "PERMISSION_DENIED"
    default_message = "You are not permitted to perform this action."


# ---- Agent errors (raised by, or on behalf of, Person 1/2/3 agents) -------------------

class AgentError(AppError):
    """Base class for agent failures. ``retryable`` drives the bounded retry policy."""

    status_code = 502
    code = "AGENT_ERROR"
    retryable = False

    def __init__(self, message: Optional[str] = None, *, details: Optional[Any] = None,
                 code: Optional[str] = None, retryable: Optional[bool] = None):
        super().__init__(message, details=details, code=code)
        if retryable is not None:
            self.retryable = retryable


class AgentNotConfiguredError(AgentError):
    status_code = 503
    code = "NOT_CONFIGURED"
    default_message = "No agent is registered for this stage."


class AgentUnavailableError(AgentError):
    status_code = 503
    code = "AGENT_UNAVAILABLE"
    default_message = "The agent is temporarily unavailable."
    retryable = True


class AgentTimeoutError(AgentError):
    status_code = 504
    code = "AGENT_TIMEOUT"
    default_message = "The agent did not respond in time."
    retryable = True


class AgentProcessingError(AgentError):
    code = "AGENT_PROCESSING_FAILED"
    default_message = "The agent failed while processing."


class AgentInvalidOutputError(AgentError):
    code = "AGENT_INVALID_OUTPUT"
    default_message = "The agent returned output that failed validation."
