"""Isolated Qwen experiment for the sealed BGE-M3 release. No downloads or GPT calls.

prepare/offline/plan/compare need no credentials. Only dev/core make API calls.
Existing orchestration is loaded in private module instances, never rewritten.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import math
from pathlib import Path

B = Path(__file__).resolve().parent
RELEASE_ID = 'B_shared_BGE_M3_dense_v1_2026_11_05'
MANIFEST_SHA256 = '8e2af60a08d9fb380dab4f27f6eef51be12bb490e47b2c9021156d2d3e1fc92a'
ZIP_SHA256 = 'ff3db404a413b1f1d74b3f5c1b2b4c198d9ab87ef28196cfc7c32c3496e38917'
REVISION = '5617a9f61b028005a4858fdac845db406aefb181'


def load_private(filename):
    spec = importlib.util.spec_from_file_location('_bgem3_' + Path(filename).stem, B / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def context():
    p = load_private('b_phase2_prediction.py')
    c = load_private('b_qwen_phase2_concurrent.py')
    c.p = p
    p.RELEASE = B / 'outputs/profile_bgem3_v1_shared_2026_11_05'
    p.ROOT = B / 'outputs/phase3_prediction_bgem3_v1_qwen_2026_11_08'
    p.TEAM_ZIP = B / 'outputs/profile_bgem3_v1_shared_2026_11_05_TEAM_ONLY.zip'
    p.RELEASE_ID = RELEASE_ID
    p.MODELS = ('qwen',)
    p.check_release = lambda: check_release(p)
    original_append = p.append_profile

    def append(base, profile, provenance, variant):
        provenance = dict(provenance)
        if variant in p.VARIANTS:
            provenance.update(embedding_model_id='BAAI/bge-m3', embedding_model_revision=REVISION,
                              handoff_manifest_sha256=MANIFEST_SHA256,
                              historical_links_path=str(p.RELEASE / 'historical_links.csv'),
                              historical_links_sha256=p.fh(p.RELEASE / 'historical_links.csv'),
                              embedding_contract_hash=profile['embedding_contract_hash'])
        return original_append(base, profile, provenance, variant)

    p.append_profile = append
    return p, c


def check_release(p):
    manifest_path = p.RELEASE / 'HANDOFF_MANIFEST_SHA256.json'
    p.require(p.fh(manifest_path) == MANIFEST_SHA256, 'BGE-M3 sealed manifest changed')
    manifest = json.loads(manifest_path.read_text())
    p.require(manifest['release_id'] == RELEASE_ID, 'Wrong sealed release')
    for entry in manifest['files']:
        path = p.bp.safe_path(p.RELEASE, entry['path'])
        p.require(path.is_file() and path.stat().st_size == entry['bytes']
                  and p.fh(path) == entry['sha256'], 'Sealed release file changed: ' + entry['path'])
    p.require(p.fh(p.TEAM_ZIP) == ZIP_SHA256, 'Sealed BGE-M3 team ZIP changed')
    release = json.loads((p.RELEASE / 'RELEASE_MANIFEST.json').read_text())
    p.require(release['release_id'] == RELEASE_ID and release['model_revision'] == REVISION,
              'BGE-M3 release/revision mismatch')
    validation = json.loads((p.RELEASE / 'automatic_validation.json').read_text())
    p.require(validation['profiles_checked'] == 300 and validation['all_final_files_texts_cards_checked'],
              'Final profile automatic checks missing')
    cards = {(r['sample_id'], r['variant']): r for r in p.bp.read_jsonl(p.D_CARDS)}
    cases = p.bp.index(p.csvrows(p.CASES))
    profiles = {}
    coverage = Counter()
    for row in p.csvrows(p.RELEASE / 'profile_manifest.csv'):
        path = p.bp.safe_path(p.RELEASE, row['profile_path'])
        value = json.loads(path.read_text())
        key = (row['sample_id'], row['setting'])
        p.require(key not in profiles, 'Duplicate profile')
        p.require(p.fh(path, 'sha1') == row['profile_sha1']
                  and p.sha1(value['profile_text']) == row['profile_text_sha1'] == value['profile_text_sha1'],
                  'Profile hash mismatch')
        card = cards[key]
        p.require(value['card_sha1'] == value['D_card_sha1'] == row['card_sha1'] == row['D_card_sha1'] == card['card_sha1'],
                  'D card hash mismatch')
        p.require(value['statistics'] == card['stats'] and value['shrunk_statistics'] == card['shrunk']
                  and value['D_original_card_text'] == card['card_text'], 'D statistics changed')
        p.require(value['sample_id'] == row['sample_id'] and value['setting'] == row['setting'] == row['variant'],
                  'Profile identity mismatch')
        p.require(value['cutoff'] == row['cutoff'] == cases[row['sample_id']]['cutoff']
                  and value['target_examiner_id'] == cases[row['sample_id']]['examiner_id'], 'A identity/cutoff mismatch')
        p.require(value['retrieved_k'] == int(row['retrieved_k']) == len(value['retrieved_cases']), 'Effective k mismatch')
        profiles[key] = (value, row)
        coverage[str(value['retrieved_k'])] += 1
    p.require(len(profiles) == 300 and dict(coverage) == release['effective_k_counts'], 'Profile coverage changed')
    return profiles, {'release_id': RELEASE_ID, 'snapshot_files_verified': len(manifest['files']),
                      'profiles_verified': len(profiles), 'actual_k_counts': dict(coverage),
                      'release_manifest_sha256': p.fh(p.RELEASE / 'RELEASE_MANIFEST.json'),
                      'handoff_manifest_sha256': MANIFEST_SHA256, 'team_zip_sha256': ZIP_SHA256,
                      'model_revision': REVISION}


def prepare(p):
    p.require(not p.ROOT.exists(), 'Experiment directory already exists; use plan/dev/core to resume, never re-prepare')
    result = p.prepare()
    path = p.ROOT / 'preflight.json'
    summary = json.loads(path.read_text())
    # The reused orchestrator already locks itself, original adapters, prompt,
    # baseline, settings, source manifest/cards, gold and every prepared input.
    summary['locks'].update({str(Path(__file__).resolve()): p.fh(__file__),
                             str(B / 'b_qwen_phase2_concurrent.py'): p.fh(B / 'b_qwen_phase2_concurrent.py')})
    summary.update(experiment='Qwen_BGE_M3_dense_v1', model_scope=['qwen'],
                   inference_api_calls_during_preparation=0,
                   interpretation='Technical representation, encoder and reviewed coverage changed; no encoder-only causal claim')
    p.bp.atomic_json(path, summary)
    return result


def dev_bindings(p):
    out = p.ROOT / 'runs/qwen/dev'
    return {str(path.relative_to(p.ROOT)): p.fh(path) for path in (
        p.ROOT / 'inputs/dev.jsonl', out / 'examiner_prediction.jsonl',
        out / 'request_provenance.jsonl', out / 'run_summary.json')}


def write_gate(p):
    out = p.ROOT / 'runs/qwen/dev'
    rows = p.bp.index(p.bp.read_jsonl(out / 'examiner_prediction.jsonl'))
    inputs = p.bp.index(p.bp.read_jsonl(p.ROOT / 'inputs/dev.jsonl'))
    configuration = json.loads((p.ROOT / 'baseline_reuse.json').read_text())['qwen']['configuration']
    p.require(len(rows) == 3 and set(rows) == set(inputs), 'New dev gate requires exactly three original dev cases')
    for sample, row in rows.items():
        request = p.bp.digest({'messages': p.messages(inputs[sample]), 'config': configuration,
                               'provenance': {k: v for k, v in inputs[sample].items() if k != 'user_message'}})
        p.require(row['status'] == 'success' and row['finish_reason'] == 'stop'
                  and row['model'] == configuration['expected_model'] and row['configuration'] == configuration
                  and row['request_hash'] == request, 'New dev gate requires three valid model responses')
        p.bp.validate_prediction(row['prediction'])
    gate = {'success_n': 3, 'scored': False, 'launcher_sha256': p.fh(__file__),
            'prompt_sha256': p.fh(p.PROMPT), 'handoff_manifest_sha256': MANIFEST_SHA256,
            'bindings': dev_bindings(p)}
    p.bp.atomic_json(out / 'live_gate.json', gate)
    return gate


def check_gate(p):
    path = p.ROOT / 'runs/qwen/dev/live_gate.json'
    p.require(path.is_file(), 'New BGE-M3 dev gate missing; run dev first')
    gate = json.loads(path.read_text())
    p.require(gate.get('success_n') == 3 and gate.get('launcher_sha256') == p.fh(__file__)
              and gate.get('prompt_sha256') == p.fh(p.PROMPT)
              and gate.get('handoff_manifest_sha256') == MANIFEST_SHA256
              and gate.get('bindings') == dev_bindings(p), 'New BGE-M3 dev gate is stale or changed')
    return gate


def inventory(p, c):
    p.check_locks()
    config = c.configuration()
    result = {}
    for variant in p.VARIANTS:
        rows = p.bp.read_jsonl(p.ROOT / 'inputs' / (variant + '.jsonl'))
        cached = c.successes(rows, p.ROOT / 'runs/qwen' / variant, config)
        result[variant] = {'total_n': len(rows), 'reused_success_n': len(cached),
                           'pending_n': len(rows) - len(cached), 'api_calls': 0}
    return result


@contextmanager
def command_lock(p):
    # Outside the create-only output root; all new launcher mutations share it.
    path = p.ROOT.parent / (p.ROOT.name + '.command.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another BGE-M3 experiment command is running; wait for it to finish') from None
        yield


def execute(p, c, command, workers=4, interval=65):
    p.require(workers > 0 and math.isfinite(interval) and interval >= 0, 'Invalid workers/interval')
    if command == 'prepare':
        return prepare(p)
    if command == 'plan':
        return inventory(p, c)
    p.check_locks()
    if command == 'offline':
        return p.offline()
    if command == 'compare':
        return p.compare()
    report = p.ROOT / 'offline_checks/report.json'
    p.require(report.is_file(), 'Run offline checks first')
    checks = json.loads(report.read_text())
    p.require(checks['api_calls'] == 0 and len(checks['models']) == 1
              and checks['models'][0]['model'] == 'qwen'
              and checks['models'][0]['status'] == 'PASS_OFFLINE_SIMULATED', 'Offline checks invalid')
    if command == 'dev':
        gate_path = p.ROOT / 'runs/qwen/dev/live_gate.json'
        gate_path.unlink(missing_ok=True)  # An interrupted/failed rerun must invalidate the old gate.
        result = p.live('qwen', 'dev', interval)
        write_gate(p)  # Fails closed, producing a nonzero CLI exit if any case failed.
        return result
    p.require(command == 'core', 'Unknown command')
    check_gate(p)
    # Validate both condition caches before the first request.
    inventory(p, c)
    result = {}
    for variant in p.VARIANTS:
        print('Qwen BGE-M3 condition: ' + variant, flush=True)
        result[variant] = c.run_concurrent(p.ROOT / 'inputs' / (variant + '.jsonl'),
                                           p.ROOT / 'runs/qwen' / variant, workers, interval=interval)
    p.require(all(r['success_n'] == 100 for r in result.values()),
              'Some core requests failed; use plan, then rerun core to retry failures and reuse successes')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'offline', 'plan', 'dev', 'core', 'compare'))
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--interval', type=float, default=65)
    args = parser.parse_args()
    p, c = context()
    try:
        if args.command == 'plan':
            result = execute(p, c, args.command, args.workers, args.interval)
        else:
            with command_lock(p):
                result = execute(p, c, args.command, args.workers, args.interval)
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
