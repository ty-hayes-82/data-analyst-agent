class SemanticError(Exception):
    """Base class for all semantic layer exceptions."""
    pass

class ContractValidationError(SemanticError):
    """Raised when a DatasetContract fails Pydantic validation or logic checks."""
    pass

class SchemaColumnMismatchError(SemanticError):
    """Raised when a DataFrame is missing columns required by the DatasetContract."""
    pass

class QualityGateError(SemanticError):
    """Raised when the DataQualityGate encounters a terminal error during validation."""
    pass
