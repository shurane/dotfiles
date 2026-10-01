"""Storage estimates must use the real importer without modifying source logs."""

import gzip
import hashlib
import json
from compression import zstd
from pathlib import Path

import pytest

from benchmarks.storage import Options, main, measure


def test_storage_samples_multiple_networks_and_compressions(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    lines = b"2026-09-30 10:00:00\talice\thello\n" * 6
    (logs / "irc.libera.#python.weechatlog").write_bytes(lines)
    (logs / "irc.oftc.#python.weechatlog.gz").write_bytes(gzip.compress(lines))
    (logs / "irc.other.#python.weechatlog.zst").write_bytes(zstd.compress(lines))
    before = {p: hashlib.sha256(p.read_bytes()).digest() for p in logs.iterdir()}
    result = measure(Options(logs_dir=logs, stride=3, sample_size=1, temp_dir=tmp_path))
    assert result.source_files == 3
    assert result.source_records == 18
    assert result.sample_records_imported == result.sample_records == 6
    assert result.source_uncompressed_bytes == len(lines) * 3
    assert result.sample_records_skipped == {}
    assert result.sample_fts_bytes > 0
    assert result.projected_sqlite_bytes == result.sample_sqlite_bytes * 3
    assert result.sample_gzip_bytes > 0
    assert result.sample_zstd_bytes > 0
    assert before == {p: hashlib.sha256(p.read_bytes()).digest() for p in logs.iterdir()}
    assert list(tmp_path.iterdir()) == [logs]


def test_storage_reports_invalid_sample_and_keeps_stdout_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "irc.libera.#python.weechatlog").write_text(
        "bad record\n2026-09-30 10:00:00\talice\thello\n"
    )
    assert main(["--logs-dir", str(logs), "--temp-dir", str(tmp_path)]) == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["sample_records_skipped"] == {"ValueError": 1}
    assert report["sample_records_imported"] == 1
    assert "Imported 1 messages" in output.err


@pytest.mark.parametrize("content", ["", "not a log record\n"])
def test_storage_rejects_empty_or_invalid_samples(tmp_path: Path, content: str) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "irc.libera.#python.weechatlog").write_text(content)
    assert main(["--logs-dir", str(logs), "--temp-dir", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == [logs]


def test_storage_rejects_overlapping_sample_blocks(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sample_size must not exceed stride"):
        Options(logs_dir=tmp_path, stride=1, sample_size=2)
