#!/usr/bin/env python3
"""Pull FAST channel schedules from the PCC airings API and write site data.

Outputs (under --out, default site/data):
  runway.json  channel runway: last airing end per channel, tiers, inactive list
  grid.json    airings for the EPG grid, compact, all monitored channels

Needs env PCC_API_KEY. Exits non-zero if any monitored channel cannot be read, so a
scheduled run fails loudly instead of publishing stale or partial data.
"""
import argparse, html, json, os, re, sys, time, datetime as dt
from zoneinfo import ZoneInfo
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


def find_gaps(airings, now_ms, horizon_ms, tol_ms):
    """Empty stretches between now and the horizon. The tail after the last airing is runway, not a gap."""
    rows = sorted((a for a in airings if a["s"] and a["e"]), key=lambda a: a["s"])
    cursor, gaps = now_ms, []
    for a in rows:
        if a["e"] <= cursor:
            continue
        if a["s"] - cursor > tol_ms and cursor < horizon_ms:
            gaps.append((cursor, min(a["s"], horizon_ms)))
        cursor = max(cursor, a["e"])
        if cursor >= horizon_ms:
            break
    return gaps


PT = ZoneInfo("America/Los_Angeles")
ET = ZoneInfo("America/New_York")


def next_block(end_ms):
    """Schedules are loaded as month blocks ending at midnight Eastern. Work out which block is missing."""
    e = dt.datetime.fromtimestamp((end_ms - 6 * 3600 * 1000) / 1000, ET)  # last programs can spill past midnight
    through = e.strftime("%b ") + str(e.day)
    if (e + dt.timedelta(days=1)).month != e.month:  # covered through month end
        nxt = (e.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        return through, nxt.strftime("%B")
    return through, "rest of " + e.strftime("%B")



def day_label(ms):
    d = dt.datetime.fromtimestamp(ms / 1000, PT)
    return d.strftime("%a, %b ") + str(d.day)


def time_label(ms):
    d = dt.datetime.fromtimestamp(ms / 1000, PT)
    return d.strftime("%a, %b ") + str(d.day) + ", " + str(int(d.strftime("%I"))) + d.strftime(":%M %p")


def dur_label(ms):
    m = ms / 60000
    if m < 120:
        return f"{int(round(m))} min"
    h = m / 60
    return f"{h:.0f} hrs" if h < 48 else f"{h / 24:.1f} days"


ROW = (
    '<tr bgcolor="{bg}"><td style="padding:6px 8px 6px 16px;color:#0B1A3E;font-family:Helvetica,Arial,sans-serif;font-size:14px;">{name}{sub}</td>'
    '<td align="right" style="padding:6px 16px 6px 8px;color:#1750A8;font-weight:bold;white-space:nowrap;font-family:Helvetica,Arial,sans-serif;font-size:14px;">{days}</td></tr>'
)


def needs_sub(c, now_ms):
    if not c.get("needs"):
        return ""
    return ('<div style="font-size:12px;color:#5E5E5E;padding-top:1px;">Through ' + c["through"] + " &middot; needs "
            + html.escape(c["needs"]) + "</div>")


def tier_block(chs, now_ms):
    if not chs:
        return '<div style="padding:8px 0 0 16px;font-family:Helvetica,Arial,sans-serif;font-size:14px;color:#5E5E5E;">None.</div>'
    rows = []
    for i, c in enumerate(chs):
        days = "no schedule" if c["days_left"] is None else f'{c["days_left"]:.1f} days left'
        rows.append(ROW.format(bg="#FFFFFF" if i % 2 == 0 else "#F4F5F8", name=html.escape(c["name"]), days=days, sub=needs_sub(c, now_ms)))
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:8px;">'
            + "".join(rows) + "</table>")


def headsup_block(shown, asof_ms):
    horizon = asof_ms + C.HEADSUP_DAYS * 86400000
    groups = {}
    for c in shown:
        r = c.get("red_on_ms")
        if r and asof_ms < r <= horizon:
            groups.setdefault(day_label(r), []).append(c)
    if not groups:
        return ""
    lines = []
    for lab, chs in sorted(groups.items(), key=lambda kv: min(c["red_on_ms"] for c in kv[1])):
        n = len(chs)
        lines.append(f'<div style="padding:2px 0;"><b>{n} channel{"" if n == 1 else "s"}</b> enter{"s" if n == 1 else ""} the red zone on <b>{lab}</b></div>')
    return ('<tr><td style="padding:16px 32px 0 32px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            '<td bgcolor="#F4F5F8" style="background:#F4F5F8;border-left:4px solid #0D1551;padding:12px 16px;font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:20px;color:#0B1A3E;">'
            '<div style="font-weight:bold;padding-bottom:4px;">Heads-up: next 10 days</div>' + "".join(lines) +
            '<div style="font-size:12px;color:#5E5E5E;padding-top:4px;">Based on each channel\'s last scheduled airing. Scheduling more content moves these dates out.</div>'
            '</td></tr></table></td></tr>')


def gaps_section(shown):
    gl = [c for c in shown if c.get("gap")]
    n = len(gl)
    head = ('<tr><td style="padding:24px 32px 0 32px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            '<td width="4" bgcolor="#1C7293" style="background:#1C7293;">&nbsp;</td>'
            '<td style="padding:2px 0 2px 12px;font-size:17px;font-weight:bold;color:#0B1A3E;font-family:Helvetica,Arial,sans-serif;">Gaps '
            f'<span style="font-weight:normal;color:#5E5E5E;font-size:14px;">empty stretches in the next {C.GAP_HORIZON_DAYS} days &middot; {n} channel{"" if n == 1 else "s"}</span></td></tr></table>')
    if not gl:
        return head + '<div style="padding:8px 0 0 16px;font-family:Helvetica,Arial,sans-serif;font-size:14px;color:#5E5E5E;">None.</div></td></tr>'
    rows = []
    for i, c in enumerate(sorted(gl, key=lambda c: c["gap"]["start_ms"])):
        g = c["gap"]
        extra = f' (+{g["count"] - 1} more)' if g["count"] > 1 else ""
        rows.append(ROW.format(bg="#FFFFFF" if i % 2 == 0 else "#F4F5F8", name=html.escape(c["name"]),
                               days=f'{time_label(g["start_ms"])} &middot; {dur_label(g["end_ms"] - g["start_ms"])}{extra}', sub=""))
    return head + ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:8px;">'
                   + "".join(rows) + "</table></td></tr>")


def render_email(runway, template):
    shown = [c for c in runway["channels"] if c["email"]]
    by = {t: [c for c in shown if c["tier"] == t] for t in ("red", "amber", "green")}
    asof = dt.datetime.fromtimestamp(runway["asof_ms"] / 1000, ZoneInfo("America/Los_Angeles"))
    asof_txt = asof.strftime("%a, %b ") + str(asof.day) + asof.strftime(", ") + str(int(asof.strftime("%I"))) + asof.strftime(":%M %p")
    out = re.sub(r"(__(?:RED|AMBER|GREEN)_COUNT__) channels", r"\1", template)  # label is added below
    out = out.replace("__ASOF__", asof_txt)
    for t in ("red", "amber", "green"):
        n = len(by[t])
        out = out.replace(f"__{t.upper()}_COUNT__", f"{n} channel" + ("" if n == 1 else "s"))
        out = out.replace(f"__{t.upper()}_BLOCK__", tier_block(by[t], runway["asof_ms"]))
    out = out.replace("__INACTIVE__", str(len(runway["inactive"])))
    out = out.replace("__HEADSUP_BLOCK__", headsup_block(shown, runway["asof_ms"]))
    out = out.replace("__GAPS_SECTION__", gaps_section(shown))
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

    # Per-channel enrichment: gaps and the date each channel would enter the red zone.
    horizon = now_ms + C.GAP_HORIZON_DAYS * 86400000
    tol = C.GAP_TOLERANCE_MIN * 60000
    by_slug = {n["slug"]: n for n in grid_nets}
    for c in channels:
        c["red_on_ms"] = None
        if c["end_ms"] is not None and c["days_left"] is not None and c["days_left"] >= C.RED_DAYS:
            c["red_on_ms"] = c["end_ms"] - C.RED_DAYS * 86400000
        c["through"] = c["needs"] = c["due_ms"] = None
        if c["end_ms"] is not None:
            c["through"], c["needs"] = next_block(c["end_ms"])
            c["due_ms"] = c["end_ms"] - C.GREEN_DAYS * 86400000
        c["gap"] = None
        net = by_slug.get(c["slug"])
        if net:
            gaps = find_gaps(net["airings"], now_ms, min(horizon, c["end_ms"] or horizon), tol)
            if gaps:
                c["gap"] = {"start_ms": gaps[0][0], "end_ms": gaps[0][1], "count": len(gaps),
                            "total_min": round(sum(b - a for a, b in gaps) / 60000)}

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "runway.json"), "w") as f:
        json.dump(runway, f, separators=(",", ":"))
    with open(os.path.join(a.out, "grid.json"), "w") as f:
        json.dump(grid, f, separators=(",", ":"))

    here = os.path.dirname(os.path.abspath(__file__))
    tpl = next((os.path.join(here, n) for n in ("email_template.html", "email-template.html")
                if os.path.exists(os.path.join(here, n))), None)
    if tpl is None:
        sys.exit("email template not found in scripts/ (email_template.html or email-template.html)")
    with open(tpl, encoding="utf-8") as f:
        email_html = render_email(runway, f.read())
    with open(os.path.join(a.out, "email.html"), "w", encoding="utf-8") as f:
        f.write(email_html)

    n = sum(len(x["airings"]) for x in grid_nets)
    tiers = {t: sum(1 for c in channels if c["tier"] == t) for t in ("red", "amber", "green")}
    print(f"ok: {len(channels)} channels {tiers}, {n} airings, {len(still_inactive)} inactive, newly active: {newly}")


if __name__ == "__main__":
    main()
