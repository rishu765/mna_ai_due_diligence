"""Project 5 exception types."""


class DueDiligenceError(Exception):
    """Base exception for Project 5."""


class DomainValidationError(DueDiligenceError, ValueError):
    """A domain contract was constructed with invalid values."""


class SerializationError(DueDiligenceError, ValueError):
    """A serialized model payload is invalid or unsupported."""


class UnsupportedSchemaVersionError(SerializationError):
    """The payload uses a schema version this package does not support."""


class VdrIngestionError(DueDiligenceError):
    """A VDR source or manifest cannot be ingested."""


class DocumentParseError(VdrIngestionError):
    """A source document cannot be parsed."""


class UnsupportedDocumentError(DocumentParseError):
    """A source document uses an unsupported format."""


class IndexingError(DueDiligenceError):
    """The VDR index cannot accept the supplied chunks."""


class RetrievalError(DueDiligenceError):
    """A VDR retrieval request is invalid or cannot be completed."""
