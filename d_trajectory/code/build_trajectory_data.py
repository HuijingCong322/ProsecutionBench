"""D / Trajectory Forecasting: build frozen labels, eligible IDs, audit, train survival labels and model inputs.

Usage:
    python build_trajectory_data.py --data path/to/data_v1_share --out path/to/D_trajectory

Reads only data_v1_share (v1.1). Writes:
    gold/trajectory_gold.csv              test_core labels (scoring only, never model input)
    gold/trajectory_gold_test300.csv      same for the optional 300-case extension
    trajectory_eligible_ids.csv           test_core IDs with eligibility + reason
    trajectory_label_audit.csv            independent re-derivation of every test_core label from transactions
    inputs/trajectory_train_labels.csv    training survival labels, censored at 2013-12-31
    inputs/trajectory_inputs.jsonl        model inputs (cutoff-available documents only), leakage-checked
    inputs/time_grid.json                 frozen evaluation grid
"""
import argparse, hashlib, json, os
import pandas as pd

TRAIN_INFO_CUTOFF = "2013-12-31"
DAYS_PER_MONTH = 30.4375
GRID_MONTHS = list(range(1, 25))
GRID_DAYS = [round(m * DAYS_PER_MONTH) for m in GRID_MONTHS]
STATUS = {"none": 0, "allowance": 1, "abandonment": 2}


def first_outcome(T, cutoff):
    """Independent rule: first mailed NOA (MN/=.) or first mailed abandonment (MABN*) after the cutoff.
    ABN9 ('Disposal for a RCE / CPA / R129') is an RCE bookkeeping entry, not an abandonment."""
    after = T[T.event_date > cutoff]
    cands = []
    noa = after[after.event_code == "MN/=."]
    if len(noa):
        cands.append((noa.event_date.min(), "allowance", "MN/=.", "Mail Notice of Allowance"))
    abn = after[after.event_code.str.startswith("MABN", na=False)].sort_values("event_date")
    if len(abn):
        r = abn.iloc[0]
        cands.append((r.event_date, "abandonment", r.event_code, r.event_description))
    return min(cands) if cands else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    D, O = a.data, a.out
    for sub in ["gold", "inputs"]:
        os.makedirs(os.path.join(O, sub), exist_ok=True)
    L = pd.read_csv(os.path.join(D, "labels.csv"), dtype={"app_id": str, "family_id": str})
    gold_ids = set(pd.read_csv(os.path.join(D, "gold_subset.csv"), dtype=str).app_id)

    def ex(app):
        with open(os.path.join(D, "examples", f"{app}.json")) as f:
            return json.load(f)

    # ---------- test labels + audit ----------
    def build_gold(ids):
        gold, audit = [], []
        for app in ids:
            e = ex(app)
            d = e["labels"]["disposition"]
            cut = e["cutoff"]
            T = pd.read_csv(os.path.join(D, "apps", app, "transactions.csv"), dtype=str)
            C = pd.read_csv(os.path.join(D, "apps", app, "catalog.csv"), dtype=str)
            fo = first_outcome(T, cut)
            ev = d["event"] if d["event"] else "none"
            censored = bool(d["censored"])
            last_txn = T.event_date.max()
            if censored:
                status, label_status = 0, "censored"
                ev_date = d.get("censor_date")
                # A censors at the snapshot date. If the record stopped long before the snapshot, we cannot
                # claim the case was observed until 2026: censor at the last verified transaction instead
                # and flag it 'incomplete' (plan section 10, step 3).
                if pd.Timestamp(last_txn) < pd.Timestamp(e["snapshot_date"]) - pd.Timedelta(days=365):
                    label_status, ev_date = "incomplete", last_txn
                    d = dict(d, time_days=(pd.Timestamp(last_txn) - pd.Timestamp(cut)).days)
            else:
                status, label_status = STATUS[ev], "observed"
                ev_date = d["event_date"]
            src_doc = src_txn = abn_int = abn_int_date = ""
            if fo:
                code = {"allowance": ["NOA"], "abandonment": ["ABN"]}[fo[1]]
                cc = C[(C.official_date == fo[0]) & C.doc_code.isin(code)]
                src_doc = cc.doc_id.iloc[0] if len(cc) else ""
                src_txn = f"{fo[0]} {fo[2]} {fo[3]}"
                if fo[1] == "abandonment":
                    m = T[T.event_code.str.match(r"^ABN\d", na=False) & (T.event_code != "ABN9")
                          & (T.event_date > cut) & (T.event_date <= fo[0])].sort_values("event_date")
                    if len(m):
                        abn_int, abn_int_date = m.event_code.iloc[-1], m.event_date.iloc[-1]
            up = T[(T.event_date > cut) & (T.event_date <= (ev_date or "9999"))]
            post = T[T.event_date > (ev_date or "9999")]
            match = (bool(fo) and fo[1] == d["event"] and fo[0] == d["event_date"]) or (not fo and censored)
            row = dict(
                sample_id=app, family_id=e["family_id"], tc=e["tc"], art_unit=e["art_unit"],
                examiner_id=e["examiner_id"], gold_subset=app in gold_ids, cutoff=cut,
                label_status=status, event=ev, outcome_date=ev_date, time_days=d["time_days"],
                censored=censored, event_code=fo[2] if fo else "", source_doc_id=src_doc,
                source_transaction=src_txn, abn_internal_code=abn_int, abn_internal_date=abn_int_date,
                last_verified_followup=last_txn, snapshot_date=e["snapshot_date"],
                status=label_status,
            )
            gold.append(row)
            audit.append(dict(
                row,
                derived_event=fo[1] if fo else "", derived_date=fo[0] if fo else "",
                derived_days=(pd.Timestamp(fo[0]) - pd.Timestamp(cut)).days if fo else None,
                matches_A_label=match,
                mailed_oas_between=int(up.event_code.isin(["MCTNF", "MCTFR"]).sum()),
                rces_between=int((up.event_code == "RCEX").sum()),
                appeal_between=bool((up.event_code == "N/AP").any()),
                abn9_rows_between=int((up.event_code == "ABN9").sum()),
                revived_after_abandonment=ev == "abandonment" and post.event_code.isin(["PREV", "MPREV"]).any(),
                later_noa_after_outcome=ev == "abandonment" and (post.event_code == "MN/=.").any(),
                beyond_24_months=(d["time_days"] or 0) > GRID_DAYS[-1],
            ))
        return pd.DataFrame(gold), pd.DataFrame(audit)

    core_ids = L[L.test_core == True].app_id.tolist()
    G, A = build_gold(core_ids)
    G.to_csv(os.path.join(O, "gold", "trajectory_gold.csv"), index=False)
    A.to_csv(os.path.join(O, "trajectory_label_audit.csv"), index=False)
    t300 = L[L.split == "test"].app_id.tolist()
    G3, A3 = build_gold(t300)
    G3.to_csv(os.path.join(O, "gold", "trajectory_gold_test300.csv"), index=False)

    # eligibility
    def eligibility(Aud):
        out = []
        for _, r in Aud.iterrows():
            reason = ""
            if not r.matches_A_label:
                reason = "label_mismatch"
            if r.status == "incomplete":
                reason = "incomplete_record"  # kept in gold, excluded from scoring, counted separately
            if r.time_days is None or pd.isna(r.time_days):
                reason = "missing_time"
            out.append(dict(sample_id=r.sample_id, eligible=reason == "", exclusion_reason=reason,
                            status=r.status, label_status=r.label_status, gold_subset=r.gold_subset))
        return pd.DataFrame(out)
    eligibility(A).to_csv(os.path.join(O, "trajectory_eligible_ids.csv"), index=False)
    eligibility(A3).to_csv(os.path.join(O, "trajectory_eligible_ids_test300.csv"), index=False)

    # ---------- training survival labels (censored at the training information cutoff) ----------
    # Training pool = A's `train` split + `excluded_time_boundary` (cutoff <= 2013-12-31, no test family).
    # Dropping excluded_time_boundary would condition on the future (next-action date) and favour fast cases.
    tr = []
    for _, r in L[L.split.isin(["train", "excluded_time_boundary"])].iterrows():
        e = ex(r.app_id)
        d = e["labels"]["disposition"]
        cut = e["cutoff"]
        assert cut <= TRAIN_INFO_CUTOFF
        if d["event"] and not d["censored"] and d["event_date"] <= TRAIN_INFO_CUTOFF:
            status, t, ev = STATUS[d["event"]], d["time_days"], d["event"]
        else:
            status, ev = 0, "censored_at_2013-12-31"
            t = (pd.Timestamp(TRAIN_INFO_CUTOFF) - pd.Timestamp(cut)).days
        o1 = e["o1"]
        tr.append(dict(
            sample_id=r.app_id, family_id=e["family_id"], split=r.split, tc=e["tc"], cutoff=cut,
            label_status=status, event=ev, time_days=t,
            # cutoff-available features (supplementary Cox baseline)
            o1_code=o1["code"],
            days_filing_to_o1=(pd.Timestamp(o1["mail_date"]) - pd.Timestamp(e["filing_date"])).days,
            days_o1_to_a1=(pd.Timestamp(cut) - pd.Timestamp(o1["mail_date"])).days,
            n_grounds_o1=r.n_grounds_o1, strategy=r.strategy,
        ))
    TR = pd.DataFrame(tr)
    TR.to_csv(os.path.join(O, "inputs", "trajectory_train_labels.csv"), index=False)

    # same cutoff-available features for test cases (feature file, not labels)
    feats = []
    for app in sorted(set(core_ids) | set(t300)):
        e = ex(app)
        o1 = e["o1"]
        r = L[L.app_id == app].iloc[0]
        feats.append(dict(
            sample_id=app, tc=e["tc"], o1_code=o1["code"],
            days_filing_to_o1=(pd.Timestamp(o1["mail_date"]) - pd.Timestamp(e["filing_date"])).days,
            days_o1_to_a1=(pd.Timestamp(e["cutoff"]) - pd.Timestamp(o1["mail_date"])).days,
            n_grounds_o1=r.n_grounds_o1, strategy=r.strategy))
    pd.DataFrame(feats).to_csv(os.path.join(O, "inputs", "trajectory_test_features.csv"), index=False)

    # ---------- model inputs ----------
    M = pd.read_csv(os.path.join(D, "sample_manifest.csv"), dtype=str).set_index("app_id")

    def write_inputs(ids, fname):
        n_docs = 0
        with open(os.path.join(O, "inputs", fname), "w") as f:
            for app in ids:
                e = ex(app)
                cut = e["cutoff"]
                docs, h = [], hashlib.sha1()
                for i in e["inputs"]:
                    assert i["date"] <= cut, f"leak: {app} {i}"
                    assert i["doc_id"] != (e.get("target") or {}).get("doc_id"), f"target in inputs: {app}"
                    with open(os.path.join(D, i["text_path"]), "rb") as tf:
                        raw = tf.read()
                    txt = raw.decode("utf-8", errors="replace")
                    h.update(i["doc_id"].encode()); h.update(raw)  # same recipe as A's sample_manifest input_hash
                    docs.append(dict(doc_id=i["doc_id"], doc_code=i["doc_code"], date=i["date"], role=i["role"],
                                     source=i["source"], text_path=i["text_path"], n_chars=len(txt)))
                    n_docs += 1
                rec = dict(
                    sample_id=app, stage="t1_after_A1", cutoff=cut, filing_date=e["filing_date"],
                    art_unit=e["art_unit"], tc=e["tc"],
                    o1=e["o1"], a1=e["a1"], documents=docs,
                    input_chars=sum(d["n_chars"] for d in docs), approx_tokens=sum(d["n_chars"] for d in docs) // 4,
                    input_hash=h.hexdigest()[:16],
                    state=None, state_version=None,  # filled when A's predicted A1 state arrives
                    horizon_months=24, grid_months=GRID_MONTHS,
                )
                # label-isolation check: no outcome / future fields in the record
                s = json.dumps(rec)
                for bad in ["disposition", "event_date", "remaining_oas", "claims_granted", "next_type", "target"]:
                    assert bad not in s, f"label field {bad} leaked into inputs for {app}"
                assert M.loc[app, "input_hash"] == rec["input_hash"], f"input_hash differs from A's manifest: {app}"
                f.write(s + "\n")
        return n_docs

    n_docs = write_inputs(core_ids, "trajectory_inputs.jsonl")
    write_inputs(["11968167", "11968173", "11968176"], "trajectory_inputs_dev.jsonl")  # prompt development only
    elig300 = eligibility(A3)
    write_inputs(elig300[elig300.eligible].sample_id.tolist(), "trajectory_inputs_test300.jsonl")
    with open(os.path.join(O, "inputs", "time_grid.json"), "w") as f:
        json.dump(dict(days_per_month=DAYS_PER_MONTH, grid_months=GRID_MONTHS, grid_days=GRID_DAYS,
                       horizon_days=GRID_DAYS[-1], train_information_cutoff=TRAIN_INFO_CUTOFF), f, indent=1)

    print(f"test_core gold: {len(G)}  events: {G.event.value_counts().to_dict()}  censored: {int(G.censored.sum())}")
    print(f"audit matches A label: {int(A.matches_A_label.sum())}/{len(A)}")
    print(f"test300 gold: {len(G3)}  events: {G3.event.value_counts().to_dict()}")
    print(f"train pool: {len(TR)}  {TR.event.value_counts().to_dict()}")
    print(f"inputs: {len(core_ids)} records, {n_docs} docs, leakage asserts passed, input_hash matches A for all")


if __name__ == "__main__":
    main()
