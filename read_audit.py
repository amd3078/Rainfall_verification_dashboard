#!/usr/bin/env python
"""Read collected audit records and tabulate them.

Sources (auto-detected):
  - Firestore  : if VERIF_FIREBASE_CRED is set (needs firebase-admin).
  - JSONL      : local logs/audit.jsonl (or VERIF_AUDIT) otherwise / with --jsonl.

Usage:
  python read_audit.py                 # print summary + recent rows
  python read_audit.py --jsonl         # force local JSONL
  python read_audit.py --csv out.csv   # also dump all records to CSV
  python read_audit.py --limit 50      # show N most recent rows
"""
import os, sys, json, argparse
import pandas as pd

AUDIT_LOG = os.environ.get("VERIF_AUDIT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "audit.jsonl"))
FB_CRED   = os.environ.get("VERIF_FIREBASE_CRED")
FB_COLL   = os.environ.get("VERIF_FIREBASE_COLLECTION", "audit")

def from_firestore():
    import firebase_admin
    from firebase_admin import credentials, firestore
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(FB_CRED))
    db = firestore.client()
    return [d.to_dict() for d in db.collection(FB_COLL).stream()]

def from_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", action="store_true", help="force local JSONL source")
    ap.add_argument("--csv", help="write all records to this CSV")
    ap.add_argument("--limit", type=int, default=20, help="rows to print")
    a = ap.parse_args()

    if FB_CRED and not a.jsonl:
        src = f"Firestore:{FB_COLL}"; recs = from_firestore()
    else:
        src = AUDIT_LOG; recs = from_jsonl(AUDIT_LOG)

    if not recs:
        print(f"No audit records found ({src})."); return
    df = pd.DataFrame(recs).sort_values("ts") if "ts" in recs[0] else pd.DataFrame(recs)

    print(f"Source: {src}")
    print(f"Total records: {len(df)}")
    if "session" in df:  print(f"Unique sessions: {df['session'].nunique()}")
    if "event" in df:    print("Events:\n" + df["event"].value_counts().to_string())
    if "ts" in df:       print(f"Span: {df['ts'].min()}  ->  {df['ts'].max()}")

    cols = [c for c in ["ts","session","event","period","threshold","obs","forecasts","sources"] if c in df]
    print(f"\nMost recent {min(a.limit,len(df))}:")
    with pd.option_context("display.max_colwidth", 40, "display.width", 160):
        print(df[cols].tail(a.limit).to_string(index=False))

    if a.csv:
        df.to_csv(a.csv, index=False); print(f"\nWrote {len(df)} records -> {a.csv}")

if __name__ == "__main__":
    main()
