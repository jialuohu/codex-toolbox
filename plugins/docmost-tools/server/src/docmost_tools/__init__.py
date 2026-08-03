"""Foundation types for the Docmost MCP plugin."""

__version__ = "0.1.0"

from .config import ApiProfile, DocmostSettings, WriteProfile
from .models import ErrorCode, OperationError, OperationResult

__all__ = [
    "ApiProfile",
    "DocmostSettings",
    "ErrorCode",
    "OperationError",
    "OperationResult",
    "WriteProfile",
    "__version__",
]
