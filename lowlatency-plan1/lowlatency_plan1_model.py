"""
Low Latency Prem-to-Cloud Plan1 — NetworkX model.

Based on the New Backbone1 model, with these Plan1 changes:
  * new backbone link NYC–CT (1 circuit)
  * dotted "London" region box around TEL, WOK and OST
  * dotted "NJ Metro" region box around SEC2 and HAL2
  * Azure connections removed (AWS and Internet only)

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
    "SEC2": ((760, 320), True),
    "HAL2": ((900, 520), False),
    "NYC":  ((1040, 120), False),
    "CT":   ((1280, 200), False),
    "WDC":  ((720, 900), False),
    "MIA":  ((900, 1330), True),
    "TEL":  ((1760, 330), True),
    "WOK":  ((1860, 640), True),
    "OST":  ((2130, 470), False),
}

BACKBONE = [
    ("SEC2", "NYC", 2),
    ("SEC2", "CT", 2),
    ("SEC2", "TEL", 1),
    ("SEC2", "WDC", 1),
    ("SEC2", "WOK", 1),
    ("SEC2", "HAL2", 2),
    ("SEC2", "LA", 2),
    ("SEC2", "MIA", 2),
    ("HAL2", "NYC", 1),
    ("NYC", "LA", 1),
    ("NYC", "CT", 1),     # Plan1: new link
    ("HAL2", "CT", 2),
    ("HAL2", "TEL", 1),
    ("HAL2", "WDC", 1),
    ("WDC", "MIA", 1),
    ("HAL2", "WOK", 1),
    ("HAL2", "LA", 2),
    ("HAL2", "MIA", 2),
    ("TEL", "OST", 1),
    ("TEL", "WOK", 2),
    ("WOK", "OST", 1),
    ("LA", "MIA", 4),
]

CLOUDS = [
    ("SEC2", "Internet",  (760, 60), 2),
    ("SEC2", "AWS West",  (500, 260), 2),
    ("HAL2", "AWS East",  (1110, 690), 2),
    ("CT",   "Internet",  (1480, 120), 2),
    ("LA",   "AWS West",  (90, 860), 2),
    ("LA",   "Internet",  (90, 1130), 2),
    ("MIA",  "AWS East",  (1160, 1420), 2),
    ("MIA",  "Internet",  (640, 1460), 2),
    ("WOK",  "Internet",  (1880, 870), 2),
]

# Dotted region boxes: name -> (member sites, padding, label x-fraction,
#                               label edge "top" or "bottom")
REGIONS = {
    "London": (["TEL", "WOK", "OST"], 70, 0.6, "top"),
    "NJ Metro": (["SEC2", "HAL2"], 60, 0.03, "top"),
}

# ---------------------------------------------------------------------------
# Drawing constants
# ---------------------------------------------------------------------------
CGX_BADGE = {"MIA": (0.35, 1.25), "LA": (0.0, 1.4)}
LABEL_T = {("NYC", "LA"): 0.75, ("SEC2", "WDC"): 0.7, ("SEC2", "CT"): 0.62,
           ("SEC2", "SEC2:Internet"): 0.72}
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

    for (a, b), d in links.items():
        n = d["of"]
        (x1, y1), (x2, y2) = pos[a], pos[b]
        L = math.hypot(x2 - x1, y2 - y1)
        nx_, ny_ = -(y2 - y1) / L, (x2 - x1) / L
        for off in offsets(n):
            ax.plot([x1 + nx_ * off, x2 + nx_ * off],
                    [y1 + ny_ * off, y2 + ny_ * off],
                    color=BLACK, lw=2.0, solid_capstyle="butt", zorder=1)
        t = LABEL_T.get((a, b), 0.5 if d["kind"] == "backbone" else 0.55)
        lx, ly = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        ax.text(lx, ly, str(n), ha="center", va="center", fontsize=14,
                fontweight="bold", color=BLACK, zorder=3,
                bbox=dict(boxstyle="round,pad=0.2", fc="white",
                          ec=BLACK, lw=1.2))

    for n, d in g.nodes(data=True):
        x, y = pos[n]
        if d["kind"] == "site":
            ax.add_patch(Circle((x, y), SITE_R, fc="white", ec=BLACK,
                                lw=3.5, zorder=4))
            ax.text(x, y, n, ha="center", va="center", fontsize=17,
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
