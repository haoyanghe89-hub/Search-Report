from marketpulse.agents.factory import _extract_json


def test_extract_json_accepts_fenced_payload() -> None:
    assert _extract_json('```json\n{"answer": 1}\n```') == '{"answer": 1}'


def test_extract_json_discards_surrounding_prose() -> None:
    assert _extract_json('Here is the result: {"answer": 1} done') == '{"answer": 1}'
