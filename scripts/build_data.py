#!/usr/bin/env python3
"""Pull FAST channel schedules from the PCC airings API and write site data.

Outputs (under --out, default site/data):
  runway.json  channel runway: last airing end per channel, tiers, inactive list
  grid.json    airings for the EPG grid, compact, all monitored channels

Needs env PCC_API_KEY. Exits non-zero if any monitored channel cannot be read, so a
scheduled run fails loudly instead of publishing stale or partial data.
"""
import argparse, json, os, re, sys, time, datetime as dt
import urllib.request, urllib.parse, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(__file__))
import config as C

KEY = os.environ.get("PCC_API_KEY", "")


def iso_to_ms(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)  # +0000 -> +00:00
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1000)


def call(params, tries=4):
    q = urllib.parse.urlencode({"apikey": KEY, **params})
    url = f"{C.API_BASE}?{q}"
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "roz-ier/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (401, 403):
                break  # bad key, do not hammer
        except Exception as e:  # network, timeout, bad json
            last = type(e).__name__
        time.sleep(2 ** i)
    raise RuntimeError(f"{params.get('network')}: {last}")


def last_end_ms(slug, far_from, far_to):
    d = call({"network": slug, "from": far_from, "to": far_to, "rows": 1, "sort": "start desc"})
    rows = d.get("rows") or []
    return iso_to_ms(rows[0].get("end")) if rows else None


def tobool(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def compact(row):
    p = row.get("properties") or {}
    pp = (row.get("program") or {}).get("properties") or {}
    rating = ""
    for r in row.get("ratings") or []:
        if r.get("rating"):
            rating = r["rating"]
            break
    vchips = pp.get("vChips")
    if isinstance(vchips, list):
        vchips = ", ".join(str(x) for x in vchips)
    series = ""
    for c in (row.get("program") or {}).get("categories") or []:
        if c.get("type") == "series" and c.get("name"):
            series = c["name"]
            break
    return {
        "s": iso_to_ms(row.get("start")),
        "e": iso_to_ms(row.get("end")),
        "t": (row.get("program") or {}).get("title") or p.get("title") or "",
        "d": pp.get("description") or pp.get("shortDescription") or "",
        "oa": pp.get("originalAirDate") or "",
        "se": pp.get("seasonNumber"),
        "ep": pp.get("seasonEpisodeNumber"),
        "sy": pp.get("seasonYear"),
        "r": rating or pp.get("parentalRating") or "",
        "v": vchips or "",
        "rd": pp.get("ext.id.radar") or "",
        "h": p.get("houseNumber") or "",
        "k": iso_to_ms(p.get("killDateTimestamp")),
        "sr": series,
        "ra": tobool(p.get("reAir")),
        "lv": tobool(p.get("isLive")),
    }


def grid_rows(slug, frm, to):
    out, start, total = [], 0, None
    while total is None or start < total:
        d = call({"network": slug, "from": frm, "to": to, "rows": 1000, "start": start, "sort": "start asc",
                   "includeRelatedProperties": "true"})
        rows = d.get("rows") or []
        total = d.get("total", len(rows))
        out.extend(compact(r) for r in rows)
        if not rows:
            break
        start += len(rows)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data")
    ap.add_argument("--only", help="comma separated slugs, for testing")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if not KEY:
        sys.exit("PCC_API_KEY is not set")

    now = dt.datetime.now(dt.timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    far_from = (now - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    far_to = (now + dt.timedelta(days=730)).strftime("%Y-%m-%d")
    g_from = (now - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    g_to = (now + dt.timedelta(days=C.GRID_DAYS_AHEAD + 2)).strftime("%Y-%m-%d")

    monitored = dict(C.MONITORED)
    inactive = [s for s in C.INACTIVE if s not in C.SUPPRESSED]
    if a.only:
        keep = set(a.only.split(","))
        monitored = {k: v for k, v in monitored.items() if k in keep}
        inactive = [s for s in inactive if s in keep]

    ends, failures = {}, []
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(last_end_ms, s, far_from, far_to): s for s in list(monitored) + inactive}
        for f in as_completed(futs):
            s = futs[f]
            try:
                ends[s] = f.result()
            except Exception as e:
                failures.append(str(e))
    if failures:
        print("FAILED channels:\n  " + "\n  ".join(sorted(failures)), file=sys.stderr)
        sys.exit(1)

    # Inactive channels that now have a schedule become monitored.
    newly = [s for s in inactive if ends.get(s)]
    for s in newly:
        monitored[s] = None
    still_inactive = [s for s in inactive if not ends.get(s)]

    def disp(s):
        return monitored.get(s) or s

    channels = []
    for s in monitored:
        end = ends.get(s)
        days = None if end is None else (end - now_ms) / 86400000
        tier = "red" if days is None or days < C.RED_DAYS else ("amber" if days < C.GREEN_DAYS else "green")
        channels.append({
            "slug": s, "name": disp(s), "end_ms": end,
            "days_left": None if days is None else round(days, 1),
            "tier": tier, "email": s not in C.EMAIL_EXCLUDE,
        })
    channels.sort(key=lambda c: (c["days_left"] is not None, c["days_left"] or 0))

    runway = {"asof_ms": now_ms, "channels": channels,
              "inactive": [disp(s) if s in monitored else s for s in still_inactive],
              "red_days": C.RED_DAYS, "green_days": C.GREEN_DAYS}

    # Grid data (only channels that have airings)
    grid_nets, gfail = [], []
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(grid_rows, s, g_from, g_to): s for s in monitored if ends.get(s)}
        res = {}
        for f in as_completed(futs):
            s = futs[f]
            try:
                res[s] = f.result()
            except Exception as e:
                gfail.append(str(e))
    if gfail:
        print("FAILED grid pulls:\n  " + "\n  ".join(sorted(gfail)), file=sys.stderr)
        sys.exit(1)
    for s in monitored:
        if s in res:
            grid_nets.append({"slug": s, "name": disp(s), "airings": res[s]})
    grid = {"asof_ms": now_ms, "from": g_from, "to": g_to, "networks": grid_nets}

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "runway.json"), "w") as f:
        json.dump(runway, f, separators=(",", ":"))
    with open(os.path.join(a.out, "grid.json"), "w") as f:
        json.dump(grid, f, separators=(",", ":"))

    n = sum(len(x["airings"]) for x in grid_nets)
    tiers = {t: sum(1 for c in channels if c["tier"] == t) for t in ("red", "amber", "green")}
    print(f"ok: {len(channels)} channels {tiers}, {n} airings, {len(still_inactive)} inactive, newly active: {newly}")


if __name__ == "__main__":
    main()
