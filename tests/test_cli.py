import pytest

from report_harness.cli import main


def test_cli_reports_missing_openai_configuration(capsys) -> None:
    result = main(
        [
            "report.xlsx",
            "--provider",
            "openai-compatible",
            "--api-key",
            "key",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "--base-url" in captured.err


def test_cli_requires_a_provider() -> None:
    with pytest.raises(SystemExit) as error:
        main(["report.xlsx"])

    assert error.value.code == 2
