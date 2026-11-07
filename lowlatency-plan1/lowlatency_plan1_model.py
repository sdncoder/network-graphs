"""
Low Latency Prem-to-Cloud Plan1 — NetworkX model.

Plan1 features:
  * dotted "London" region box around LON-1, LON-2 and LON-3
  * dotted "NJ Metro" region box around NJ-1 and NJ-2
  * AWS and Internet on-ramps
  * estimated one-way latency per circuit, each circuit on its own diverse path

Latency estimate (per circuit):
    route_km   = length of that circuit's estimated diverse path x ROUTE_FACTOR
    latency_ms = route_km x FIBER_US_PER_KM / 1000
Circuit 1 on a link takes the direct (great-circle) route. Each further
circuit takes its own diverse route, bowed out progressively further
(1, 2, 3 x spacing). In North America the bow goes inland, toward the middle
of the continental US, so alternates stay over land; elsewhere it goes to the
right of A->Z. Circuits never share a route and the alternates are longer. Fiber propagation
only: equipment, queueing and serialization delay are excluded.

Every circuit is its own edge in a MultiGraph and is drawn as a separate
straight line, offset in parallel so circuit diversity is visible.

Run (from the repo root):
    python lowlatency-plan1/lowlatency_plan1_model.py [output.png]

Writes lowlatency_plan1_model.png and report.txt next to this script by default.
"""
import sys
import math
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle

TITLE = "Low Latency Prem-to-Cloud Plan1"

# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------
SITES = {
    # compressed geography: LA west, NJ Metro / NYC / CT northeast,
    # WDC and MIA down the east coast, London across the Atlantic
    "LA":   ((250, 1000), True),
    "NJ-1": ((760, 320), True),
    "NJ-2": ((900, 520), False),
    "NYC":  ((1040, 120), False),
    "CT":   ((1280, 200), False),
    "WDC":  ((720, 900), False),
    "MIA":  ((900, 1330), True),
    "LON-1":  ((1760, 330), True),
    "LON-2":  ((1860, 640), True),
    "LON-3":  ((2130, 470), False),
}

BACKBONE = [
    ("NJ-1", "NYC", 2),
    ("NJ-1", "CT", 2),
    ("NJ-1", "LON-1", 1),
    ("NJ-1", "WDC", 1),
    ("NJ-1", "LON-2", 1),
    ("NJ-1", "NJ-2", 2),
    ("NJ-1", "LA", 2),
    ("NJ-1", "MIA", 2),
    ("NJ-2", "NYC", 1),
    ("NYC", "LA", 1),
    ("NYC", "CT", 1),     # Plan1: new link
    ("NJ-2", "CT", 2),
    ("NJ-2", "LON-1", 1),
    ("NJ-2", "WDC", 1),
    ("WDC", "MIA", 1),
    ("NJ-2", "LON-2", 1),
    ("NJ-2", "LA", 2),
    ("NJ-2", "MIA", 2),
    ("LON-1", "LON-3", 1),
    ("LON-1", "LON-2", 2),
    ("LON-2", "LON-3", 1),
    ("LA", "MIA", 4),
]

CLOUDS = [
    ("NJ-1", "Internet",  (760, 60), 2),
    ("NJ-1", "AWS West",  (330, 250), 2),
    ("NJ-2", "AWS East",  (1110, 690), 2),
    ("CT",   "Internet",  (1480, 120), 2),
    ("LA",   "AWS West",  (90, 860), 2),
    ("LA",   "Internet",  (90, 1130), 2),
    ("MIA",  "AWS East",  (1160, 1420), 2),
    ("MIA",  "Internet",  (640, 1460), 2),
    ("LON-2",  "Internet",  (1880, 870), 2),
]

# Dotted region boxes: name -> (member sites, padding, label x-fraction,
#                               label edge "top" or "bottom")
REGIONS = {
    "London": (["LON-1", "LON-2", "LON-3"], 70, 0.6, "top"),
    "NJ Metro": (["NJ-1", "NJ-2"], 60, 0.03, "top"),
}

# ---------------------------------------------------------------------------
# Geography and latency
# ---------------------------------------------------------------------------
# site -> (lat, lon, area). Coordinates are rounded to ~10 km (0.1 deg).
LOCATIONS = {
    "LA":   (34.1, -118.4, "Los Angeles area"),
    "NJ-1": (40.8, -74.1, "New Jersey, NYC metro"),
    "NJ-2": (40.7, -74.2, "New Jersey, NYC metro"),
    "NYC":  (40.8, -74.0, "New York City"),
    "CT":   (41.1, -73.5, "Connecticut"),
    "WDC":  (38.9, -77.0, "Washington, DC"),
    "MIA":  (25.8, -80.4, "Miami area"),
    "LON-1": (51.5, 0.0, "London area"),
    "LON-2": (51.3, -0.6, "London area"),
    "LON-3": (51.5, -0.3, "London area"),
}
# cloud on-ramp -> (lat, lon, assumed AWS region). Internet has no latency.
CLOUD_LOCATIONS = {
    "AWS East": (39.040, -77.490, "AWS us-east-1, Ashburn, VA"),
    "AWS West": (45.840, -119.700, "AWS us-west-2, Oregon"),
}
ROUTE_FACTOR = 1.3        # fiber route vs. geometric path (slack, rights-of-way)
FIBER_US_PER_KM = 4.9     # light in single-mode fiber (n ~ 1.468)
DIVERSITY = 0.12          # lateral spacing between diverse routes, x link distance
MIN_SPACING_KM, MAX_SPACING_KM = 3.0, 600.0
INLAND = (38.5, -97.0)    # continental-US centre: North American bows head here
EARTH_KM = 6371.0088


def _ll(p):
    return math.radians(p[0]), math.radians(p[1])


def gc_km(p, q):
    (la1, lo1), (la2, lo2) = _ll(p), _ll(q)
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * EARTH_KM * math.asin(math.sqrt(h))


def _interp(p, q, f):
    (la1, lo1), (la2, lo2) = _ll(p), _ll(q)
    d = gc_km(p, q) / EARTH_KM
    if d == 0:
        return p
    a, b = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
    x = a * math.cos(la1) * math.cos(lo1) + b * math.cos(la2) * math.cos(lo2)
    y = a * math.cos(la1) * math.sin(lo1) + b * math.cos(la2) * math.sin(lo2)
    z = a * math.sin(la1) + b * math.sin(la2)
    return (math.degrees(math.atan2(z, math.hypot(x, y))),
            math.degrees(math.atan2(y, x)))


def _bearing(p, q):
    (la1, lo1), (la2, lo2) = _ll(p), _ll(q)
    return math.atan2(math.sin(lo2 - lo1) * math.cos(la2),
                      math.cos(la1) * math.sin(la2)
                      - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1))


def _dest(p, brg, km):
    la, lo = _ll(p)
    d = km / EARTH_KM
    la2 = math.asin(math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(brg))
    lo2 = lo + math.atan2(math.sin(brg) * math.sin(d) * math.cos(la),
                          math.cos(d) - math.sin(la) * math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2) + 540) % 360 - 180


def diverse_path(p, q, offset_km, steps=64):
    """Great circle p->q bowed sideways by offset_km at the midpoint."""
    pts = []
    for i in range(steps + 1):
        f = i / steps
        c = _interp(p, q, f)
        if offset_km and 0 < i < steps:
            c = _dest(c, _bearing(c, q) + math.pi / 2,
                      offset_km * math.sin(math.pi * f))
        pts.append(c)
    return pts


def path_km(pts):
    return sum(gc_km(a, b) for a, b in zip(pts, pts[1:]))


def _loc(node):
    if node in LOCATIONS:
        return LOCATIONS[node][:2]
    cloud = node.split(":", 1)[1]
    return CLOUD_LOCATIONS[cloud][:2] if cloud in CLOUD_LOCATIONS else None


def circuit_paths():
    """One record per circuit (backbone + AWS), each on its own diverse path."""
    links = [(a, b, n, "backbone") for a, b, n in BACKBONE]
    links += [(s, f"{s}:{c}", n, "cloud") for s, c, _, n in CLOUDS if c in CLOUD_LOCATIONS]
    rows = []
    for a, b, n, kind in links:
        p, q = _loc(a), _loc(b)
        d = gc_km(p, q)
        spacing = min(max(DIVERSITY * d, MIN_SPACING_KM), MAX_SPACING_KM)
        side = 1
        if p[1] < -50 and q[1] < -50:      # both ends in North America: bow inland
            mid = _interp(p, q, 0.5)
            right = _dest(mid, _bearing(mid, q) + math.pi / 2, spacing)
            side = 1 if gc_km(right, INLAND) < gc_km(mid, INLAND) else -1
        for k in range(n):
            off = side * k * spacing       # circuit 1 direct, then 1, 2, 3 x spacing
            pts = diverse_path(p, q, off)
            route = path_km(pts) * ROUTE_FACTOR
            rows.append(dict(a=a, b=b, z=b.split(":", 1)[-1], kind=kind,
                             circuit=k + 1, of=n, gc_km=d, offset_km=off,
                             route_km=route,
                             ms=route * FIBER_US_PER_KM / 1000, path=pts))
    return rows


def link_latency():
    """(a, b) -> (min_ms, max_ms) across that link's circuits."""
    out = {}
    for r in circuit_paths():
        lo, hi = out.get((r["a"], r["b"]), (1e9, 0))
        out[(r["a"], r["b"])] = (min(lo, r["ms"]), max(hi, r["ms"]))
    return out


def fmt_ms(x):
    return f"{x:.2f}" if x < 1 else f"{x:.1f}"


def link_label(a, b, n, lat=None):
    lat = link_latency() if lat is None else lat
    key = (a, b) if (a, b) in lat else (b, a)
    if key not in lat:
        return str(n)
    lo, hi = lat[key]
    span = fmt_ms(lo) if fmt_ms(lo) == fmt_ms(hi) else f"{fmt_ms(lo)}–{fmt_ms(hi)}"
    return f"{n} | {span} ms"


# ---------------------------------------------------------------------------
# Drawing constants
# ---------------------------------------------------------------------------
CGX_BADGE = {"MIA": (0.35, 1.25), "LA": (0.0, 1.4)}
LABEL_T = {("NYC", "LA"): 0.75, ("NJ-1", "WDC"): 0.7, ("NJ-1", "CT"): 0.62,
           ("NJ-1", "NJ-1:Internet"): 0.72}
SITE_R = 52
CIRCUIT_GAP = 11
CLOUD_W, CLOUD_H = 128, 70
BLACK = "#1a1a1a"


def build_graph():
    g = nx.MultiGraph()
    for name, (pos, cgx) in SITES.items():
        g.add_node(name, kind="site", pos=pos, cgx=cgx)
    for a, b, n in BACKBONE:
        for i in range(n):
            g.add_edge(a, b, kind="backbone", circuit=i + 1, of=n)
    for site, cloud, pos, n in CLOUDS:
        cid = f"{site}:{cloud.replace(chr(10), ' ')}"
        g.add_node(cid, kind="cloud", pos=pos, label=cloud,
                   internet=cloud == "Internet")
        for i in range(n):
            g.add_edge(site, cid, kind="external", circuit=i + 1, of=n)
    return g


def region_box(members, pad):
    """(x0, y0, x1, y1) enclosing the member sites and their CGX badges."""
    xs, ys = [], []
    for s in members:
        (x, y), cgx = SITES[s]
        xs += [x - SITE_R, x + SITE_R]
        ys += [y - SITE_R, y + SITE_R]
        if cgx:
            bx, by = CGX_BADGE.get(s, (0.9, -0.95))
            cx, cy = x + SITE_R * bx, y + SITE_R * by
            xs += [cx - 30, cx + 30]
            ys += [cy - 18, cy + 18]
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def offsets(n):
    return [(i - (n - 1) / 2) * CIRCUIT_GAP for i in range(n)]


def seg_point_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def check_visibility(g):
    """Every line must clear every node it doesn't terminate on, and no
    node outside a region may sit inside its box."""
    pos = nx.get_node_attributes(g, "pos")
    problems = []
    for a, b in {tuple(sorted(e)) for e in g.edges()}:
        for n, p in pos.items():
            if n in (a, b):
                continue
            clear = SITE_R if g.nodes[n]["kind"] == "site" else CLOUD_H / 2
            d = seg_point_dist(p, pos[a], pos[b])
            if d < clear + 2 * CIRCUIT_GAP:
                problems.append((a, b, n, round(d)))
    for name, (members, pad, *_) in REGIONS.items():
        x0, y0, x1, y1 = region_box(members, pad)
        for n, (x, y) in pos.items():
            if n not in members and x0 - 60 < x < x1 + 60 and y0 - 40 < y < y1 + 40:
                problems.append((name, "contains", n))
    return problems


def _seg_rect(p, q, r):
    """Does segment p-q cross rectangle r = (x0, y0, x1, y1)? (Liang-Barsky)"""
    (x1, y1), (x2, y2) = p, q
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for pv, qv in ((-dx, x1 - r[0]), (dx, r[2] - x1), (-dy, y1 - r[1]), (dy, r[3] - y1)):
        if pv == 0:
            if qv < 0:
                return False
            continue
        t = qv / pv
        if pv < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def label_size(txt):
    if txt.isdigit():
        return 26, 30
    return 7.6 * len(txt) + 14, 26


def place_labels(g):
    """(a, b) -> (x, y, text): put each count/latency label where it crosses
    the fewest other lines, nodes, badges and already-placed labels."""
    pos = nx.get_node_attributes(g, "pos")
    lat = link_latency()
    links = {}
    for a, b, d in g.edges(data=True):
        links.setdefault((a, b), d)
    segs = [((a, b), pos[a], pos[b]) for a, b in links]
    for members, pad, *_ in REGIONS.values():
        x0, y0, x1, y1 = region_box(members, pad)
        for p, q in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                     ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            segs.append((None, p, q))
    blocks = []
    for n, d in g.nodes(data=True):
        x, y = pos[n]
        if d["kind"] == "site":
            blocks.append((x - SITE_R, y - SITE_R, x + SITE_R, y + SITE_R))
            if d["cgx"]:
                bx, by = CGX_BADGE.get(n, (0.9, -0.95))
                cx, cy = x + SITE_R * bx, y + SITE_R * by
                blocks.append((cx - 30, cy - 18, cx + 30, cy + 18))
        else:
            blocks.append((x - CLOUD_W / 2, y - CLOUD_H / 2, x + CLOUD_W / 2, y + CLOUD_H / 2))
    for name, (members, pad, lt, edge) in REGIONS.items():
        x0, y0, x1, y1 = region_box(members, pad)
        lx, ly = x0 + (x1 - x0) * lt, (y0 if edge == "top" else y1)
        blocks.append((lx - 70, ly - 18, lx + 70, ly + 18))

    def overlap(r, o):
        return r[0] < o[2] and o[0] < r[2] and r[1] < o[3] and o[1] < r[3]

    order = sorted(links, key=lambda k: -len(link_label(*k, links[k]["of"], lat)))
    placed = {}
    for a, b in order:
        n = links[(a, b)]["of"]
        txt = link_label(a, b, n, lat)
        w, h = label_size(txt)
        (x1, y1), (x2, y2) = pos[a], pos[b]
        best = None
        pref = LABEL_T.get((a, b), 0.5 if links[(a, b)]["kind"] == "backbone" else 0.55)
        for i in range(0, 61):
            t = 0.2 + i * 0.01
            lx, ly = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
            r = (lx - w / 2 - 4, ly - h / 2 - 4, lx + w / 2 + 4, ly + h / 2 + 4)
            cost = abs(t - pref) * 2
            cost += sum(100 for o in blocks if overlap(r, o))
            cost += sum(10 for k, p, q in segs if k != (a, b) and _seg_rect(p, q, r))
            if cost < (best[0] if best else 1e9):
                best = (cost, lx, ly, r)
        _, lx, ly, r = best
        blocks.append(r)
        placed[(a, b)] = (lx, ly, txt)
    return placed


def draw(g, out):
    pos = nx.get_node_attributes(g, "pos")
    fig, ax = plt.subplots(figsize=(25, 18.75))
    ax.set_aspect("equal")
    ax.axis("off")

    # region boxes (behind everything)
    for name, (members, pad, lt, edge) in REGIONS.items():
        x0, y0, x1, y1 = region_box(members, pad)
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False,
                               ec=BLACK, lw=2.5, ls=(0, (2, 3)), zorder=0))
        ax.text(x0 + (x1 - x0) * lt, y0 if edge == "top" else y1, name, ha="center", va="center",
                fontsize=18, fontweight="bold", zorder=6,
                bbox=dict(boxstyle="square,pad=0.25", fc="white", ec="none"))

    links = {}
    for a, b, d in g.edges(data=True):
        links.setdefault((a, b), d)
    labels = place_labels(g)

    for (a, b), d in links.items():
        n = d["of"]
        (x1, y1), (x2, y2) = pos[a], pos[b]
        L = math.hypot(x2 - x1, y2 - y1)
        nx_, ny_ = -(y2 - y1) / L, (x2 - x1) / L
        for off in offsets(n):
            ax.plot([x1 + nx_ * off, x2 + nx_ * off],
                    [y1 + ny_ * off, y2 + ny_ * off],
                    color=BLACK, lw=2.0, solid_capstyle="butt", zorder=1)
        lx, ly, txt = labels[(a, b)]
        ax.text(lx, ly, txt, ha="center", va="center",
                fontsize=14 if txt.isdigit() else 11,
                fontweight="bold", color=BLACK, zorder=3,
                bbox=dict(boxstyle="round,pad=0.2", fc="white",
                          ec=BLACK, lw=1.2))

    for n, d in g.nodes(data=True):
        x, y = pos[n]
        if d["kind"] == "site":
            ax.add_patch(Circle((x, y), SITE_R, fc="white", ec=BLACK,
                                lw=3.5, zorder=4))
            ax.text(x, y, n, ha="center", va="center",
                    fontsize=17 if len(n) <= 4 else 14,
                    fontweight="bold", zorder=5)
            if d["cgx"]:
                bx, by = CGX_BADGE.get(n, (0.9, -0.95))
                ax.text(x + SITE_R * bx, y + SITE_R * by, "CGX",
                        ha="center", va="center", fontsize=13, zorder=6,
                        bbox=dict(boxstyle="round,pad=0.3", fc="white",
                                  ec=BLACK, lw=2))
        else:
            ax.add_patch(FancyBboxPatch(
                (x - CLOUD_W / 2, y - CLOUD_H / 2), CLOUD_W, CLOUD_H,
                boxstyle="round,pad=0,rounding_size=30",
                fc="white", ec=BLACK, lw=2.2, zorder=4))
            ax.text(x, y, d["label"], ha="center", va="center",
                    fontsize=12.5, zorder=5)

    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    for members, pad, *_ in REGIONS.values():
        x0, y0, x1, y1 = region_box(members, pad)
        xs += [x0, x1]; ys += [y0, y1]
    ax.set_xlim(min(xs) - 110, max(xs) + 110)
    ax.set_ylim(max(ys) + 110, min(ys) - 110)
    ax.set_title(TITLE, fontsize=20, pad=12)
    fig.savefig(out, dpi=110, bbox_inches="tight", facecolor="white")


def report(g):
    sites = [n for n, d in g.nodes(data=True) if d["kind"] == "site"]
    bb = g.subgraph(sites)
    print(TITLE)
    print(f"Sites: {len(sites)}   Clouds: {g.number_of_nodes() - len(sites)}")
    print(f"Backbone links: {len(BACKBONE)}   circuits: {bb.number_of_edges()}")
    ext = sum(n for *_, n in CLOUDS)
    print(f"Cloud/Internet links: {len(CLOUDS)}   circuits: {ext}")
    print(f"Total circuits: {g.number_of_edges()}")
    for name, (members, *_ ) in REGIONS.items():
        print(f"Region {name}: {', '.join(members)}")

    simple = nx.Graph(bb)
    print("\nBackbone circuits per site:")
    for s in sorted(sites, key=lambda s: -bb.degree(s)):
        print(f"  {s:5} {bb.degree(s):2} circuits to {simple.degree(s)} sites")
    aps = list(nx.articulation_points(simple))
    print(f"\nBackbone articulation points: {aps or 'none'}")
    print(f"Min site cut (node connectivity): {nx.node_connectivity(simple)}")
    print(f"Min link cut (edge connectivity): {nx.edge_connectivity(simple)}")
    single = [f"{a}-{b}" for a, b, n in BACKBONE if n == 1]
    print(f"Single-circuit links: {', '.join(single)}")

    print("\nEstimated one-way latency (each circuit on its own diverse path)")
    print(f"  route = diverse path x {ROUTE_FACTOR}, {FIBER_US_PER_KM} us/km fiber")
    print(f"  {'Link':16} {'Ckts':>4} {'GC km':>7} {'Route km':>17} {'One-way ms':>14}")
    by_link = {}
    for r in circuit_paths():
        by_link.setdefault((r["a"], r["z"]), []).append(r)
    for (a, z), rs in sorted(by_link.items(), key=lambda kv: kv[1][0]["ms"]):
        km = [r["route_km"] for r in rs]
        ms = [r["ms"] for r in rs]
        kmr = f"{min(km):,.0f}" if len(rs) == 1 else f"{min(km):,.0f}-{max(km):,.0f}"
        msr = fmt_ms(min(ms)) if len(rs) == 1 else f"{fmt_ms(min(ms))}-{fmt_ms(max(ms))}"
        print(f"  {a + '-' + z:16} {len(rs):>4} {rs[0]['gc_km']:>7,.0f} {kmr:>17} {msr:>14}")


if __name__ == "__main__":
    import io
    import os
    from contextlib import redirect_stdout
    out_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(out_dir, "lowlatency_plan1_model.png")
    G = build_graph()
    buf = io.StringIO()
    with redirect_stdout(buf):
        report(G)
        bad = check_visibility(G)
        print("\nLine visibility:", "all clear" if not bad else bad)
    print(buf.getvalue(), end="")
    with open(os.path.join(out_dir, "report.txt"), "w") as f:
        f.write(buf.getvalue())
    draw(G, out)
    print(f"\nWrote {out}")
