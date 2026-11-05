"""Baseline without an LLM: plain math on the SAME 3 past applications the model sees (their full event lists).

    python history_math.py --root path/to/D_trajectory [--histories inputs/examiner_histories_v1.jsonl]

For every past application, from its event list (only events before the case's cutoff, built by
build_examiner_histories.py), with the same definitions as our answer keys:
    first reply   = the first applicant reply (A..., A.NE or RCE) after the application's first rejection
                    (this matches our cutoff, which is the first reply A1)
    next days     = days from the first reply to the examiner's next letter (non-final, final, advisory, restriction,
                    Quayle, allowance, abandonment notice)
    rounds        = number of non-final + final rejections after the first reply, up to the allowance/abandonment
    allowed_24 / abandoned_24 = the application was allowed / abandoned within 730 days of the first reply
An application still pending at the cutoff counts with what is known so far (days waited so far, rounds so far, and
"not ended" for the 24-month shares): a lower bound. Applications with no first reply before the cutoff are skipped.

Prediction for the case:
    Next action   median of the next days (the median is the single number with the smallest expected absolute error)
    Rounds        median of the rounds, rounded to a whole number
    Disposition   the training KM curves stretched so month 24 equals the share allowed_24 and the share abandoned_24
                  of the usable applications (the same stretch rule as "numbers only"), then the frozen repair rules
    No usable application -> the KM prediction for that task.
Writes outputs/D/{trajectory,rounds_next}_predictions_history_math_{own,mismatched}.jsonl.
"""
import argparse, json, os, sys
from datetime import date
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from traj_common import load_predictions, validate_curves  # noqa

REJ = {"MCTNF", "MCTFR"}
BINS = 5


def days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def app_numbers(ev, cutoff):
    first_rej = next((e for e in ev if e["code"] in REJ), None)
    if first_rej is None:
        return None
    reply = next((e for e in ev if e["kind"] == "reply" and e["date"] > first_rej["date"]), None)
    if reply is None:
        return None
    t0 = reply["date"]
    after = [e for e in ev if e["date"] > t0]
    nxt = next((e for e in after if e["kind"] in ("letter", "abandonment")), None)
    end = next((e for e in after if e["code"] == "MN/=." or e["kind"] == "abandonment"), None)
    upto = end["date"] if end else cutoff
    rounds = sum(1 for e in after if e["code"] in REJ and e["date"] <= upto)
    end_days = days(t0, end["date"]) if end else None
    return dict(first_reply=t0,
                next_days=days(t0, nxt["date"]) if nxt else days(t0, cutoff), next_pending=nxt is None,
                rounds=rounds, ended=end is not None,
                allowed_24=bool(end and end["code"] == "MN/=." and end_days <= 730),
                abandoned_24=bool(end and end["kind"] == "abandonment" and end_days <= 730))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--histories", default=None)
    a = ap.parse_args()
    R = a.root
    O = os.path.join(R, "outputs", "D")
    H = [json.loads(x) for x in open(a.histories or os.path.join(R, "inputs", "examiner_histories_v1.jsonl"), encoding="utf-8")]
    km_t = {r["sample_id"]: r for r in load_predictions(os.path.join(O, "trajectory_predictions_km.jsonl"))}
    km_r = {r["sample_id"]: r for r in load_predictions(os.path.join(O, "rounds_next_predictions_km.jsonl"))}
    k0 = next(iter(km_t.values()))
    FA0, FB0 = np.array(k0["F_allowance"]), np.array(k0["F_abandonment"])
    for v in ["own", "mismatched"]:
        traj, rn, n_used, n_pend = [], [], [], 0
        for h in [x for x in H if x["variant"] == v]:
            sid = h["sample_id"]
            nums = [n for app in h["app_ids"] if (n := app_numbers(h["events"][app], h["cutoff"])) is not None]
            n_used.append(len(nums)); n_pend += sum(n["next_pending"] or not n["ended"] for n in nums)
            base = dict(sample_id=sid, method=f"history_math_{v}",
                        model="none (math on the 3 past applications)", status="ok",
                        input_setting=f"{v} past-application histories", n_usable_apps=len(nums),
                        history_sha1=h["history_sha1"])
            if nums:
                a24 = float(np.mean([n["allowed_24"] for n in nums])); b24 = float(np.mean([n["abandoned_24"] for n in nums]))
                FA, FB, S, rep = validate_curves((FA0 * a24 / FA0[-1]).tolist(), (FB0 * b24 / FB0[-1]).tolist())
                d = float(round(np.median([n["next_days"] for n in nums])))
                rv = [n["rounds"] for n in nums]
                rp = int(np.floor(np.median(rv) + 0.5))
                p = np.bincount(np.minimum(rv, BINS - 1), minlength=BINS) / len(rv)
            else:
                FA, FB, S = np.array(km_t[sid]["F_allowance"]), np.array(km_t[sid]["F_abandonment"]), np.array(km_t[sid]["S"])
                rep, a24, b24 = ["no usable past application: KM"], None, None
                d, rp, p = float(km_r[sid]["next_days_pred"]), int(km_r[sid]["rounds_pred"]), np.array(km_r[sid]["p_rounds"])
            traj.append(dict(base, F_allowance=list(map(float, FA)), F_abandonment=list(map(float, FB)),
                             S=list(map(float, S)), repairs=rep, a24=a24, b24=b24))
            rn.append(dict(base, p_rounds=[float(x) for x in p], rounds_pred=rp, rounds_pred_dist_median=rp,
                           next_days_pred=d, next_risk=-d))
        for name, recs in [("trajectory", traj), ("rounds_next", rn)]:
            with open(os.path.join(O, f"{name}_predictions_history_math_{v}.jsonl"), "w") as fh:
                for r in recs:
                    fh.write(json.dumps(r) + "\n")
        print(f"history_math_{v}: usable past applications per case {np.bincount(n_used).tolist()} (index = count); "
              f"{n_pend} applications still open at the cutoff (counted as lower bounds)")


if __name__ == "__main__":
    main()
