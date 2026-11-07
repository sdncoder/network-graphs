"""
Render the estimated circuit paths (the same paths as the KMZ) as map images.

Four maps: an overview (US + London), the continental US, the NJ/NYC metro
and London. Each draws every circuit path colour-coded by circuit (1 blue,
2 red, 3 green, 4 orange, matching the KMZ), with a side panel listing the
links on that map and their one-way latency.

Basemap: public-domain Natural Earth data, downloaded on first run into a
.basemap/ folder next to this script (git-ignored).

Run (from the repo root):  python lowlatency-plan1/render_paths.py [model.py] [output_dir]
"""
import os
import sys
import json
import math
import urllib.request
import importlib.util
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))
model_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "lowlatency_plan1_model.py")
out_dir = sys.argv[2] if len(sys.argv) > 2 else HERE
os.makedirs(out_dir, exist_ok=True)

spec = importlib.util.spec_from_file_location("model", model_path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
CACHE = os.path.join(HERE, ".basemap")
COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd"]
EN = "–"

# name, title, (lon0, lon1, lat0, lat1), land layer, draw states
MAPS = [
    ("paths_overview", "All circuit paths", (-126, 6, 21, 59), "ne_50m_admin_0_countries", False),
    ("paths_us", "Continental US circuit paths", (-125, -66, 23, 50), "ne_50m_admin_0_countries", True),
    ("paths_nj_metro", "NJ Metro, NYC and CT circuit paths", (-74.32, -73.42, 40.62, 41.13), "ne_10m_land", False),
    ("paths_london", "London circuit paths", (-0.72, 0.16, 51.24, 51.60), "ne_10m_land", False),
]


def layer(name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name + ".geojson")
    if not os.path.exists(path):
        print(f"Downloading {name} ...")
        urllib.request.urlretrieve(NE + name + ".geojson", path)
    with open(path) as f:
        return json.load(f)["features"]


def rings(geom):
    if geom is None:
        return []
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


def in_box(p, box, pad=0.0):
    lon0, lon1, lat0, lat1 = box
    return lon0 - pad <= p[1] <= lon1 + pad and lat0 - pad <= p[0] <= lat1 + pad


rows = m.circuit_paths()
nodes = {s: v[:2] for s, v in m.LOCATIONS.items()}
nodes.update({k: v[:2] for k, v in m.CLOUD_LOCATIONS.items()})


def end_point(name):
    return nodes[name.split(":", 1)[-1]]


written = []
for fname, title, box, land_name, states in MAPS:
    lon0, lon1, lat0, lat1 = box
    aspect = 1 / math.cos(math.radians((lat0 + lat1) / 2))
    map_w = 11.0
    map_h = map_w * (lat1 - lat0) * aspect / (lon1 - lon0)
    n_links = len({(r["a"], r["b"]) for r in rows
                   if in_box(end_point(r["a"]), box, 0.01) and in_box(end_point(r["b"]), box, 0.01)})
    fig = plt.figure(figsize=(map_w + 4.2, max(map_h + 1.0, 0.2 * n_links + 3.6, 6.5)))
    ax = fig.add_axes([0.02, 0.04, map_w / (map_w + 4.2) - 0.03, 0.88])
    ax.set_xlim(lon0, lon1)
    ax.set_ylim(lat0, lat1)
    ax.set_aspect(aspect)
    ax.set_facecolor("#dfe9f2")
    ax.set_xticks([])
    ax.set_yticks([])

    polys = [Polygon(r, closed=True) for f in layer(land_name) for r in rings(f["geometry"])]
    ax.add_collection(PatchCollection(polys, facecolor="#f4f3ef", edgecolor="#9a9a9a", lw=0.5, zorder=1))
    if land_name == "ne_10m_land":
        lakes = [Polygon(r, closed=True) for f in layer("ne_10m_lakes") for r in rings(f["geometry"])]
        ax.add_collection(PatchCollection(lakes, facecolor="#dfe9f2", edgecolor="#9a9a9a", lw=0.4, zorder=1))
        for f in layer("ne_10m_rivers_lake_centerlines"):
            g = f["geometry"]
            parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
            for part in parts:
                ax.plot([c[0] for c in part], [c[1] for c in part], color="#9cc0dc", lw=2.2, zorder=1.5)
                if f["properties"].get("name") in ("Thames", "Hudson"):
                    vis = [c for c in part if in_box((c[1], c[0]), box)]
                    if vis:
                        c = vis[len(vis) // 3]
                        ax.text(c[0], c[1], f["properties"]["name"], color="#5d8fb8",
                                fontsize=9, style="italic", zorder=1.6)
    if states:
        st = [Polygon(r, closed=True) for f in layer("ne_50m_admin_1_states_provinces_lakes")
              if f["properties"].get("adm0_a3") in ("USA", "CAN", "MEX") for r in rings(f["geometry"])]
        ax.add_collection(PatchCollection(st, facecolor="none", edgecolor="#c4c4c4", lw=0.4, zorder=1))

    # links on this map: both ends inside the frame; others are drawn faint
    links = {}
    for r in rows:
        inside = in_box(end_point(r["a"]), box, 0.01) and in_box(end_point(r["b"]), box, 0.01)
        xs = [p[1] for p in r["path"]]
        ys = [p[0] for p in r["path"]]
        ax.plot(xs, ys, color=COLORS[min(r["circuit"], len(COLORS)) - 1],
                lw=2.0 if inside else 1.0, alpha=0.9 if inside else 0.18,
                solid_capstyle="round", zorder=3 if inside else 2)
        if inside:
            links.setdefault(f"{r['a']}{EN}{r['z']}", []).append(r)

    # markers, then one label per cluster of sites that sit close on screen
    shown = [(n, ll) for n, ll in nodes.items() if in_box(ll, box)]
    for name, (lat, lon) in shown:
        cloud = name in m.CLOUD_LOCATIONS
        ax.plot(lon, lat, marker="s" if cloud else "o", ms=8 if cloud else 9,
                mfc="white", mec="#1a1a1a", mew=2, zorder=5)
    near = (lon1 - lon0) * 0.04
    clusters = []
    for name, (lat, lon) in shown:
        for c in clusters:
            if any(abs(lon - x) < near and abs(lat - y) < near / aspect for _, (y, x) in c):
                c.append((name, (lat, lon)))
                break
        else:
            clusters.append([(name, (lat, lon))])
    dx = (lon1 - lon0) * 0.01
    for c in clusters:
        lat = max(y for _, (y, x) in c)
        lon = max(x for _, (y, x) in c)
        label = " · ".join(n for n, _ in c)
        right = lon > lon0 + 0.8 * (lon1 - lon0)
        ax.annotate(label, (lon, lat), xytext=(lon - dx if right else lon + dx, lat + dx / aspect),
                    ha="right" if right else "left", fontsize=10, fontweight="bold", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.9))

    ax.set_title(f"{m.TITLE} {EN} {title}", fontsize=14, loc="left", pad=8)

    # side panel: links on this map, fastest first
    tx = fig.add_axes([map_w / (map_w + 4.2) - 0.0, 0.04, 4.0 / (map_w + 4.2), 0.88])
    tx.axis("off")
    lines = ["One-way latency (est.)", ""]
    for name, rs in sorted(links.items(), key=lambda kv: min(r["ms"] for r in kv[1])):
        lo = m.fmt_ms(min(r["ms"] for r in rs))
        hi = m.fmt_ms(max(r["ms"] for r in rs))
        lines.append(f"{name:<15}{len(rs)} ckt  {lo if lo == hi else lo + EN + hi} ms")
    tx.text(0.0, 1.0, "\n".join(lines), va="top", ha="left", family="monospace", fontsize=9.5)
    handles = [Line2D([0], [0], color=c, lw=2.5, label=f"Circuit {i + 1}" + (" (direct)" if i == 0 else " (diverse)"))
               for i, c in enumerate(COLORS[:4])]
    tx.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 0.02), frameon=False, fontsize=9.5)
    note = (f"Route = path x {m.ROUTE_FACTOR}, {m.FIBER_US_PER_KM} us/km fiber.\n"
            "Propagation only. Faint lines leave this map.")
    tx.text(0.0, 0.0, note, va="top", ha="left", fontsize=8.5, color="#555555",
            transform=tx.transAxes)

    out = os.path.join(out_dir, fname + ".png")
    fig.savefig(out, dpi=120, facecolor="white")
    plt.close(fig)
    written.append(out)
    print(f"Wrote {out} ({len(links)} links)")
