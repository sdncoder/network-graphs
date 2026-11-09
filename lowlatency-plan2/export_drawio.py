"""
Export a backbone model (e.g. Low Latency Prem-to-Cloud Plan2) to draw.io
for draw.io or Lucidchart.

- Sites are circles, clouds/Internet are rounded boxes, CGX is a small badge.
- Every circuit is its own connector with fixed exit/entry points so
  parallel circuits stay side by side.
- Circuit counts are text labels at each link's midpoint.
- REGIONS (if the model defines them) become dotted, unfilled boxes with a
  label on the top edge, placed behind everything else.

Run (from the repo root):  python lowlatency-plan2/export_drawio.py [model.py] [output.drawio]
"""
import sys
import math
import os
import importlib.util
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
model_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "lowlatency_plan2_model.py")
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "lowlatency_plan2.drawio")

spec = importlib.util.spec_from_file_location("model", model_path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

G = m.build_graph()
pos = {n: d["pos"] for n, d in G.nodes(data=True)}
R, GAP = m.SITE_R, m.CIRCUIT_GAP
CW, CH = m.CLOUD_W, m.CLOUD_H
LABEL_T = getattr(m, "LABEL_T", {})
CGX_BADGE = getattr(m, "CGX_BADGE", {})
REGIONS = getattr(m, "REGIONS", {})
TITLE = getattr(m, "TITLE", "Backbone")

cells = []
ids = {}


def cid(name):
    if name not in ids:
        ids[name] = f"n{len(ids) + 1}"
    return ids[name]


def box(node):
    x, y = pos[node]
    if G.nodes[node]["kind"] == "site":
        return x - R, y - R, 2 * R, 2 * R
    return x - CW / 2, y - CH / 2, CW, CH


def boundary_point(node, ux, uy, nx_, ny_, off):
    cx, cy = pos[node]
    if G.nodes[node]["kind"] == "site":
        along = math.sqrt(max(R * R - off * off, 0))
    else:
        ox, oy = nx_ * off, ny_ * off
        tx = (CW / 2 - abs(ox)) / abs(ux) if abs(ux) > 1e-9 else 1e9
        ty = (CH / 2 - abs(oy)) / abs(uy) if abs(uy) > 1e-9 else 1e9
        along = min(tx, ty)
    return cx + ux * along + nx_ * off, cy + uy * along + ny_ * off


def rel(node, px, py):
    bx, by, bw, bh = box(node)
    return (px - bx) / bw, (py - by) / bh


# --- regions first so they sit behind everything ---------------------------
for name, (members, pad, lt, *rest) in REGIONS.items():
    edge = rest[0] if rest else "top"
    x0, y0, x1, y1 = m.region_box(members, pad)
    cells.append(f'<mxCell id="{cid("region:" + name)}" value="" style="rounded=0;whiteSpace=wrap;html=1;'
                 f'fillColor=none;strokeColor=#1A1A1A;strokeWidth=2;dashed=1;dashPattern=2 4;" '
                 f'vertex="1" parent="1"><mxGeometry x="{x0:.1f}" y="{y0:.1f}" '
                 f'width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" as="geometry"/></mxCell>')
    lx = x0 + (x1 - x0) * lt
    cells.append(f'<mxCell id="{cid("region-label:" + name)}" value="{escape(name)}" '
                 f'style="text;html=1;align=center;verticalAlign=middle;fillColor=#FFFFFF;'
                 f'fontStyle=1;fontSize=18;fontColor=#1A1A1A;" vertex="1" parent="1">'
                 f'<mxGeometry x="{lx - 50:.1f}" y="{(y0 if edge == 'top' else y1) - 14:.1f}" width="100" height="28" as="geometry"/></mxCell>')

# --- vertices --------------------------------------------------------------
for n, d in G.nodes(data=True):
    x, y, w, h = box(n)
    if d["kind"] == "site":
        style = ("ellipse;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#1A1A1A;"
                 f"strokeWidth=4;fontStyle=1;fontSize=17;fontColor=#1A1A1A;")
        label = n
    else:
        style = ("rounded=1;arcSize=40;whiteSpace=wrap;html=1;fillColor=#FFFFFF;"
                 "strokeColor=#1A1A1A;strokeWidth=2;fontSize=13;fontColor=#1A1A1A;")
        label = d["label"].replace("\n", "<br>")
    cells.append(f'<mxCell id="{cid(n)}" value="{escape(label, {chr(34): "&quot;"})}" '
                 f'style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" as="geometry"/></mxCell>')
    if d["kind"] == "site" and d["cgx"]:
        bx, by = CGX_BADGE.get(n, (0.9, -0.95))
        cx, cy = pos[n][0] + R * bx, pos[n][1] + R * by
        cells.append(f'<mxCell id="{cid(n + ":CGX")}" value="CGX" style="rounded=1;whiteSpace=wrap;html=1;'
                     f'fillColor=#FFFFFF;strokeColor=#1A1A1A;strokeWidth=2;fontSize=13;" vertex="1" parent="1">'
                     f'<mxGeometry x="{cx - 26:.1f}" y="{cy - 14:.1f}" width="52" height="28" as="geometry"/></mxCell>')

# --- circuits + count labels -----------------------------------------------
links = {}
for a, b, d in G.edges(data=True):
    links.setdefault((a, b), d)

placed = m.place_labels(G) if hasattr(m, "place_labels") else {}
edge_n = 0
for (a, b), d in links.items():
    n = d["of"]
    (x1, y1), (x2, y2) = pos[a], pos[b]
    L = math.hypot(x2 - x1, y2 - y1)
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    nx_, ny_ = -uy, ux
    for k in range(n):
        off = (k - (n - 1) / 2) * GAP
        sx, sy = rel(a, *boundary_point(a, ux, uy, nx_, ny_, off))
        tx, ty = rel(b, *boundary_point(b, -ux, -uy, nx_, ny_, off))
        edge_n += 1
        style = (f"endArrow=none;startArrow=none;html=1;strokeColor=#1A1A1A;strokeWidth=2;"
                 f"exitX={sx:.4f};exitY={sy:.4f};exitDx=0;exitDy=0;exitPerimeter=0;"
                 f"entryX={tx:.4f};entryY={ty:.4f};entryDx=0;entryDy=0;entryPerimeter=0;")
        cells.append(f'<mxCell id="e{edge_n}" value="" style="{style}" edge="1" parent="1" '
                     f'source="{cid(a)}" target="{cid(b)}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    if (a, b) in placed:
        lx, ly, txt = placed[(a, b)]
    else:
        t = LABEL_T.get((a, b), 0.5 if d["kind"] == "backbone" else 0.55)
        lx, ly, txt = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, str(n)
    w, h = (22, 26) if txt.isdigit() else (7.2 * len(txt) + 10, 24)
    fs = 14 if txt.isdigit() else 11
    cells.append(f'<mxCell id="lbl{edge_n}" value="{escape(txt)}" style="rounded=1;whiteSpace=wrap;html=1;'
                 f'fillColor=#FFFFFF;strokeColor=#1A1A1A;strokeWidth=1;fontStyle=1;fontSize={fs};" '
                 f'vertex="1" parent="1"><mxGeometry x="{lx - w / 2:.1f}" y="{ly - h / 2:.1f}" width="{w:.1f}" '
                 f'height="{h}" as="geometry"/></mxCell>')

xml = (f'<mxfile host="drawio"><diagram id="plan" name="{escape(TITLE)}">'
       '<mxGraphModel dx="2200" dy="1700" grid="0" gridSize="10" guides="1" tooltips="1" '
       'connect="1" arrows="0" fold="1" page="0" pageScale="1" pageWidth="2400" pageHeight="1800" '
       'math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
       + "".join(cells) +
       '</root></mxGraphModel></diagram></mxfile>')
open(out, "w").write(xml)
print(f"Wrote {out}: {len(ids)} shapes, {edge_n} circuit connectors, {len(links)} count labels, "
      f"{len(REGIONS)} region(s)")
