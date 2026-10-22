"""D / Trajectory Forecasting, tasks 2 and 3: build frozen labels for
   Remaining Rounds   N_t          = number of further Office Actions before the first disposition
   Time to Next Action (T_t+1, d)  = days from the A1 filing (cutoff) to the next examiner communication

Same cases, same cutoff (A1 filing date) and same training rule as the Disposition task.

Usage:
    python build_rounds_next_data.py --data path/to/data_v1_share --out path/to/D_trajectory

Reads data_v1_share (labels.csv, examples/*.json, apps/*/transactions.csv). Writes:
    gold/rounds_next_gold.csv            test_core labels for both tasks (scoring only, never model input)
    gold/rounds_next_gold_test300.csv    same for the optional 300-case extension
    inputs/rounds_next_train_labels.csv  training labels, censored at 2013-12-31
    rounds_next_label_audit.csv          my count vs A's `remaining_oas`, my next action vs A's `target`

Frozen rules (written before any model is scored):
  Office Action (counts as a round) = a mailed non-final or final rejection: transaction MCTNF or MCTFR.
      Advisory actions, restriction requirements, Ex parte Quayle actions, interview summaries and examiner's
      answers on appeal are NOT counted. An RCE does not end prosecution, so actions after an RCE do count.
      One mailed transaction = one action (the document catalog sometimes lists the same action twice).
  Remaining rounds N = number of such actions mailed after the cutoff and on or before the first disposition
      (first mailed Notice of Allowance MN/=. or first mailed abandonment MABN*; same rule as the Disposition task).
  Next examiner communication = the first mailed transaction after the cutoff in
      {MCTNF, MCTFR, MCTAV, MCTRS, MCTEQ, MN/=., MABN*} (rejection, advisory action, restriction, Quayle action,
      allowance, abandonment notice). Interview summaries and miscellaneous letters do not count.
      This is the same document A uses as `target` (checked for every case in the audit).
  Training (A's train + excluded_time_boundary, cutoffs <= 2013-12-31): anything after 2013-12-31 is unknown.
      Rounds: if the disposition is after 2013-12-31, N is censored: we only know N >= (actions seen by then).
      Next action: if it is after 2013-12-31, the time is censored at 2013-12-31.
"""
import argparse, json, os
import pandas as pd

TRAIN_INFO_CUTOFF = "2013-12-31"
OA_CODES = {"MCTNF", "MCTFR"}
NEXT_CODES = {"MCTNF", "MCTFR", "MCTAV", "MCTRS", "MCTEQ", "MN/=."}
NEXT_TYPE = {"MCTNF": "nonfinal_rejection", "MCTFR": "final_rejection", "MCTAV": "advisory_action",
             "MCTRS": "restriction", "MCTEQ": "ex_parte_quayle", "MN/=.": "allowance"}


def first_disposition(T, cutoff):
    """First mailed NOA or first mailed abandonment after the cutoff (identical to build_trajectory_data.py)."""
    after = T[T.event_date > cutoff]
    c = []
    noa = after[after.event_code == "MN/=."]
    if len(noa):
        c.append((noa.event_date.min(), "allowance"))
    abn = after[after.event_code.str.startswith("MABN", na=False)]
    if len(abn):
        c.append((abn.event_date.min(), "abandonment"))
    return min(c) if c else (None, None)


def next_action(T, cutoff):
    after = T[(T.event_date > cutoff) & (T.event_code.isin(NEXT_CODES) | T.event_code.str.startswith("MABN", na=False))]
    if not len(after):
        return None, None
    r = after.sort_values(["event_date"], kind="stable").iloc[0]
    return r.event_date, r.event_code


def days(a, b):
    return (pd.Timestamp(b) - pd.Timestamp(a)).days


def label_one(D, app, info_cutoff=None):
    """Labels for one application. info_cutoff=None -> use everything up to the snapshot (test);
    info_cutoff='2013-12-31' -> nothing after that date is known (training)."""
    e = json.load(open(os.path.join(D, "examples", f"{app}.json")))
    cut = e["cutoff"]
    T = pd.read_csv(os.path.join(D, "apps", app, "transactions.csv"), dtype=str)
    end_obs = info_cutoff or T.event_date.max()  # last day we can see
    if info_cutoff:
        T = T[T.event_date <= info_cutoff]
    disp_date, disp_event = first_disposition(T, cut)
    upto = disp_date or end_obs
    oas = T[(T.event_date > cut) & (T.event_date <= upto) & T.event_code.isin(OA_CODES)].sort_values("event_date")
    n = int(len(oas))
    nx_date, nx_code = next_action(T, cut)
    tg = e.get("target") or {}
    return dict(
        sample_id=app, family_id=e["family_id"], tc=e["tc"], art_unit=e["art_unit"], cutoff=cut,
        # remaining rounds
        rounds=n, rounds_censored=disp_date is None, disposition=disp_event or "none_observed",
        disposition_date=disp_date or "", rounds_observed_until=upto,
        oa_dates=";".join(f"{d} {c}" for d, c in zip(oas.event_date, oas.event_code)),
        rces=int(((T.event_date > cut) & (T.event_date <= upto) & (T.event_code == "RCEX")).sum()),
        # time to next action
        next_days=days(cut, nx_date) if nx_date else days(cut, end_obs), next_censored=nx_date is None,
        next_date=nx_date or "", next_code=nx_code or "", next_type=NEXT_TYPE.get(nx_code, "abandonment" if nx_code else ""),
        # for the audit
        A_remaining_oas=e["labels"].get("remaining_oas"), A_target_date=tg.get("date"), A_target_code=tg.get("doc_code"),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    D, O = a.data, a.out
    for sub in ["gold", "inputs"]:
        os.makedirs(os.path.join(O, sub), exist_ok=True)
    L = pd.read_csv(os.path.join(D, "labels.csv"), dtype={"app_id": str})

    core = [label_one(D, x) for x in L[L.test_core == True].app_id]
    t300 = [label_one(D, x) for x in L[L.split == "test"].app_id]
    G, G3 = pd.DataFrame(core), pd.DataFrame(t300)
    for g in (G, G3):
        g["eligible_rounds"] = ~g.rounds_censored
        g["eligible_next"] = ~g.next_censored
    G.to_csv(os.path.join(O, "gold", "rounds_next_gold.csv"), index=False)
    G3.to_csv(os.path.join(O, "gold", "rounds_next_gold_test300.csv"), index=False)

    tr = [label_one(D, x, TRAIN_INFO_CUTOFF) for x in L[L.split.isin(["train", "excluded_time_boundary"])].app_id]
    TR = pd.DataFrame(tr)
    TR.to_csv(os.path.join(O, "inputs", "rounds_next_train_labels.csv"), index=False)

    # audit: compare with A (full follow-up, all 1000 examples)
    full = pd.DataFrame([label_one(D, x) for x in L.app_id]).merge(L[["app_id", "split", "test_core"]],
                                                                  left_on="sample_id", right_on="app_id")
    full["rounds_match_A"] = full.rounds.astype(str) == full.A_remaining_oas.astype(str)
    full["next_match_A"] = (full.next_date.fillna("") == full.A_target_date.fillna(""))
    full.drop(columns=["app_id"]).to_csv(os.path.join(O, "rounds_next_label_audit.csv"), index=False)

    print(f"test_core: {len(G)} cases | rounds censored {int(G.rounds_censored.sum())} | next censored {int(G.next_censored.sum())}")
    print("  rounds distribution:", G.rounds.value_counts().sort_index().to_dict())
    print("  next action types:", G.next_type.value_counts().to_dict(), "| median days", G.next_days.median())
    print(f"train: {len(TR)} | rounds censored {int(TR.rounds_censored.sum())} | next censored {int(TR.next_censored.sum())}")
    for name, s in (("test_core", full.test_core == True), ("all 1000", full.index == full.index)):
        f = full[s]
        print(f"audit {name}: rounds = A's remaining_oas {int(f.rounds_match_A.sum())}/{len(f)};"
              f" next action date = A's target date {int(f.next_match_A.sum())}/{len(f)}")
    bad = full[~full.rounds_match_A]
    if len(bad):
        print("  rounds differ from A (A counts duplicate catalog rows):", bad[["sample_id", "split", "rounds", "A_remaining_oas"]].values.tolist())


if __name__ == "__main__":
    main()
