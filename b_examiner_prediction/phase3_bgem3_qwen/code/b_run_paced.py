"""Explicit paced resume; preserve b_prediction implementation and success cache.

Each uncached API attempt waits at least --interval seconds. No API retries are
added: failed rows remain failed for explicit resume. Model settings unchanged.
"""
import argparse
import os
from pathlib import Path
import time
from b_prediction import azure_transport, run, atomic_json


def paced_transport(send, interval=65, sleep=time.sleep, monotonic=time.monotonic):
    if interval <= 0:
        raise ValueError('interval must be positive')
    next_at = monotonic() + interval
    def paced(payload):
        nonlocal next_at
        delay = max(0, next_at - monotonic())
        if delay:
            print(f'Rate pacing: waiting {delay:.0f}s before API attempt', flush=True)
            sleep(delay)
        try:
            return send(payload)
        except Exception as exc:
            response = getattr(exc, 'response', None)
            if response is not None and response.status_code == 429:
                try:
                    cooldown = float(response.headers.get('retry-after', interval))
                except (ValueError, TypeError):
                    cooldown = interval
                next_at = monotonic() + max(interval, cooldown)
            raise
        finally:
            next_at = max(next_at, monotonic() + interval)
    return paced


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('inputs', 'prompt', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--interval', type=float, default=65)
    a = p.parse_args()
    config = {'endpoint': os.environ.get('AZURE_OPENAI_ENDPOINT'),
              'deployment': os.environ.get('AZURE_DEPLOYMENT')}
    atomic_json(a.output/'request_pacing.json',
                {'interval_seconds': a.interval, 'api_retries_added': 0,
                 'reason': 'Explicit resume after observed HTTP 429; model parameters unchanged'})
    print(run(a.inputs, a.prompt, a.output, config,
              transport=paced_transport(azure_transport(config), a.interval)))
