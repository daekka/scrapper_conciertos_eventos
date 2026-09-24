import pytest
from pydantic import ValidationError

from src.models.classification import ClassificationResult


def test_valid_classification():
    result = ClassificationResult.model_validate(
        {
            "classification": "INTERESTED",
            "confidence": 0.91,
            "reason": "Encaja con la escena indie.",
            "matched_preferences": ["indie"],
            "suggested_tags": ["indie"],
        }
    )
    assert result.classification == "INTERESTED"
    assert result.music_genres == []


@pytest.mark.parametrize(
    "payload",
    [
        {"classification": "LOVE", "confidence": 0.5, "reason": "x"},
        {"classification": "MAYBE", "confidence": 1.2, "reason": "x"},
        {"classification": "IGNORE", "confidence": 0.2, "reason": ""},
        {"confidence": 0.2, "reason": "falta clase"},
    ],
)
def test_invalid_classification(payload):
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate(payload)
