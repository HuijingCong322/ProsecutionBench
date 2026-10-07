import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('content_reproduction', Path(__file__).resolve().parents[1]/'scripts/reproduce_lr_content.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_quoted_statute_does_not_create_ground():
    result = module.extract_content('Claims are rejected under 35 U.S.C. 103(a). The quoted statute mentions section 102.')
    assert result['o1_has_103'] == 1
    assert result['o1_has_102'] == 0

def test_heading_and_statute_variants():
    result = module.extract_content('Claim Rejections - 35 USC § 112. Claims are rejected under 35 USC 101.')
    assert result['o1_has_112'] == result['o1_has_101'] == 1

def test_double_patenting_not_forced_into_statute_flags():
    result = module.extract_content('Claims are rejected on the ground of nonstatutory obviousness-type double patenting.')
    assert all(result[k] == 0 for k in module.FEATURES[2:6])

def test_length_uses_normalized_whitespace():
    assert module.extract_content('  Claim\n  text.  ')['o1_body_characters'] == len('Claim text.')
