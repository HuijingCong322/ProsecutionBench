import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_run_paced import paced_transport


def test_pacing_respects_interval_and_429_retry_after_without_retry():
    import httpx
    now = [0.0]; waits = []; calls = []
    def sleep(delay):
        waits.append(delay); now[0] += delay
    def send(payload):
        calls.append(payload)
        if len(calls) == 1:
            response = httpx.Response(429, headers={'retry-after':'120'},
                                     request=httpx.Request('POST','https://example.test'))
            raise httpx.HTTPStatusError('429', request=response.request, response=response)
        return {'ok':True}
    paced = paced_transport(send, 65, sleep, lambda:now[0])
    with pytest.raises(httpx.HTTPStatusError):paced({'a':1})
    assert len(calls)==1
    assert paced({'a':2})=={'ok':True}
    assert waits==[65,120]
    assert len(calls)==2
