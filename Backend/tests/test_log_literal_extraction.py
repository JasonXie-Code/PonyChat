"""Keep legacy log formats while avoiding a whole-body backtracking regex."""
import re
import time

import pytest

from Backend.routes.admin.llm_log_indexer import _extract_debug_log_literal, _loads_debug_log_literal
from Backend.routes.admin.llm_logs import _read_log_detail


@pytest.mark.parametrize('body', [
    '{}', '{"data": {"text": "semi;colon and `tick`"}}',
    '{"data": {"text": `line one\nline two;`}}',
    '{\n    "data": {}\n}',
])
@pytest.mark.parametrize('suffix', ['', ';', '; \n\t', '\n\t'])
def test_legacy_extraction_and_detail(tmp_path, body, suffix):
    content = '// debug log\nconst \n debug_log \t= \n' + body + suffix
    old = re.search(r'const\s+debug_log\s*=\s*(.+?)\s*;?\s*$', content, re.DOTALL)
    literal = _extract_debug_log_literal(content)
    assert literal == old.group(1)
    path = tmp_path / 'sample.js'
    path.write_text(content, encoding='utf-8')
    assert _read_log_detail(str(path)) == _loads_debug_log_literal(old.group(1))


@pytest.mark.parametrize('content', ['', '// empty', 'const debug_log = ;',
                                     'const debug_log = \n', 'const other = {};'])
def test_missing_or_empty_declaration(content):
    assert _extract_debug_log_literal(content) is None


def test_multimegabyte_indented_body_does_not_backtrack():
    # Long whitespace runs inside real pretty-printed logs made the old
    # overlapping suffix regex hold the GIL for seconds in a worker thread.
    body = '{"data": [\n' + (' ' * 80 + '"entry",\n') * 60000 + '"last"]}'
    started = time.perf_counter()
    assert _extract_debug_log_literal('const debug_log = ' + body + ';\n') == body
    assert time.perf_counter() - started < 1.0
