import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def launcher():
    assert importlib.util.find_spec('b_bgem3_qwen_prediction') is not None, 'New BGE-M3 launcher missing'
    return importlib.import_module('b_bgem3_qwen_prediction')


def test_original_modules_are_isolated():
    m = launcher()
    import b_phase2_prediction as old
    import b_qwen_phase2_concurrent as concurrent
    p, c = m.context()
    assert p is not old and c is not concurrent and c.p is p
    assert old.ROOT.name == 'phase2_prediction_v4_reviewed'
    assert concurrent.p is old
    assert p.ROOT.name == 'phase3_prediction_bgem3_v1_qwen_2026_11_08'


def test_sealed_manifest_tamper_rejected(tmp_path):
    m = launcher()
    p, _ = m.context()
    p.RELEASE = tmp_path
    (tmp_path / 'HANDOFF_MANIFEST_SHA256.json').write_text('{}')
    with pytest.raises(ValueError, match='manifest'):
        p.check_release()


@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    m = launcher()
    p, c = m.context()
    if not p.CORE.is_file():
        pytest.skip('Requires separately shared private corpus, profiles and baseline; never fetched by public tests')
    p.ROOT = tmp_path_factory.mktemp('bgem3') / 'new_experiment'
    m.prepare(p)
    return m, p, c


def test_prepare_has_only_frozen_profile_text_and_complete_lineage(prepared):
    m, p, _ = prepared
    base = p.bp.index(p.bp.read_jsonl(p.CORE))
    profiles, _ = p.check_release()
    for variant in ('own', 'mismatched'):
        rows = p.bp.read_jsonl(p.ROOT / 'inputs' / (variant + '.jsonl'))
        assert len(rows) == 100
        for row in rows:
            profile, _ = profiles[(row['app_id'], variant)]
            assert row['user_message'] == base[row['sample_id']]['user_message'] + p.PROFILE_HEADER + profile['profile_text']
            assert row['state_hash'] == base[row['sample_id']]['state_hash']
            assert row['profile_provenance']['embedding_model_revision'] == '5617a9f61b028005a4858fdac845db406aefb181'
            assert row['profile_provenance']['historical_links_sha256'] == p.fh(p.RELEASE / 'historical_links.csv')
    assert set(json.loads((p.ROOT / 'baseline_reuse.json').read_text())) == {'qwen'}
    summary = p.check_locks()
    assert (summary['type_eligible_n'], summary['ground_eligible_n']) == (99, 62)
    assert str(Path(m.__file__).resolve()) in summary['locks']


def test_reprepare_never_overwrites_existing_data(prepared):
    m, p, _ = prepared
    target = p.ROOT / 'inputs/own.jsonl'
    before = target.read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        m.prepare(p)
    assert target.read_bytes() == before


def test_core_without_new_dev_gate_is_blocked_before_transport(prepared):
    m, p, _ = prepared
    with pytest.raises(ValueError, match='dev gate'):
        m.check_gate(p)


def test_saved_dev_outputs_are_bound_and_resume_reuses_successes(prepared):
    m, p, _ = prepared
    config = json.loads(p.frozen_path('qwen').read_text())['config']
    calls = []

    def send(payload):
        calls.append(payload)
        return {'model': config['expected_model'], 'choices': [{'finish_reason': 'stop', 'message': {'content': p.bp.canonical(p.fixture_prediction())}}], 'usage': {}}

    out = p.ROOT / 'runs/qwen/dev'
    p.invoke('qwen', p.ROOT / 'inputs/dev.jsonl', out, send)
    m.write_gate(p)
    m.check_gate(p)
    assert len(calls) == 3
    p.invoke('qwen', p.ROOT / 'inputs/dev.jsonl', out, send)
    assert len(calls) == 3
    # Repeating the dev run changes its journal; a stale gate must be rejected.
    with pytest.raises(ValueError, match='dev gate'):
        m.check_gate(p)
    m.write_gate(p)
    rowfile = out / 'examiner_prediction.jsonl'
    rows = p.bp.read_jsonl(rowfile)
    rows[0]['status'] = 'failed'
    p.bp.jsonl(rowfile, rows)
    with pytest.raises(ValueError, match='dev gate'):
        m.check_gate(p)


def test_prepared_input_tamper_blocks_checks(prepared):
    _, p, _ = prepared
    target = p.ROOT / 'inputs/mismatched.jsonl'
    before = target.read_bytes()
    try:
        target.write_bytes(before + b'\n')
        with pytest.raises(ValueError, match='dependency changed'):
            p.check_locks()
    finally:
        target.write_bytes(before)


def test_execute_missing_key_and_failed_dev_never_leave_a_gate(prepared, monkeypatch):
    m, p, c = prepared
    p.offline()
    monkeypatch.delenv('QWEN_API_KEY', raising=False)
    monkeypatch.delenv('AZURE_OPENAI_API_KEY', raising=False)
    with pytest.raises(ValueError, match='Missing QWEN_API_KEY'):
        m.execute(p, c, 'dev', interval=0.000001)
    gate = p.ROOT / 'runs/qwen/dev/live_gate.json'
    assert not gate.exists()
    monkeypatch.setenv('QWEN_API_KEY', 'TEST_ONLY_NOT_A_CREDENTIAL')

    def failed(payload):
        raise RuntimeError('simulated endpoint failure')

    monkeypatch.setattr(p.bp, 'azure_transport', lambda _: failed)
    # Remove prior simulated success caches to exercise actual failure handling.
    dev = p.ROOT / 'runs/qwen/dev'
    for path in (dev / 'cache').glob('*.json'):
        path.unlink()
    with pytest.raises(ValueError, match='three valid model responses'):
        m.execute(p, c, 'dev', interval=0.000001)
    assert not gate.exists()
    with pytest.raises(ValueError, match='dev gate'):
        m.execute(p, c, 'core', interval=0)


def test_complete_two_condition_core_resume_uses_no_more_calls(prepared, monkeypatch):
    m, p, c = prepared
    config = json.loads(p.frozen_path('qwen').read_text())['config']
    calls = []

    def send(payload):
        calls.append(payload)
        return {'model': config['expected_model'], 'choices': [{'finish_reason': 'stop', 'message': {'content': p.bp.canonical(p.fixture_prediction())}}], 'usage': {'total_tokens': 1, 'simulated': True}}

    monkeypatch.setenv('QWEN_API_KEY', 'TEST_ONLY_NOT_A_CREDENTIAL')
    monkeypatch.setattr(p.bp, 'azure_transport', lambda _: send)
    m.execute(p, c, 'dev', interval=0.000001)
    assert len(calls) == 3
    result = m.execute(p, c, 'core', workers=4, interval=0)
    assert len(calls) == 203
    assert result['own']['success_n'] == result['mismatched']['success_n'] == 100
    resumed = m.execute(p, c, 'core', workers=4, interval=0)
    assert len(calls) == 203
    assert resumed['own']['scheduled_n'] == resumed['mismatched']['scheduled_n'] == 0
    assert m.inventory(p, c)['own']['reused_success_n'] == 100
    assert not (p.ROOT / 'runs/gpt').exists()
    assert not (p.ROOT / 'runs/qwen/artunit').exists()


def test_second_launcher_command_is_refused(tmp_path):
    m = launcher()
    p, _ = m.context()
    p.ROOT = tmp_path / 'new'
    with m.command_lock(p):
        with pytest.raises(ValueError, match='Another BGE-M3 experiment command'):
            with m.command_lock(p):
                pytest.fail('Second command obtained the lock')
