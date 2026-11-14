"""Exercise the real spec's minimum policy without importing a build tool."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


SPEC = Path(__file__).resolve().parents[1] / 'platform/macos/pyinstaller/whisper_project_mac.spec'


def declared_minimum(hits, *, host='10.15.7', override=None):
    source = SPEC.read_text(encoding='utf-8')
    tree = ast.parse(source)
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name == '_select_minimum_macos']
    env = {} if override is None else {'WTS_MACOS_MIN': override}
    namespace = dict(_minos_hits=hits, os=SimpleNamespace(environ=env, path=os.path),
                     _platform=SimpleNamespace(mac_ver=lambda: (host, '', ''), machine=lambda: 'x86_64'))
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(SPEC), 'exec'), namespace)
    policy = source[source.index('_highest_min ='):source.index('\nexe = EXE(')]
    exec(compile(policy, str(SPEC), 'exec'), namespace)
    return namespace['_MIN_MACOS']


@pytest.mark.parametrize('name,minimum', [
    ('bin/deno', (12, 0)),
    ('google/_upb/_message.abi3.so', (12, 0)),
    ('onnxruntime/capi/onnxruntime_pybind11_state.so', (11, 0)),
], ids=['deno', 'protobuf-upb', 'onnxruntime'])
def test_old_build_host_never_lowers_a_bundled_component_minimum(name, minimum):
    actual = tuple(int(part) for part in declared_minimum({minimum: [name]}).split('.'))
    assert actual >= minimum, 'Build-host cap understates a bundled component requirement'


def test_lower_override_cannot_hide_all_three_native_findings():
    hits = {(12, 0): ['bin/deno', 'google/_upb/_message.abi3.so'],
            (11, 0): ['onnxruntime/capi/onnxruntime_pybind11_state.so']}
    with pytest.raises(ValueError, match='minimum|Minimum'):
        declared_minimum(hits, override='10.15')


@pytest.mark.parametrize('override', ['invalid', '12.0.0.1'])
def test_malformed_minimum_override_is_rejected(override):
    with pytest.raises(ValueError):
        declared_minimum({(12, 0): ['bin/deno']}, override=override)


@pytest.mark.parametrize('host,override,expected', [
    ('13.6.9', None, '12.0'),
    ('10.15.7', '12.0', '12.0'),
    ('10.15.7', '13.0', '13.0'),
    ('10.15.7', '12.0.1', '12.0.1'),
])
def test_equal_higher_or_automatic_minima_are_retained(host, override, expected):
    assert declared_minimum({(12, 0): ['bin/deno']}, host=host, override=override) == expected
