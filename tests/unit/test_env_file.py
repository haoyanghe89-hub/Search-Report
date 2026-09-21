from pathlib import Path

import pytest

from marketpulse.config import Settings


def test_env_file_loads_key_without_mutating_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text("DEEPSEEK_API_KEY=local-test-key\nMARKETPULSE_MODEL=test-model\n")
    config = Settings.from_env(env_file=path)
    assert config.deepseek_api_key.get_secret_value() == "local-test-key"
    assert config.model == "test-model"
    assert "local-test-key" not in repr(config)
    assert "local-test-key" not in config.model_dump_json()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "process-key")
    assert Settings.from_env(env_file=path).deepseek_api_key.get_secret_value() == "process-key"


def test_no_parent_environment_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=parent-key")
    child = tmp_path / "child"
    child.mkdir()
    assert (
        Settings.from_env(require_api_key=False, env_file=child / ".env").deepseek_api_key is None
    )
