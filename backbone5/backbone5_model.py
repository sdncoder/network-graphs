"""
Backbone5 network model (NetworkX)

Builds the Backbone1 core plus the Edges from the "BackboneSplit"
sheet of Backbone-Split5.numbers. Backbone2 columns are ignored.

Each Backbone1 link carries an estimated one-way latency, derived from the
site locations listed on the "Backbone1" sheet:

    latency_ms = great_circle_km * ROUTE_FACTOR * FIBER_US_PER_KM / 1000

  - great-circle distance between the two sites (haversine)
  - ROUTE_FACTOR  : fiber path is longer than the straight line (1.3 typical)
  - FIBER_US_PER_KM: light in single-mode fiber, ~4.9 us/km (n ~= 1.468)
  - Propagation only: excludes equipment, queueing and serialization delay

Styling
  - Backbone1 nodes : white, dark outline, no labels
  - Edge nodes      : light grey, small, no labels
  - All links       : straight lines, drawn beneath the nodes
  - Backbone1 links : labelled with estimated latency (ms)

Usage
  pip install networkx matplotlib numbers-parser
  python backbone5_model.py Backbone-Split5.numbers [output.png]
"""

import math
import sys

import matplotlib.pyplot as plt
import networkx as nx
from numbers_parser import Document

SPLIT_SHEET = "BackboneSplit"
SITE_SHEET = "Backbone1"

# Column positions on the BackboneSplit sheet (0-based)
BB1_A, BB1_Z, BB1_LINKS, BB1_BW = 0, 1, 2, 3          # Backbone1 block
ST_A, ST_Z, ST_LINKS, ST_BW = 13, 14, 15, 16          # Edges block
DATA_START_ROW = 2                                    # rows 0-1 are headers

# Site / Location columns on the Backbone1 sheet
SITE_COL, LOC_COL = 5, 6

# Hub names on the sheet that are typos for a Backbone1 site
HUB_ALIASES = {"ASH1": "ASH"}

# Latency model
ROUTE_FACTOR = 1.3
FIBER_US_PER_KM = 4.9

# Approximate coordinates for each Location listed on the Backbone1 sheet
LOCATION_COORDS = {
    "Universal City":          (34.1381, -118.3534),
    "Los Angeles":             (34.0522, -118.2437),
    "San Jose":                (37.3382, -121.8863),
    "Denver":                  (39.7392, -104.9903),
    "Dry Creek, South Denver": (39.5800, -104.8700),
    "Chicago":                 (41.8781, -87.6298),
    "Dallas":                  (32.7767, -96.7970),
    "Houston":                 (29.7604, -95.3698),
    "Secaucus NJ":             (40.7895, -74.0565),
    "Stamford":                (41.0534, -73.5387),
    "Halsey NJ":               (40.7357, -74.1724),   # Halsey St, Newark
    "Atlanta":                 (33.7490, -84.3880),
    "Digital Realty, VA":      (39.0300, -77.4700),   # Ashburn campus
    "Ashburn, VA":             (39.0438, -77.4874),
    "Telemundo Center":        (25.8200, -80.3400),   # Miami area
    "North Capital W.D.C.":    (38.9000, -77.0090),
    "30 Rockefeller, NYC":     (40.7587, -73.9787),
    "Woking, London":          (51.3190, -0.5580),
    "Telehouse, London":       (51.5110, -0.0010),
    "Miami":                   (25.7617, -80.1918),
    "Osterley, London":        (51.4880, -0.3510),
}

# The sheet's Location cells have a find/replace artefact ("SEC1aucus",
# "HAL1sey"); map them back to the real place names.
LOCATION_FIXES = {"SEC1aucus NJ": "Secaucus NJ", "HAL1sey NJ": "Halsey NJ"}

# Schematic positions for Backbone1 sites (west -> east), fixed so the
# core reads like a map and no link passes through another node.
BACKBONE_POS = {
    "SNJ": (0.0, 6.0),  "LA": (0.0, 2.0),
    "DEN": (4.0, 7.0),  "DRY": (4.0, 4.0),
    "CHI": (8.0, 8.0),  "DAL": (7.0, 2.0),  "HOU": (8.0, 0.0),
    "HAL1": (12.0, 9.5), "SEC1": (15.0, 8.5),
    "DRT": (11.0, 5.5), "ASH": (14.0, 4.5),
    "ATL": (11.0, 1.5), "MIA": (14.0, -0.5),
}

# Slots for edge nodes, keyed by the (sorted) Backbone1 hubs they home to.
# Each group sits in open space beside its hubs so no edge line lies on
# top of a backbone link and no two edge nodes share a position.
EDGE_SLOTS = {
    ("HAL1", "SEC1"): [(12.0, 11.0), (12.9, 11.2), (13.8, 11.2), (14.7, 11.0)],
    ("LA", "SNJ"):    [(-1.4, 2.6), (-1.4, 3.4), (-1.4, 4.2), (-1.4, 5.0)],
    ("DEN", "DRY"):   [(5.1, 5.3), (5.1, 6.0)],
    ("DEN", "LA"):    [(1.9, 3.1), (2.5, 2.75), (3.1, 2.4)],
    ("DAL", "DRY"):   [(5.0, 2.2)],
    ("DAL", "HOU"):   [(8.7, 0.5), (8.9, 1.0), (9.1, 1.5), (9.3, 2.0)],
    ("ATL", "MIA"):   [(11.7, -1.0), (12.5, -1.4)],
    ("ASH", "ATL"):   [(12.2, 3.5)],
    ("ASH", "MIA"):   [(15.4, 1.8)],
    ("ASH", "HAL1"):  [(13.0, 6.5)],
    ("ASH", "SEC1"):  [(16.4, 6.3)],
}


def clean(v):
    return str(v).strip() if v not in (None, "") else None


# ---------------------------------------------------------------- load

def load(path):
    doc = Document(path)
    sheets = {s.name: s for s in doc.sheets}

    rows = list(sheets[SPLIT_SHEET].tables[0].rows(values_only=True))
    backbone, edge_rows = [], []
    for r in rows[DATA_START_ROW:]:
        a, z = clean(r[BB1_A]), clean(r[BB1_Z])
        if a and z:
            backbone.append((a, z, int(r[BB1_LINKS] or 1), clean(r[BB1_BW])))
        a, z = clean(r[ST_A]), clean(r[ST_Z])
        if a and z:
            edge_rows.append((a, z, int(r[ST_LINKS] or 1), clean(r[ST_BW])))

    sites = {}
    for r in list(sheets[SITE_SHEET].tables[0].rows(values_only=True))[1:]:
        site, loc = clean(r[SITE_COL]), clean(r[LOC_COL])
        if site and loc:
            sites[site] = LOCATION_FIXES.get(loc, loc)

    return backbone, edge_rows, sites


# ---------------------------------------------------------------- latency

def great_circle_km(p1, p2):
    lat1, lon1 = map(math.radians, p1)
    lat2, lon2 = map(math.radians, p2)
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def latency_ms(km):
    return km * ROUTE_FACTOR * FIBER_US_PER_KM / 1000.0


# ---------------------------------------------------------------- graph

def build_graph(backbone, edge_rows, sites):
    G = nx.Graph()
    dupes, offnet, aliased = [], [], []

    for a, z, links, bw in backbone:
        for n in (a, z):
            loc = sites.get(n)
            G.add_node(n, role="backbone1", location=loc,
                       coords=LOCATION_COORDS.get(loc))
        if G.has_edge(a, z):
            dupes.append((a, z))
            continue
        G.add_edge(a, z, role="backbone1", links=links, bw=bw)

    # Estimated latency on each Backbone1 link
    for a, z, d in G.edges(data=True):
        ca, cz = G.nodes[a]["coords"], G.nodes[z]["coords"]
        if ca and cz:
            d["km"] = great_circle_km(ca, cz)
            d["latency_ms"] = latency_ms(d["km"])

    bb_nodes = set(G.nodes)
    for st, hub, links, bw in edge_rows:
        if hub in HUB_ALIASES:
            aliased.append((st, hub, HUB_ALIASES[hub]))
            hub = HUB_ALIASES[hub]
        if hub not in bb_nodes:              # hub is on Backbone2 only
            offnet.append((st, hub))
            continue
        G.add_node(st, role="edge")
        if G.has_edge(st, hub):
            dupes.append((st, hub))
            continue
        G.add_edge(st, hub, role="edge", links=links, bw=bw)

    # An edge node whose every hub is off Backbone1 never got a node; any
    # partially-homed edge node keeps its Backbone1 links.
    return G, dupes, offnet, aliased


# ---------------------------------------------------------------- layout

def layout(G):
    bb = [n for n, d in G.nodes(data=True) if d["role"] == "backbone1"]
    pos = {n: BACKBONE_POS.get(n, (7.0, 4.0)) for n in bb}

    used, unplaced = {}, []
    for n, d in G.nodes(data=True):
        if d["role"] != "edge":
            continue
        key = tuple(sorted(G.neighbors(n)))
        slots = EDGE_SLOTS.get(key, [])
        i = used.get(key, 0)
        if i < len(slots):
            pos[n] = slots[i]
            used[key] = i + 1
        else:
            unplaced.append(n)

    # Edge nodes not covered by a slot (new rows on the sheet) are placed by a
    # spring layout with everything else held fixed.
    if unplaced:
        for n in unplaced:
            hubs = list(G.neighbors(n))
            pos[n] = (sum(pos[h][0] for h in hubs) / len(hubs) + 0.5,
                      sum(pos[h][1] for h in hubs) / len(hubs) - 0.5)
        fixed = [n for n in pos if n not in unplaced]
        pos = nx.spring_layout(G, pos=pos, fixed=fixed, k=0.8,
                               iterations=200, seed=7)
    return pos


# Where along each backbone link to place its latency label (0.5 = middle).
# Shifted off the midpoint where two links cross.
LABEL_POS = {
    ("SNJ", "DRY"): 0.30, ("DEN", "LA"): 0.30,
    ("DRY", "HAL1"): 0.35, ("SEC1", "CHI"): 0.62,
    ("ASH", "CHI"): 0.30, ("CHI", "ATL"): 0.40,
    ("CHI", "DAL"): 0.55, ("DRT", "SEC1"): 0.30,
    ("ATL", "DRT"): 0.40, ("HAL1", "SEC1"): 0.5,
}


def fmt_ms(ms):
    return f"{ms:.2f} ms" if ms < 1 else f"{ms:.1f} ms"


# ---------------------------------------------------------------- draw

def draw(G, pos, out):
    bb = [n for n, d in G.nodes(data=True) if d["role"] == "backbone1"]
    st = [n for n, d in G.nodes(data=True) if d["role"] == "edge"]
    bb_edges = [(u, v) for u, v, d in G.edges(data=True) if d["role"] == "backbone1"]
    st_edges = [(u, v) for u, v, d in G.edges(data=True) if d["role"] == "edge"]

    fig, ax = plt.subplots(figsize=(18, 11))
    fig.patch.set_facecolor("white")

    # Straight lines, beneath the nodes
    nx.draw_networkx_edges(G, pos, edgelist=st_edges, ax=ax,
                           edge_color="#a0a0a0", width=1.0, arrows=False)
    nx.draw_networkx_edges(G, pos, edgelist=bb_edges, ax=ax,
                           edge_color="#1f1f1f", width=2.2, arrows=False)

    nx.draw_networkx_nodes(G, pos, nodelist=st, ax=ax, node_size=140,
                           node_color="#d3d3d3", edgecolors="#8a8a8a",
                           linewidths=0.9)
    nx.draw_networkx_nodes(G, pos, nodelist=bb, ax=ax, node_size=520,
                           node_color="white", edgecolors="#1f1f1f",
                           linewidths=2.0)

    # Latency labels on Backbone1 links (no node labels)
    for u, v in bb_edges:
        ms = G.edges[u, v].get("latency_ms")
        if ms is None:
            continue
        t = LABEL_POS.get((u, v), LABEL_POS.get((v, u), 0.5))
        if (v, u) in LABEL_POS:
            t = 1 - t
        x = pos[u][0] + (pos[v][0] - pos[u][0]) * t
        y = pos[u][1] + (pos[v][1] - pos[u][1]) * t
        ax.text(x, y, fmt_ms(ms), fontsize=8.5, color="#1f1f1f",
                ha="center", va="center", zorder=5,
                bbox=dict(boxstyle="round,pad=0.22", fc="white",
                          ec="#1f1f1f", lw=0.6))

    ax.set_title("Backbone5 — Backbone1 + Edges "
                 "(estimated one-way latency)", fontsize=15, pad=14)
    fig.text(0.5, 0.02,
             f"Latency = great-circle distance × {ROUTE_FACTOR} route factor × "
             f"{FIBER_US_PER_KM} µs/km fiber propagation. "
             "Excludes equipment and queueing delay.",
             ha="center", fontsize=9.5, color="#555555")
    ax.axis("off")
    ax.margins(0.05)
    plt.tight_layout(rect=(0, 0.04, 1, 1))
    plt.savefig(out, dpi=200, facecolor="white")
    print(f"Saved {out}")


# ---------------------------------------------------------------- main

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "Backbone-Split5.numbers"
    out = sys.argv[2] if len(sys.argv) > 2 else "backbone5_model.png"

    backbone, edge_rows, sites = load(src)
    G, dupes, offnet, aliased = build_graph(backbone, edge_rows, sites)

    bb = [n for n, d in G.nodes(data=True) if d["role"] == "backbone1"]
    st = [n for n, d in G.nodes(data=True) if d["role"] == "edge"]
    n_bb = sum(1 for *_, d in G.edges(data=True) if d["role"] == "backbone1")
    print(f"Backbone1 nodes: {len(bb)}   Edge nodes: {len(st)}")
    print(f"Backbone1 links: {n_bb}   Edge links: {G.number_of_edges() - n_bb}")
    print(f"Connected: {nx.is_connected(G)}")
    if dupes:
        print("Duplicate rows skipped:", ", ".join(f"{a}-{z}" for a, z in dupes))
    if offnet:
        print("Edges skipped (hub not on Backbone1):",
              ", ".join(f"{a}-{z}" for a, z in offnet))
    for s, old, new in aliased:
        print(f"Hub renamed: {s}-{old} treated as {s}-{new}")

    print("\nBackbone1 link latency (one-way, estimated)")
    rows = sorted(((u, v, d) for u, v, d in G.edges(data=True)
                   if d["role"] == "backbone1"),
                  key=lambda e: -e[2].get("latency_ms", 0))
    for u, v, d in rows:
        print(f"  {u:>4} - {v:<4} {d['km']:7.0f} km  {d['latency_ms']:6.2f} ms")

    draw(G, layout(G), out)


if __name__ == "__main__":
    main()
