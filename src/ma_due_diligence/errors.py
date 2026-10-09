"""Project 5 exception types."""


class DueDiligenceError(Exception):
    """Base exception for Project 5."""


class DomainValidationError(DueDiligenceError, ValueError):
    """A domain contract was constructed with invalid values."""


class SerializationError(DueDiligenceError, ValueError):
    """A serialized model payload is invalid or unsupported."""


class UnsupportedSchemaVersionError(SerializationError):
    """The payload uses a schema version this package does not support."""
