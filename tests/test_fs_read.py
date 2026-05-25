"""read_file prepends a size header and honours start_line/end_line ranges."""

from core.tools.ctx import WORKDIR
from core.tools.fs import read_file
from core.text import tokens


async def test_read_file_full_includes_total_lines_header(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one\ntwo\nthree\n")
    tok = WORKDIR.set(tmp_path)
    try:
        out = await read_file("a.txt")
    finally:
        WORKDIR.reset(tok)
    first, _, body = out.partition("\n")
    assert first == "[a.txt · 3 lines]"
    assert body == "one\ntwo\nthree\n"


async def test_read_file_range_header_and_slice(tmp_path):
    f = tmp_path / "b.txt"
    f.write_text("\n".join(str(i) for i in range(1, 11)) + "\n")
    tok = WORKDIR.set(tmp_path)
    try:
        out = await read_file("b.txt", start_line=3, end_line=5)
    finally:
        WORKDIR.reset(tok)
    first, _, body = out.partition("\n")
    assert first == "[b.txt · lines 3-5 of 10]"
    assert body == "3\n4\n5\n"


async def test_read_file_expands_tiny_ranges_in_large_files(tmp_path):
    f = tmp_path / "large.txt"
    f.write_text("\n".join(str(i) for i in range(1, 101)) + "\n")
    tok = WORKDIR.set(tmp_path)
    try:
        out = await read_file("large.txt", start_line=3, end_line=5)
    finally:
        WORKDIR.reset(tok)
    header, _, rest = out.partition("\n")
    note, _, body = rest.partition("\n")
    assert header == "[large.txt · lines 3-32 of 100]"
    assert note == "[read_file expanded requested lines 3-5 to 3-32; minimum targeted read is 30 lines]"
    assert body.startswith("3\n4\n5\n")
    assert body.endswith("32\n")


async def test_read_file_full_large_file_is_token_capped(tmp_path):
    f = tmp_path / "huge.txt"
    f.write_text("HEAD\n" + ("middle words\n" * 20_000) + "TAIL\n", encoding="utf-8")
    tok = WORKDIR.set(tmp_path)
    try:
        out = await read_file("huge.txt")
    finally:
        WORKDIR.reset(tok)

    assert "[read_file truncated full-file output to 8000 tokens" in out
    assert "HEAD" in out
    assert "TAIL" in out
    assert tokens(out) <= 8_200
