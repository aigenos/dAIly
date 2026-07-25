"""Private subscriber viewer — see your full list (emails + status) locally.

Run this ON YOUR OWN MACHINE only. It prints subscriber emails, so never wire
it into a public GitHub Actions workflow (Action logs on a public repo are
world-readable). Your Resend key stays on your laptop; nobody else can see this.

    RESEND_API_KEY=re_...  python -m scripts.subscribers            # print table
    RESEND_API_KEY=re_...  python -m scripts.subscribers --csv out.csv   # export
    RESEND_API_KEY=re_...  RESEND_AUDIENCE_ID=... python -m scripts.subscribers

Needs a FULL-ACCESS Resend key (the send-only key can't read contacts).
"""

from __future__ import annotations

import csv
import os
import sys

import requests

API = "https://api.resend.com"


def _get(path: str, key: str):
    r = requests.get(f"{API}{path}", headers={"Authorization": f"Bearer {key}"}, timeout=20)
    r.raise_for_status()
    return r.json()


def _audience_id(key: str) -> str:
    aid = os.environ.get("RESEND_AUDIENCE_ID", "").strip()
    if aid:
        return aid
    data = (_get("/audiences", key) or {}).get("data") or []
    if not data:
        raise SystemExit("No audience found in this Resend account.")
    return data[0]["id"]


def _contacts(key: str, aid: str) -> list[dict]:
    data = (_get(f"/audiences/{aid}/contacts", key) or {}).get("data") or []
    # Newest first.
    return sorted(data, key=lambda c: c.get("created_at", ""), reverse=True)


def main() -> int:
    key = os.environ.get("RESEND_API_KEY", "").strip()
    if not key:
        print("Set RESEND_API_KEY (a full-access key) and re-run.", file=sys.stderr)
        return 1
    try:
        aid = _audience_id(key)
        contacts = _contacts(key, aid)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        if code in (401, 403):
            print("Key rejected — this needs a FULL-ACCESS Resend key "
                  "(resend.com → API Keys).", file=sys.stderr)
        else:
            print(f"Resend API error ({code}).", file=sys.stderr)
        return 1

    active = [c for c in contacts if not c.get("unsubscribed")]
    csv_path = None
    if "--csv" in sys.argv:
        i = sys.argv.index("--csv")
        csv_path = sys.argv[i + 1] if i + 1 < len(sys.argv) else "subscribers.csv"

    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["email", "status", "joined", "first_name", "last_name"])
            for c in contacts:
                w.writerow([
                    c.get("email", ""),
                    "unsubscribed" if c.get("unsubscribed") else "subscribed",
                    (c.get("created_at", "") or "")[:10],
                    c.get("first_name", "") or "",
                    c.get("last_name", "") or "",
                ])
        print(f"Wrote {len(contacts)} contact(s) to {csv_path}")
        return 0

    print(f"\n  dAIly subscribers — audience {aid}")
    print(f"  {len(active)} subscribed · {len(contacts) - len(active)} unsubscribed "
          f"· {len(contacts)} total\n")
    print(f"  {'EMAIL':<40} {'STATUS':<13} JOINED")
    print(f"  {'-'*40} {'-'*12} {'-'*10}")
    for c in contacts:
        status = "unsubscribed" if c.get("unsubscribed") else "subscribed"
        print(f"  {c.get('email',''):<40} {status:<13} {(c.get('created_at','') or '')[:10]}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
