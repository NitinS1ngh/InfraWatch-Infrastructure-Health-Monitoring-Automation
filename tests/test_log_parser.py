from pathlib import Path

from app.log_parser.log_parser import LogParser


FIXTURE = Path(__file__).parent / "fixtures" / "sample_application.log"


def test_log_severity_counts() -> None:
    summary = LogParser(FIXTURE).parse()
    assert summary.severity_counts == {
        "DEBUG": 1,
        "INFO": 1,
        "WARNING": 1,
        "ERROR": 1,
        "CRITICAL": 1,
    }
    assert len(summary.recent_errors) == 2


def test_empty_and_missing_log_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty.log"
    empty.touch()
    empty_summary = LogParser(empty).parse()
    assert empty_summary.error_count == 0
    assert empty_summary.errors == ()

    missing_summary = LogParser(tmp_path / "missing.log").parse()
    assert missing_summary.error_count == 0
    assert missing_summary.errors