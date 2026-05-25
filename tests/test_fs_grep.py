"""grep_file returns bounded, targeted search output."""

from core.tools.ctx import WORKDIR
from core.tools.fs import grep_file


async def test_grep_file_content_merges_adjacent_match_context(tmp_path):
    for i in range(3):
        (tmp_path / f"f{i}.txt").write_text("needle\n" * 5, encoding="utf-8")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await grep_file("", "needle", output_mode="content", max_results=4)
    finally:
        WORKDIR.reset(tok)

    assert "Found 15 match(es) across 3 file(s)" in out
    assert "Showing context blocks 1-3 of 3" in out
    assert "5 matches in block" in out
    assert out.count("needle") == 15


async def test_grep_file_fixed_string_treats_pattern_literally(tmp_path):
    (tmp_path / "a.txt").write_text("a.b\naxb\n", encoding="utf-8")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await grep_file("a.txt", "a.b", output_mode="content", fixed_string=True)
    finally:
        WORKDIR.reset(tok)

    assert "Found 1 match(es)" in out
    assert "1: a.b" in out


async def test_grep_file_defaults_to_paths_only(tmp_path):
    (tmp_path / "a.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("nope\n", encoding="utf-8")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await grep_file("", "needle")
    finally:
        WORKDIR.reset(tok)

    assert out.endswith("a.txt")
    assert "1: needle" not in out


async def test_grep_file_paths_mode_pages_with_offset(tmp_path):
    for i in range(3):
        (tmp_path / f"f{i}.txt").write_text("needle\n", encoding="utf-8")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await grep_file("", "needle", max_results=2)
        next_out = await grep_file("", "needle", max_results=2, offset=2)
    finally:
        WORKDIR.reset(tok)

    assert "Showing files 1-2 of 3" in out
    assert "offset=2" in out
    assert out.count(".txt") == 2
    assert "Showing files 3-3 of 3" in next_out
    assert "f2.txt" in next_out


async def test_grep_file_content_mode_defaults_to_30_context_blocks(tmp_path):
    for i in range(40):
        (tmp_path / f"f{i:02d}.txt").write_text("needle\n", encoding="utf-8")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await grep_file("", "needle", output_mode="content")
    finally:
        WORKDIR.reset(tok)

    assert "Showing context blocks 1-30 of 40" in out
    assert "offset=30" in out


async def test_grep_file_content_mode_clamps_max_results_to_100(tmp_path):
    for i in range(120):
        (tmp_path / f"f{i:03d}.txt").write_text("needle\n", encoding="utf-8")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await grep_file("", "needle", output_mode="content", max_results=500)
    finally:
        WORKDIR.reset(tok)

    assert "Showing context blocks 1-100 of 120" in out
    assert "offset=100" in out


async def test_grep_file_count_mode_sorts_by_path_relevance_then_count(tmp_path):
    (tmp_path / "needle-target.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "many.txt").write_text("needle\n" * 5, encoding="utf-8")
    (tmp_path / "z.txt").write_text("needle\n", encoding="utf-8")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await grep_file("", "needle", output_mode="count")
    finally:
        WORKDIR.reset(tok)

    lines = out.splitlines()
    assert lines.index("needle-target.txt: 1") < lines.index("many.txt: 5")
    assert "Found 7 match(es) across 3 file(s)" in out


async def test_grep_file_fixed_string_path_ranking_tokenizes_endpoint_like_patterns(tmp_path):
    (tmp_path / "the-yesterday-test.md").write_text("/articles/the-yesterday-test\n", encoding="utf-8")
    (tmp_path / "index.md").write_text("/articles/the-yesterday-test\n" * 5, encoding="utf-8")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await grep_file("", "/articles/the-yesterday-test", fixed_string=True)
    finally:
        WORKDIR.reset(tok)

    lines = out.splitlines()
    assert lines.index("the-yesterday-test.md") < lines.index("index.md")


async def test_grep_file_glob_filters_candidates(tmp_path):
    (tmp_path / "a.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "a.md").write_text("needle\n", encoding="utf-8")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await grep_file("", "needle", glob="**/*.py")
    finally:
        WORKDIR.reset(tok)

    assert "a.py" in out
    assert "a.md" not in out


async def test_grep_file_warns_when_candidate_scan_cap_is_hit(tmp_path):
    for i in range(1001):
        (tmp_path / f"f{i:03d}.txt").write_text("needle\n", encoding="utf-8")

    tok = WORKDIR.set(tmp_path)
    try:
        out = await grep_file("", "needle")
    finally:
        WORKDIR.reset(tok)

    assert "scanned first 1000 candidate files" in out
    assert "files beyond that were not searched" in out
