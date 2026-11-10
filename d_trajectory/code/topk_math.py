"""profile_with_embedding, no LLM: the "top-3 average" the mentor asked to see first.

    python topk_math.py --root path/to/D_trajectory [--blocks inputs/examiner_blocks_emb_v1.jsonl]

Takes the 3 past applications most similar to the case by B's BGE-M3 search (the same 3 the LLM sees in the paths /
fulldoc blocks) and applies the same math as history_math.py to their dated events, cut at the case's cutoff:
    next action  = the median days from each application's first reply to its next letter
    rounds       = the median count of further rejections after the first reply
    disposition  = the training curves stretched to the share allowed / abandoned within 24 months
A case with no usable past application falls back to the plain average (KM).
    emb_top3_math_own         this case's examiner
    emb_top3_math_mismatched  another examiner of the same art unit (control)
Writes outputs/D/{trajectory,rounds_next}_predictions_<name>.jsonl.
"""
import argparse, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from traj_common import load_predictions, validate_curves  # noqa
from history_math import app_numbers, BINS  # noqa  same definitions as phase 2


def load_blocks(path):
    out = {}
    for x in open(path, encoding="utf-8"):
        b = json.loads(x)
        for k in ("card_text", "paths_text", "fulldoc_text"):
            b.pop(k, None)
        out[(b["sample_id"], b["variant"])] = b
    return out


class Predictor:
    def __init__(self, out_dir):
        self.km_t = {r["sample_id"]: r for r in load_predictions(os.path.join(out_dir, "trajectory_predictions_km.jsonl"))}
        self.km_r = {r["sample_id"]: r for r in load_predictions(os.path.join(out_dir, "rounds_next_predictions_km.jsonl"))}
        k0 = next(iter(self.km_t.values()))
        self.FA0, self.FB0 = np.array(k0["F_allowance"]), np.array(k0["F_abandonment"])

    def predict(self, sid, cutoff, apps, method, setting):
        """apps = list of {app_id, events}. Same rules as history_math.py."""
        nums = [n for x in apps if (n := app_numbers(x["events"], cutoff)) is not None]
        base = dict(sample_id=sid, method=method, model="none (math on past applications)", status="ok",
                    input_setting=setting, n_usable_apps=len(nums), past_app_ids=[x["app_id"] for x in apps])
        if nums:
            a24 = float(np.mean([n["allowed_24"] for n in nums])); b24 = float(np.mean([n["abandoned_24"] for n in nums]))
            FA, FB, S, rep = validate_curves((self.FA0 * a24 / self.FA0[-1]).tolist(), (self.FB0 * b24 / self.FB0[-1]).tolist())
            d = float(round(np.median([n["next_days"] for n in nums])))
            rv = [n["rounds"] for n in nums]
            rp = int(np.floor(np.median(rv) + 0.5))
            p = np.bincount(np.minimum(rv, BINS - 1), minlength=BINS) / len(rv)
        else:
            k = self.km_t[sid]
            FA, FB, S = np.array(k["F_allowance"]), np.array(k["F_abandonment"]), np.array(k["S"])
            rep, a24, b24 = ["no usable past application: KM"], None, None
            q = self.km_r[sid]
            d, rp, p = float(q["next_days_pred"]), int(q["rounds_pred"]), np.array(q["p_rounds"])
        t = dict(base, F_allowance=list(map(float, FA)), F_abandonment=list(map(float, FB)), S=list(map(float, S)),
                 repairs=rep, a24=a24, b24=b24)
        r = dict(base, p_rounds=[float(x) for x in p], rounds_pred=rp, rounds_pred_dist_median=rp,
                 next_days_pred=d, next_risk=-d)
        return t, r


def top3(b):
    """The top-3 past applications with their events (from the candidate list of the same block row)."""
    by = {c["app_id"]: c for c in b["candidates"]}
    miss = [x["app_id"] for x in b["top3"] if x["app_id"] not in by]
    if miss:
        raise SystemExit(f"top-3 application missing from the candidate list: {b['sample_id']} {b['variant']} {miss}")
    return [by[x["app_id"]] for x in b["top3"]]


def run(root, blocks_path):
    O = os.path.join(root, "outputs", "D")
    B = load_blocks(blocks_path)
    P = Predictor(O)
    for v in ["own", "mismatched"]:
        name = f"emb_top3_math_{v}"
        traj, rn = [], []
        for (sid, vv), b in sorted(B.items()):
            if vv == v:
                t, r = P.predict(sid, b["cutoff"], top3(b), name, f"{v}: top-3 of B's BGE-M3 search")
                traj.append(t); rn.append(r)
        for task, recs in [("trajectory", traj), ("rounds_next", rn)]:
            with open(os.path.join(O, f"{task}_predictions_{name}.jsonl"), "w") as fh:
                for x in recs:
                    fh.write(json.dumps(x) + "\n")
        n_used = [t["n_usable_apps"] for t in traj]
        print(f"{name}: {len(traj)} cases; usable past applications per case median {np.median(n_used):.0f}; "
              f"{sum(n == 0 for n in n_used)} cases fall back to KM")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--blocks", default=None)
    a = ap.parse_args()
    run(a.root, a.blocks or os.path.join(a.root, "inputs", "examiner_blocks_emb_v1.jsonl"))


if __name__ == "__main__":
    main()
