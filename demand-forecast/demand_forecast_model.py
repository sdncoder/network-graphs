"""
demand-forecast — NetworkX model of per-event bandwidth from the BOC
event workbooks (demand-forecast/*.xlsx).

Each workbook is one remote production. The program reads two sheets:
  * BOC          event name, date, game time, TX window, network, truck, PCRs
  * Connectivity data circuits (EPL, Bitfire HSIP), Bitfire streams in each
                 direction, bonded-cellular (LiveU) streams

Bandwidth rules (all in Mbps)
  * Data circuits use the number in the Bandwith column. An origin-port note
    such as "WE TAKE 500MB" caps the usable rate at that figure.
  * A Bitfire stream marked "*40" is 40 Mbps.
  * A stream is ASSIGNED when it has a description (other than "Unassigned")
    or a destination port; otherwise it is a SPARE encoder slot on the truck.
  * Needed  = EPL data + assigned Bitfire streams (site -> CT Prod Hub).
  * Full build = EPL data + every Bitfire slot listed (assigned + spare).
  * Bonded cellular (LiveU) rides the cellular network, not the fiber, and
    is reported separately.

Every circuit and every stream is its own edge in a MultiGraph:
    TRUCK -- carrier -- CT PROD HUB   (EPL, HSIP circuit, one edge per stream)
    TRUCK -- LiveU cellular -- CT PROD HUB

Graphics (straight lines only, every line checked for visibility):
  * bandwidth_per_event.png   stacked bars: needed vs full build vs circuit
  * event_paths.png           one panel per event, one line per stream
  * hub_timeline.png     concurrent Site->CT Prod Hub demand across TX windows

Run:
    pip install networkx matplotlib openpyxl
    python demand_forecast_model.py [xlsx ...] [--out DIR]
"""
import argparse
import csv
import glob
import math
import os
import re
from datetime import datetime, timedelta

import networkx as nx
import openpyxl
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyBboxPatch

HERE = os.path.dirname(os.path.abspath(__file__))
STREAM_MBPS = 40           # "*40" Bitfire stream
HUB = "CT Prod Hub"        # production hub the trucks feed (sanitized name)
YEAR = 2026
BLACK = "#1a1a1a"
C_EPL, C_UP, C_SPARE, C_DOWN, C_CELL = "#2a6f97", "#c8553d", "#e9b8a9", "#588157", "#8a6fb3"

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
SECTIONS = {   # section header prefix -> kind; direction is read from "SITE >" / "> SITE"
    "DATA CIRCUITS": "data",
    "BITFIRE TRANSMISSION": "bf",
    "BONDED CELLULAR TRANSMISSION": "cell",
    "LIVEU TRANSMISSION": "cell",
    "ADDITONAL FEEDS": "other",
    "ADDITIONAL FEEDS": "other",
}


def section_of(key):
    kind = next((v for k, v in SECTIONS.items() if key.startswith(k)), None)
    if kind in ("bf", "cell"):
        kind += "_up" if re.search(r"SITE\s*>", key) else "_down"
    return kind


def clean(v):
    if v is None:
        return ""
    return str(v).replace("\xa0", " ").strip()


def boc_fields(ws):
    f = {}
    rows = [[clean(v) for v in r] for r in ws.iter_rows(values_only=True)]
    for r in rows:
        if len(r) > 4 and r[3].endswith(":"):
            f[r[3].rstrip(":").strip().upper()] = r[4]
    titles = [r[3] for r in rows if len(r) > 3 and r[3] and not r[3].endswith(":")][:3]
    f["SERIES"], f["WEEK"], f["MATCHUP"] = (titles + ["", "", ""])[:3]
    return f


def parse_window(text):
    """'11/8 10:00 ET - 11/8 23:59 ET', '11/9 @ 6:00 - 11/11 @ 6:00 ET',
    'FRI 11/13, 10am -SAT 00:59am' -> (start, end) datetimes."""
    pts = re.findall(r"(\d{1,2})/(\d{1,2})\D*?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text, re.I)
    times = []
    for i, (mo, d, h, mi, ap) in enumerate(pts[:2]):
        h, mi = int(h), int(mi or 0)
        if ap and ap.lower() == "pm" and h < 12:
            h += 12
        times.append(datetime(YEAR, int(mo), int(d), h % 24, mi))
    if len(times) == 1:   # "FRI 11/13, 10am -SAT 00:59am": end has no date
        m = re.search(r"-\s*\w*\s*(\d{1,2}):(\d{2})", text)
        end = times[0].replace(hour=int(m.group(1)), minute=int(m.group(2)))
        if end <= times[0]:
            end += timedelta(days=1)
        times.append(end)
    return times[0], times[1]


MONTHS = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL",
                                           "AUG", "SEP", "OCT", "NOV", "DEC"])}


def game_day(text, fallback):
    m = re.search(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\w*\s+(\d{1,2})", text.upper())
    return datetime(YEAR, MONTHS[m.group(1)], int(m.group(2))) if m else fallback


def mbps(v):
    s = clean(v)
    m = re.search(r"\d+(\.\d+)?", s)
    return float(m.group()) if m else None


def connectivity(ws):
    rows = []
    sect, idx = None, {}
    header = None
    for r in ws.iter_rows(values_only=True):
        r = [clean(v) for v in r] + [""] * 18
        key = r[2].upper()
        if key == "SERVICE #":
            header = r
            continue
        hit = section_of(key)
        if hit:
            sect = hit
            continue
        if not header or not sect or not r[2]:
            continue
        idx[sect] = idx.get(sect, 0) + 1
        rows.append(dict(section=sect, n=idx[sect], svc=r[2], desc=r[3], audio=r[4],
                         enc=r[5], bw=r[6], route=r[8], src_port=r[9], dst_port=r[10],
                         svc_id=r[11]))
    return rows


def load_event(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    boc = boc_fields(wb["BOC"])
    rows = connectivity(wb["Connectivity"])
    start, end = parse_window(boc.get("TX WINDOW", ""))
    truck = re.sub(r"^(GCV|GVC|LMG)\s*-?\s*", "", boc.get("TRUCK", ""), flags=re.I).strip()
    ev = dict(file=os.path.basename(path), series=boc["SERIES"], matchup=event_type(path, boc["WEEK"]),
              date=boc.get("DATE", ""), game_time=boc.get("GAME TIME", ""),
              network=boc.get("NETWORK", ""), truck=boc.get("TRUCK", ""), truck_short=truck,
              pcr=boc.get("GAME PCR", ""), php=boc.get("PHP PCR", ""), video=boc.get("VIDEO", ""),
              start=start, end=end, game_day=game_day(boc.get("DATE", ""), start), rows=rows, flags=[])

    data = [r for r in rows if r["section"] == "data"]
    epl = next((r for r in data if "EPL" in r["desc"].upper()), None)
    hsip = next((r for r in data if "HSIP" in r["desc"].upper()), None)

    def usable(r):
        cap = mbps(r["bw"]) or 0
        note = re.search(r"WE TAKE\s*(\d+)\s*MB", r["src_port"].upper())
        return (min(cap, float(note.group(1))) if note else cap), cap

    ev["epl"], ev["epl_ordered"] = usable(epl)
    ev["hsip"], ev["hsip_ordered"] = usable(hsip)
    ev["carrier"] = carrier_of(hsip["route"]) or carrier_of(epl["route"])
    ev["venue"] = venue_of(hsip["route"])

    seen = {}
    others = {}
    for r in rows:
        r["mbps"] = STREAM_MBPS if "40" in r["bw"] else (mbps(r["bw"]) or 0)
        d = r["desc"].lower()
        # assigned: a real description, or (blank description) a service id / receive port
        r["assigned"] = bool(r["desc"] and "unassigned" not in d) or \
            (not r["desc"] and bool(r["svc_id"]) and r["section"] in ("bf_up", "bf_down"))
        r["label"] = f"{r['svc'].split('.')[0]}.{r['n']}" if r["section"] != "data" else r["svc"]
        r["dup"] = False
        if r["section"] in ("bf_up", "bf_down"):
            port = r["src_port"] if r["section"] == "bf_up" else r["dst_port"]
            m = re.search(r"\b[TR]X\s*0?(\d+)", port.upper())
            slot = (r["section"], int(m.group(1))) if m else (r["section"], f"row{r['n']}")
            r["slot"] = slot[1]
            if slot in seen:               # same truck slot listed twice
                if r["assigned"] and not seen[slot]["assigned"]:
                    seen[slot]["dup"] = True
                    seen[slot] = r
                else:
                    r["dup"] = True
            else:
                seen[slot] = r
            # template leftovers: rows naming a different truck or venue
            u = (port + " " + r["route"]).upper()
            if truck and port and truck_key(truck) not in port.upper():
                who = truck_key(re.sub(r"\s*[TR]X.*$", "", port.upper()))
                others.setdefault(f"truck {who.title()}", []).append(r["label"])
            elif ev["venue"] and ev["venue"].upper() not in u:
                hops = [p for p in r["route"].upper().split(">") if "BITFIRE" in p]
                who = hops[:1] if r["section"] == "bf_up" else hops[-1:]
                if who:
                    others.setdefault("another venue", []).append(r["label"])
    for who, labs in others.items():
        ev["flags"].append(f"rows {', '.join(sorted(set(labs)))} still name {who} (copied from another event)")
    dups = [r["label"] for r in rows if r["dup"]]
    if dups:
        ev["flags"].append(f"rows {', '.join(dups)} repeat a truck slot already listed (counted once)")
    rows[:] = [r for r in rows if not r["dup"]]

    up = [r for r in rows if r["section"] == "bf_up"]
    dn = [r for r in rows if r["section"] == "bf_down"]
    cell = [r for r in rows if r["section"] in ("cell_up", "cell_down")]
    ev["up_assigned"] = sum(r["mbps"] for r in up if r["assigned"])
    ev["up_spare"] = sum(r["mbps"] for r in up if not r["assigned"])
    ev["dn_assigned"] = sum(r["mbps"] for r in dn if r["assigned"])
    ev["dn_spare"] = sum(r["mbps"] for r in dn if not r["assigned"])
    ev["n_up"] = (sum(r["assigned"] for r in up), len(up))
    ev["n_dn"] = (sum(r["assigned"] for r in dn), len(dn))
    ev["n_cell_up"] = sum(r["section"] == "cell_up" for r in cell)
    ev["n_cell_dn"] = sum(r["section"] == "cell_down" for r in cell)
    ev["cell_mbps"] = sum(r["mbps"] for r in cell)
    ev["needed"] = ev["epl"] + ev["up_assigned"]
    ev["full"] = ev["epl"] + ev["up_assigned"] + ev["up_spare"]
    ev["fiber"] = ev["epl"] + ev["hsip"]
    ev["hsip_util"] = ev["up_assigned"] / ev["hsip"] if ev["hsip"] else 0
    ev["hsip_full_util"] = (ev["up_assigned"] + ev["up_spare"]) / ev["hsip"] if ev["hsip"] else 0
    if ev["hsip_ordered"] != ev["hsip"]:
        ev["flags"].append(f"HSIP ordered at {ev['hsip_ordered']:.0f} Mbps but only {ev['hsip']:.0f} usable (origin-port note)")
    if ev["hsip_full_util"] > 1:
        ev["flags"].append(f"all {ev['n_up'][1]} TX slots ({ev['up_assigned'] + ev['up_spare']:.0f} Mbps) "
                           f"would exceed the {ev['hsip']:.0f} Mbps HSIP")
    return ev


def event_type(path, series):
    """'MCBB Big East · Week 1' from the file name and BOC series; no team names."""
    m = re.search(r"\b([MW]CBB)\b", os.path.basename(path).replace("_", " ").upper())
    kind = m.group(1) if m else "CBB"
    conf = re.sub(r"\s*Basketball.*$", "", series, flags=re.I).strip()
    wk = re.search(r"WEEK\s*(\d+)", series, re.I)
    return f"{kind} {conf}" + (f" · Week {wk.group(1)}" if wk else "")


def truck_key(truck):
    words = [w for w in re.findall(r"[A-Z]{2,}", truck.upper()) if w not in ("GCV", "GVC", "LMG")]
    return words[0] if words else truck.upper()


def carrier_of(route):
    u = route.upper()
    for k, name in (("SEGRA", "Frontier/Segra"), ("FRONTIER", "Frontier/Segra"),
                    ("ATT", "AT&T"), ("LUMEN", "Lumen")):
        if k in u:
            return name
    return "Carrier"


def venue_of(route):
    m = re.match(r"\s*(.*?)\s*BITFIRE", route.upper())
    v = (m.group(1) if m else route).strip()
    return v.title() if len(v) > 3 else v


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------
def build_graph(events):
    """One MultiGraph for all events. Nodes are namespaced per event so each
    event's truck, carrier hand-off and CT Prod Hub receive are separate."""
    g = nx.MultiGraph()
    for i, ev in enumerate(events):
        t, c, s, l = f"E{i}:truck", f"E{i}:carrier", f"E{i}:hub", f"E{i}:liveu"
        g.add_node(t, kind="truck", label=ev["truck_short"], event=i)
        g.add_node(c, kind="carrier", label=ev["carrier"], event=i)
        g.add_node(s, kind="hub", label=HUB.replace(" Prod ", "\nProd "), event=i)
        for hop in ((t, c), (c, s)):
            g.add_edge(*hop, kind="epl", mbps=ev["epl"], label="EPL data")
            g.add_edge(*hop, kind="hsip", mbps=ev["hsip"], label="Bitfire HSIP")
        for r in ev["rows"]:
            if r["section"] in ("bf_up", "bf_down"):
                for hop in ((t, c), (c, s)):
                    g.add_edge(*hop, kind=r["section"], mbps=r["mbps"], assigned=r["assigned"],
                               label=r["desc"] or r["label"])
            if r["section"] in ("cell_up", "cell_down"):
                g.add_node(l, kind="liveu", label="LiveU\ncellular", event=i)
                for hop in ((t, l), (l, s)):
                    g.add_edge(*hop, kind=r["section"], mbps=r["mbps"], assigned=True, label=r["label"])
    return g


# ---------------------------------------------------------------------------
# Graphics
# ---------------------------------------------------------------------------
def event_title(ev):
    return f"{ev['matchup']}\n{ev['game_day']:%a %-m/%-d}  ·  {ev['truck']}  ·  {ev['network']}"


def draw_bars(events, out):
    fig, ax = plt.subplots(figsize=(13, 6.4))
    names = [f"{ev['game_day']:%a %-m/%-d}  {ev['matchup']}" for ev in events]
    y = range(len(events))
    left = [0] * len(events)
    for key, color, lab in (("epl", C_EPL, "EPL data"), ("up_assigned", C_UP, "Assigned Bitfire streams"),
                            ("up_spare", C_SPARE, "Spare truck TX slots")):
        vals = [ev[key] for ev in events]
        ax.barh(y, vals, left=left, color=color, height=0.52, label=lab, edgecolor="white", lw=1)
        left = [a + b for a, b in zip(left, vals)]
    for i, ev in enumerate(events):
        ax.plot([ev["fiber"]] * 2, [i - 0.36, i + 0.36], color=BLACK, lw=2.4)
        ax.text(ev["needed"] / 2 + ev["epl"] / 2, i, f"{ev['needed']:,.0f} needed", ha="center",
                va="center", color="white", fontsize=10.5, fontweight="bold")
        ax.text(max(ev["full"], ev["fiber"]) + 25, i,
                f"full build {ev['full']:,.0f}  ·  usable fiber {ev['fiber']:,.0f} Mbps",
                va="center", fontsize=10, color="#333")
    ax.set_yticks(list(y), names, fontsize=11)
    ax.invert_yaxis()
    ax.set_xlabel("Mbps, site → CT Prod Hub", fontsize=11)
    ax.set_xlim(0, max(max(ev["full"], ev["fiber"]) for ev in events) * 1.45)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    handles, labels = ax.get_legend_handles_labels()
    handles.append(Line2D([0], [0], color=BLACK, lw=2.4))
    labels.append("Usable fiber (EPL + HSIP)")
    ax.legend(handles, labels, loc="lower right", frameon=False, fontsize=10)
    ax.set_title("Bandwidth needed per event", fontsize=16, fontweight="bold", loc="left")
    fig.tight_layout()
    fig.savefig(out, dpi=130, facecolor="white")
    plt.close(fig)


def seg_point_dist(p, a, b):
    (px, py), (ax_, ay), (bx, by) = p, a, b
    dx, dy = bx - ax_, by - ay
    t = max(0, min(1, ((px - ax_) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax_ + t * dx), py - (ay + t * dy))


PANEL_POS = {"truck": (0, 0), "carrier": (5, 0), "hub": (10, 0), "liveu": (5, -3.3)}
NODE_R = 1.0
GAP = 0.072


def panel_lines(g, i):
    """(u, v, kind, assigned, p, q) for every edge of event i, parallel
    edges offset side by side."""
    groups = {}
    for u, v, d in g.edges(data=True):
        if g.nodes[u]["event"] != i:
            continue
        groups.setdefault((u, v), []).append(d)
    out = []
    order = {"epl": 0, "hsip": 1, "bf_up": 2, "bf_down": 3, "cell_up": 4, "cell_down": 5}
    for (u, v), ds in groups.items():
        ds = sorted(ds, key=lambda d: (order[d["kind"]], not d.get("assigned", True)))
        (x1, y1), (x2, y2) = PANEL_POS[g.nodes[u]["kind"]], PANEL_POS[g.nodes[v]["kind"]]
        L = math.hypot(x2 - x1, y2 - y1)
        nx_, ny_ = -(y2 - y1) / L, (x2 - x1) / L
        n = len(ds)
        for k, d in enumerate(ds):
            off = (k - (n - 1) / 2) * GAP
            out.append((u, v, d, (x1 + nx_ * off, y1 + ny_ * off), (x2 + nx_ * off, y2 + ny_ * off)))
    return out


def check_visibility(g, events):
    """Every line clears every node it doesn't end on, and parallel lines in a
    bundle stay inside the node they land on (so each one is visible)."""
    problems = []
    for i in range(len(events)):
        nodes = {n: PANEL_POS[d["kind"]] for n, d in g.nodes(data=True) if d["event"] == i}
        lines = panel_lines(g, i)
        for u, v, d, p, q in lines:
            for n, c in nodes.items():
                if n not in (u, v) and seg_point_dist(c, p, q) < NODE_R + 0.15:
                    problems.append(f"event {i}: {u}-{v} passes {n}")
        bundle = {}
        for u, v, *_ in lines:
            bundle[(u, v)] = bundle.get((u, v), 0) + 1
        for (u, v), n in bundle.items():
            if (n - 1) * GAP / 2 > NODE_R * 0.95:
                problems.append(f"event {i}: {u}-{v} bundle of {n} wider than the node")
    return problems


STYLE = {
    "epl": dict(color=C_EPL, lw=2.6, ls="-"),
    "hsip": dict(color=BLACK, lw=2.6, ls="-"),
    "bf_up": dict(color=C_UP, lw=1.6, ls="-"),
    "bf_down": dict(color=C_DOWN, lw=1.6, ls="-"),
    "cell_up": dict(color=C_CELL, lw=1.6, ls="-"),
    "cell_down": dict(color=C_CELL, lw=1.6, ls=(0, (3, 2))),
}


def draw_paths(g, events, out):
    fig, axes = plt.subplots(len(events), 1, figsize=(13, 4.9 * len(events)))
    for i, (ax, ev) in enumerate(zip(axes, events)):
        ax.set_aspect("equal")
        ax.axis("off")
        for u, v, d, p, q in panel_lines(g, i):
            st = dict(STYLE[d["kind"]])
            if not d.get("assigned", True):
                st.update(color=C_SPARE, ls=(0, (2, 2)), lw=1.3)
            ax.plot([p[0], q[0]], [p[1], q[1]], solid_capstyle="butt", zorder=1, **st)
        for n, d in g.nodes(data=True):
            if d["event"] != i:
                continue
            x, y = PANEL_POS[d["kind"]]
            if d["kind"] == "carrier":
                ax.add_patch(FancyBboxPatch((x - 1.1, y - 0.95), 2.2, 1.9,
                                            boxstyle="round,pad=0,rounding_size=0.35",
                                            fc="white", ec=BLACK, lw=2.2, zorder=4))
            else:
                ax.add_patch(Circle((x, y), NODE_R, fc="white", ec=BLACK, lw=2.6, zorder=4))
            ax.text(x, y, d["label"], ha="center", va="center", fontsize=10.5,
                    fontweight="bold", zorder=5)
        # label boxes on the truck->carrier hop, CT Prod Hub->carrier hop
        a_up, t_up = ev["n_up"]
        a_dn, t_dn = ev["n_dn"]
        ax.text(2.5, 1.45, f"EPL {ev['epl']:.0f}  ·  HSIP {ev['hsip']:.0f} Mbps",
                ha="center", fontsize=10, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=BLACK, lw=1))
        ax.text(7.5, 1.45, f"↑ {a_up} of {t_up} TX = {ev['up_assigned']:.0f} Mbps"
                           f"\n↓ {a_dn} of {t_dn} RX = {ev['dn_assigned']:.0f} Mbps",
                ha="center", fontsize=10, fontweight="bold", linespacing=1.4,
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=BLACK, lw=1))
        if ev["n_cell_up"] or ev["n_cell_dn"]:
            ax.text(8.6, -2.2, f"LiveU ↑{ev['n_cell_up']} ↓{ev['n_cell_dn']} (cellular)",
                    ha="center", fontsize=9.5, color=C_CELL, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=C_CELL, lw=1))
        util = f"HSIP {ev['hsip_util']:.0%} used, {ev['hsip_full_util']:.0%} at full build"
        ax.text(-1.1, 3.0, event_title(ev), fontsize=12, fontweight="bold", va="bottom")
        ax.text(-1.1, 2.95, f"Needed {ev['needed']:,.0f} Mbps  ·  {util}", fontsize=10.5, va="top",
                color="#c62828" if ev["hsip_full_util"] > 1 else "#333")
        ax.set_xlim(-1.2, 11.2)
        ax.set_ylim(-4.4, 4.3)
    handles = [Line2D([0], [0], lw=2.6, **{k: v for k, v in STYLE["epl"].items() if k != "lw"}, label="EPL data"),
               Line2D([0], [0], lw=2.6, color=BLACK, label="Bitfire HSIP circuit"),
               Line2D([0], [0], lw=1.8, color=C_UP, label="Bitfire stream site→CT Prod Hub (40 Mbps)"),
               Line2D([0], [0], lw=1.8, color=C_DOWN, label="Bitfire return CT Prod Hub→site"),
               Line2D([0], [0], lw=1.6, color=C_SPARE, ls=(0, (2, 2)), label="Spare slot"),
               Line2D([0], [0], lw=1.8, color=C_CELL, label="LiveU cellular")]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=10.5)
    fig.suptitle("Event transport paths — one line per circuit and stream", fontsize=16,
                 fontweight="bold", x=0.05, ha="left", y=0.995)
    fig.tight_layout(rect=(0, 0.04, 1, 0.98))
    fig.savefig(out, dpi=110, facecolor="white")
    plt.close(fig)


def timeline(events, step=timedelta(minutes=30)):
    t0 = min(ev["start"] for ev in events)
    t1 = max(ev["end"] for ev in events)
    pts = []
    t = t0
    while t <= t1:
        live = [ev for ev in events if ev["start"] <= t < ev["end"]]
        pts.append((t, sum(ev["needed"] for ev in live), sum(ev["full"] for ev in live),
                    [ev["matchup"] for ev in live]))
        t += step
    return pts


def draw_timeline(events, out):
    pts = timeline(events)
    fig, ax = plt.subplots(figsize=(13, 5))
    ts = [p[0] for p in pts]
    ax.step(ts, [p[2] for p in pts], where="post", color=C_SPARE, lw=2, label="Full build")
    ax.step(ts, [p[1] for p in pts], where="post", color=C_UP, lw=2.6, label="Needed")
    ax.fill_between(ts, [p[1] for p in pts], step="post", color=C_UP, alpha=0.12)
    peak = max(pts, key=lambda p: p[1])
    ax.annotate(f"Peak {peak[1]:,.0f} Mbps\n" + " + ".join(peak[3]), (peak[0], peak[1]),
                xytext=(12, 10), textcoords="offset points", fontsize=10, fontweight="bold")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %-m/%-d"))
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.set_ylabel("Mbps into CT Prod Hub")
    ax.set_ylim(0, max(p[2] for p in pts) * 1.35)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("Concurrent demand into CT Prod Hub across TX windows (ET)", fontsize=15,
                 fontweight="bold", loc="left")
    fig.tight_layout()
    fig.savefig(out, dpi=130, facecolor="white")
    plt.close(fig)
    return peak


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def report(events, g, peak, vis):
    p = []
    w = p.append
    w("Demand forecast — bandwidth needed per event")
    w(f"Bitfire stream = {STREAM_MBPS} Mbps.  Needed = EPL + assigned site->CT Prod Hub streams.")
    w(f"Graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges (one per circuit or stream per hop)")
    w("")
    w(f"{'Date':6} {'Event':32} {'Truck':14} {'EPL':>5} {'HSIP':>5} {'TX a/t':>7} {'Up':>5} "
      f"{'RX a/t':>7} {'Down':>5} {'Needed':>7} {'Full':>6} {'HSIP%':>6} {'Full%':>6} Cell")
    for ev in events:
        w(f"{ev['game_day']:%m/%d} {ev['matchup'][:32]:32} {ev['truck'][:14]:14} {ev['epl']:5.0f} "
          f"{ev['hsip']:5.0f} {'%d/%d' % ev['n_up']:>7} {ev['up_assigned']:5.0f} "
          f"{'%d/%d' % ev['n_dn']:>7} {ev['dn_assigned']:5.0f} {ev['needed']:7.0f} {ev['full']:6.0f} "
          f"{ev['hsip_util']:6.0%} {ev['hsip_full_util']:6.0%} ↑{ev['n_cell_up']} ↓{ev['n_cell_dn']}")
    w("")
    w("TX windows (ET)")
    for ev in events:
        w(f"  {ev['matchup'][:32]:32} {ev['start']:%a %m/%d %H:%M} → {ev['end']:%a %m/%d %H:%M}")
    w(f"\nPeak concurrent demand into CT Prod Hub: {peak[1]:,.0f} Mbps needed "
      f"({peak[2]:,.0f} full build) at {peak[0]:%a %m/%d %H:%M} — {' + '.join(peak[3])}")
    w("\nWorkbook flags")
    for ev in events:
        for f in ev["flags"]:
            w(f"  {ev['matchup'][:32]}: {f}")
    w("\nLine visibility: " + ("all clear" if not vis else "; ".join(vis)))
    return "\n".join(p) + "\n"


def write_csv(events, path):
    cols = ["date", "event", "network", "truck", "carrier", "tx_start", "tx_end", "epl_mbps",
            "hsip_mbps", "tx_assigned", "tx_slots", "up_assigned_mbps", "up_spare_mbps",
            "rx_assigned", "rx_slots", "down_assigned_mbps", "needed_mbps", "full_build_mbps",
            "fiber_usable_mbps", "hsip_util", "hsip_full_util", "liveu_up", "liveu_down"]
    with open(path, "w", newline="") as f:
        c = csv.writer(f)
        c.writerow(cols)
        for ev in events:
            c.writerow([f"{ev['game_day']:%Y-%m-%d}", ev["matchup"], ev["network"], ev["truck"], ev["carrier"],
                        f"{ev['start']:%Y-%m-%d %H:%M}", f"{ev['end']:%Y-%m-%d %H:%M}", ev["epl"], ev["hsip"],
                        ev["n_up"][0], ev["n_up"][1], ev["up_assigned"], ev["up_spare"], ev["n_dn"][0],
                        ev["n_dn"][1], ev["dn_assigned"], ev["needed"], ev["full"], ev["fiber"],
                        round(ev["hsip_util"], 4), round(ev["hsip_full_util"], 4), ev["n_cell_up"],
                        ev["n_cell_dn"]])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", nargs="*")
    ap.add_argument("--out", default=os.path.join(HERE, "output"))
    a = ap.parse_args(argv)
    files = a.xlsx or sorted(glob.glob(os.path.join(HERE, "*.xlsx")))
    os.makedirs(a.out, exist_ok=True)
    events = sorted((load_event(f) for f in files), key=lambda e: e["game_day"])
    g = build_graph(events)
    vis = check_visibility(g, events)
    draw_bars(events, os.path.join(a.out, "bandwidth_per_event.png"))
    draw_paths(g, events, os.path.join(a.out, "event_paths.png"))
    peak = draw_timeline(events, os.path.join(a.out, "hub_timeline.png"))
    text = report(events, g, peak, vis)
    print(text, end="")
    open(os.path.join(a.out, "report.txt"), "w").write(text)
    write_csv(events, os.path.join(a.out, "bandwidth_per_event.csv"))
    with open(os.path.join(a.out, "workbook_flags.csv"), "w", newline="") as f:
        c = csv.writer(f)
        c.writerow(["date", "event", "flag"])
        for ev in events:
            for fl in ev["flags"]:
                c.writerow([f"{ev['game_day']:%Y-%m-%d}", ev["matchup"], fl])
    return events, peak


if __name__ == "__main__":
    main()
