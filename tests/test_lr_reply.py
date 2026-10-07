import importlib.util
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'scripts/reproduce_lr_reply.py'
spec = importlib.util.spec_from_file_location('reply_script', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_claim_status_distinguishes_argument_from_claim_changes():
    assert module.claim_flags('1. (Original) canceled noise in the argument') == (0, 0)
    assert module.claim_flags('1. (Currently Amended) <del>old</del> text') == (1, 0)
    assert module.claim_flags('1-20. (Canceled)\n21. (New) a thing') == (1, 1)
    assert module.claim_flags('3. (Cancelled)') == (0, 1)


def test_missing_markup_is_unknown_not_absence():
    assert module.claim_flags(None) == ('', '')
    assert module.claim_flags('1. (Original) a thing') == (0, 0)
