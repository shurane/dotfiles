"""Monthly archives preserve original bytes and partition the boundary exactly."""

from compression import zstd
from pathlib import Path

import pytest

from soju_extras.importer.archive import prepare_history, verify_output
from soju_extras.importer.cli import SojuLogImporter


def test_monthly_archives_and_inclusive_local_cutoff(tmp_path: Path, soju_db: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    filename = "irc.libera.#c++.weechatlog"
    ambiguous_old = b"2025-11-02 01:30:00\talice\tDST stays untouched\n"
    june_utc = b"2026-07-01 06:59:59Z\tbob\tstill June in Pacific\n"
    june_naive = b"2026-06-30 23:59:59\tbob\told\r\n"
    july_utc = b"2026-07-01 07:00:00Z\tcarol\tboundary\n"
    july_naive = b"2026-07-01 00:00:01\tdan\tnew\n"
    raw = ambiguous_old + july_utc + june_utc + july_naive * 2 + june_naive
    (source / filename).write_bytes(raw)
    output = tmp_path / "result"
    report = prepare_history(source, output, since="2026-07-01", timezone="America/Los_Angeles")
    assert (report.source_records, report.archived_records, report.import_records) == (6, 3, 3)
    archives = sorted((output / "archives").rglob("*.zst"))
    assert [p.name for p in archives] == ["2025-11.weechatlog.zst", "2026-06.weechatlog.zst"]
    assert zstd.decompress(archives[0].read_bytes()) == ambiguous_old
    assert zstd.decompress(archives[1].read_bytes()) == june_utc + june_naive
    assert (output / "import" / filename).read_bytes() == july_utc + july_naive * 2
    assert (source / filename).read_bytes() == raw
    importer = SojuLogImporter(output / "import", db_path=soju_db, timezone="America/Los_Angeles")
    assert importer.run() == 3
    assert importer.run() == 0
    with pytest.raises(FileExistsError):
        prepare_history(source, output, since="2026-07-01", timezone="America/Los_Angeles")
    archives[0].write_bytes(zstd.compress(b"tampered\n"))
    with pytest.raises(ValueError, match="Verification failed"):
        verify_output(archives[0], report.outputs[str(archives[0].relative_to(output))])


@pytest.mark.parametrize("bad", [b"partial", b"bad\n", b"2026-99-01 00:00:00\tx\tbad\n"])
def test_failed_partition_is_not_published_and_can_retry(tmp_path: Path, bad: bytes) -> None:
    source = tmp_path / "source"
    source.mkdir()
    path = source / "irc.libera.#test.weechatlog"
    good = b"2026-06-01 00:00:00\tx\told\n2026-07-01 00:00:00\tx\tnew\n"
    path.write_bytes(good + bad)
    with pytest.raises(ValueError):
        prepare_history(source, tmp_path / "result", since="2026-07-01", timezone="UTC")
    assert not (tmp_path / "result").exists()
    assert not list(tmp_path.glob(".history-*"))
    path.write_bytes(good)
    assert (
        prepare_history(
            source, tmp_path / "result", since="2026-07-01", timezone="UTC"
        ).source_records
        == 2
    )


def test_same_target_rotations_are_rejected_before_writing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for suffix in ("", ".1"):
        (source / ("irc.libera.#test.weechatlog" + suffix)).write_bytes(
            b"2026-01-01 00:00:00\tx\told\n"
        )
    with pytest.raises(ValueError, match="one plain"):
        prepare_history(source, tmp_path / "result", since="2026-07-01", timezone="UTC")
    assert not (tmp_path / "result").exists()
