from typer.testing import CliRunner

from marketpulse.cli import app

runner = CliRunner()


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--competitors" in result.stdout
    assert "产品方向" in result.stdout


def test_cli_rejects_short_topic_before_credentials() -> None:
    result = runner.invoke(app, ["x"])
    assert result.exit_code == 2
    assert "至少需要 2 个字符" in result.output


def test_cli_reports_missing_deepseek_key(monkeypatch: object) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["AI meeting notes tools"])
    assert result.exit_code == 3
    assert "DEEPSEEK_API_KEY" in result.output
