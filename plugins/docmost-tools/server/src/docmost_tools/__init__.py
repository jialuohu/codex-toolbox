"""Private adapter package for the local Docmost MCP integration."""

__version__ = "0.5.0"

from .client import DocmostReadClient
from .config import ApiProfile, DocmostSettings, WriteProfile
from .models import ErrorCode, OperationError, OperationResult

__all__ = [
    "ApiProfile",
    "DocmostReadClient",
    "DocmostSettings",
    "ErrorCode",
    "OperationError",
    "OperationResult",
    "WriteProfile",
    "__version__",
]
