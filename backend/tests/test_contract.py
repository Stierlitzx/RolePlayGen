import pytest
from pydantic import ValidationError

from app.schemas import TurnContract


def contract(choice: dict | None, is_ending: bool = False) -> dict:
    return {
        "narration": "Something happens.",
        "choice": choice,
        "state": {"scene": "Scene", "summary": "A concise summary.", "facts": ["Fact"]},
        "is_ending": is_ending,
    }


def options(count: int) -> list[dict[str, str]]:
    return [{"id": letter, "text": f"Option {letter}"} for letter in "abcd"[:count]]


def test_open_contract_is_valid() -> None:
    value = TurnContract.model_validate(
        contract({"mode": "open", "options": options(3), "allow_custom": True, "prompt": "Choose"})
    )
    assert value.choice is not None
    assert value.choice.mode == "open"


def test_locked_contract_is_valid() -> None:
    value = TurnContract.model_validate(
        contract({"mode": "locked", "options": options(4), "allow_custom": False, "prompt": "Choose"})
    )
    assert value.choice is not None
    assert len(value.choice.options) == 4


def test_binary_contract_is_valid() -> None:
    value = TurnContract.model_validate(
        contract({"mode": "binary", "options": options(2), "allow_custom": False, "prompt": "Choose"})
    )
    assert value.choice is not None
    assert value.choice.mode == "binary"


def test_ending_requires_null_choice() -> None:
    value = TurnContract.model_validate(contract(None, True))
    assert value.is_ending is True


@pytest.mark.parametrize(
    "choice",
    [
        {"mode": "open", "options": options(2), "allow_custom": True, "prompt": "Choose"},
        {"mode": "open", "options": options(3), "allow_custom": False, "prompt": "Choose"},
        {"mode": "locked", "options": options(1), "allow_custom": False, "prompt": "Choose"},
        {"mode": "locked", "options": options(3), "allow_custom": True, "prompt": "Choose"},
        {"mode": "binary", "options": options(3), "allow_custom": False, "prompt": "Choose"},
    ],
)
def test_invalid_choice_mode_rules(choice: dict) -> None:
    with pytest.raises(ValidationError):
        TurnContract.model_validate(contract(choice))


def test_ending_with_choice_is_invalid() -> None:
    with pytest.raises(ValidationError):
        TurnContract.model_validate(
            contract(
                {"mode": "binary", "options": options(2), "allow_custom": False, "prompt": "Choose"},
                True,
            )
        )


def test_empty_required_fields_are_invalid() -> None:
    with pytest.raises(ValidationError):
        TurnContract.model_validate(
            {
                "narration": "",
                "choice": None,
                "state": {"scene": "", "summary": "", "facts": []},
                "is_ending": True,
            }
        )
