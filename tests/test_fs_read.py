"""read_file prepends a size header and honours start_line/end_line ranges."""

from core.tools.ctx import WORKDIR
from core.tools.fs import read_file


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
