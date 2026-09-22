"""Proactive OKF scanner package."""

from tars.domains.proactive.scanner.engine import OKFRelevanceScanner
from tars.domains.proactive.scanner.schemas import (
    DeadlineExtractionResult,
    ScanResult,
    UtteranceCandidate,
)

__all__ = [
    "DeadlineExtractionResult",
    "OKFRelevanceScanner",
    "ScanResult",
    "UtteranceCandidate",
]
