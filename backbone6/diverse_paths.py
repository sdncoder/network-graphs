"""
Backbone6 - diverse A/B path latency to AWS East

For every Backbone1 site, find the pair of diverse paths (A and B) to AWS East
and the latency differential (skew) between them.

  - Diverse: A and B share no links, no transit sites and no AWS on-ramp, so
    one path always enters AWS East at SEC1 and the other at MIA.
  - A/B pair: the diverse pair with the lowest combined latency
    (the usual way to pick A/B; Suurballe-style).
  - Min possible diff: the smallest skew any diverse pair can reach for that
    site, usually by routing both paths the long way.
  - Latency: the same propagation estimate as backbone6_model.py
    (great-circle km x 1.3 route factor x 4.9 us/km); excludes equipment delay.

Outputs
  diverse_paths_aws_east.md   table, sorted by differential
  diverse_paths_aws_east.csv  same data
  diverse_paths_sec1.png      drawing of the highest-differential site's
                              Path A (red) and Path B (blue)

Usage
  python diverse_paths.py Backbone-Split5.numbers
"""

import csv
import itertools
import sys

import matplotlib.pyplot as plt
import networkx as nx

import backbone6_model as m

TARGET = "AWS East"
A_COLOR, B_COLOR, BASE = "#d62728", "#1f5fbf", "#c8c8c8"


def path_ms(G, p):
    return sum(G.edges[a, b]["latency_ms"] for a, b in zip(p, p[1:]))


def diverse_pairs(G, site):
    """Best (min total) and min-skew diverse A/B pairs from site to TARGET."""
    paths = [(path_ms(G, p), p) for p in nx.all_simple_paths(G, site, TARGET)]
    best = minskew = None
    for x, y in itertools.combinations(paths, 2):
        if set(x[1][1:-1]) & set(y[1][1:-1]):      # shared transit site / on-ramp
            continue
        a, b = sorted((x, y), key=lambda t: t[0])  # A = lower latency
        if best is None or a[0] + b[0] < best[0][0] + best[1][0]:
            best = (a, b)
        if minskew is None or b[0] - a[0] < minskew[1][0] - minskew[0][0]:
            minskew = (a, b)
    return best, minskew


def analyse(G):
    H = G.copy()
    H.remove_nodes_from([n for n, d in G.nodes(data=True)
                         if d["role"] == "cloud" and n != TARGET])
    rows = []
    for s in (n for n, d in H.nodes(data=True) if d["role"] == "backbone1"):
        (a, b), (ma, mb) = diverse_pairs(H, s)
        rows.append(dict(site=s, a_ms=a[0], a_path=a[1], b_ms=b[0], b_path=b[1],
                         diff=b[0] - a[0], min_diff=mb[0] - ma[0],
                         min_a=ma[0], min_b=mb[0]))
    rows.sort(key=lambda r: -r["diff"])
    return rows


def via(p):
    mid = p[1:-1]
    return "direct" if not mid else "via " + ", ".join(mid)


def chain(p):
    return " → ".join(p)


# ---------------------------------------------------------------- outputs

def write_table(rows, md, csv_path):
    top = rows[0]
    lines = [
        "# Backbone6 — diverse A/B path latency to AWS East",
        "",
        f"Highest differential: **{top['site']} — {top['diff']:.1f} ms** "
        f"(A {top['a_ms']:.1f} ms {via(top['a_path'])}, "
        f"B {top['b_ms']:.1f} ms {via(top['b_path'])}).",
        "",
        "| Site | Path A | Path B | Differential | Min possible differential |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        bold = "**" if r is top else ""
        lines.append(
            f"| {bold}{r['site']}{bold} "
            f"| {r['a_ms']:.1f} ms — {chain(r['a_path'])} "
            f"| {r['b_ms']:.1f} ms — {chain(r['b_path'])} "
            f"| {bold}{r['diff']:.1f} ms{bold} "
            f"| {r['min_diff']:.1f} ms ({r['min_a']:.1f} / {r['min_b']:.1f}) |")
    lines += [
        "",
        "- **Diverse:** A and B share no links, transit sites or AWS on-ramp, "
        "so one path enters AWS East at SEC1 and the other at MIA.",
        "- **Path A / Path B:** the diverse pair with the lowest combined "
        "latency; A is the lower-latency leg.",
        "- **Min possible differential:** the lowest skew any diverse pair can "
        "reach (A / B latency shown), usually by routing both legs the long way.",
        "- **Latency:** propagation estimate, great-circle km × 1.3 route factor "
        "× 4.9 µs/km fiber, AWS East assumed at us-east-1 (Ashburn, VA). "
        "Excludes equipment and queueing delay.",
        "- SEC1 and MIA are the AWS East on-ramps, so their differential cannot "
        "be reduced: one leg is always the direct on-ramp.",
        "",
        "![Highest-differential A/B paths](diverse_paths_sec1.png)",
        "",
    ]
    open(md, "w").write("\n".join(lines))

    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "path_a_ms", "path_a", "path_b_ms", "path_b",
                    "differential_ms", "min_possible_differential_ms",
                    "min_pair_a_ms", "min_pair_b_ms"])
        for r in rows:
            w.writerow([r["site"], f"{r['a_ms']:.2f}", chain(r["a_path"]),
                        f"{r['b_ms']:.2f}", chain(r["b_path"]),
                        f"{r['diff']:.2f}", f"{r['min_diff']:.2f}",
                        f"{r['min_a']:.2f}", f"{r['min_b']:.2f}"])
    print(f"Saved {md}, {csv_path}")


def draw_paths(G, row, out):
    pos = m.layout(G)
    a_edges = list(zip(row["a_path"], row["a_path"][1:]))
    b_edges = list(zip(row["b_path"], row["b_path"][1:]))
    on = {frozenset(e) for e in a_edges + b_edges}
    rest = [(u, v) for u, v in G.edges() if frozenset((u, v)) not in on]
    bb = [n for n, d in G.nodes(data=True) if d["role"] == "backbone1"]
    clouds = [n for n, d in G.nodes(data=True) if d["role"] == "cloud"]
    used = set(row["a_path"]) | set(row["b_path"])

    fig, ax = plt.subplots(figsize=(18, 11))
    fig.patch.set_facecolor("white")
    ax.set_aspect("equal")

    # The rest of the network, muted; the A and B paths on top, straight lines
    nx.draw_networkx_edges(G, pos, edgelist=rest, ax=ax, edge_color=BASE,
                           width=1.6, arrows=False)
    nx.draw_networkx_edges(G, pos, edgelist=a_edges, ax=ax, edge_color=A_COLOR,
                           width=4.5, arrows=False)
    nx.draw_networkx_edges(G, pos, edgelist=b_edges, ax=ax, edge_color=B_COLOR,
                           width=4.5, arrows=False)

    nx.draw_networkx_nodes(G, pos, nodelist=[n for n in bb if n not in used],
                           ax=ax, node_size=520, node_color="white",
                           edgecolors=BASE, linewidths=2.0)
    nx.draw_networkx_nodes(G, pos, nodelist=[n for n in bb if n in used],
                           ax=ax, node_size=620, node_color="white",
                           edgecolors="#1f1f1f", linewidths=2.4)
    for c in clouds:
        m.draw_cloud(ax, pos[c], c)

    # Labels for the sites on the two paths only
    for n in used & set(bb):
        x, y = pos[n]
        ax.text(x, y + 0.48, n, ha="center", va="bottom", fontsize=11,
                fontweight="bold", color="#1f1f1f", zorder=6)

    # Per-hop latency on each path
    for edges, col in ((a_edges, A_COLOR), (b_edges, B_COLOR)):
        for u, v in edges:
            ms = G.edges[u, v]["latency_ms"]
            x = (pos[u][0] + pos[v][0]) / 2
            y = (pos[u][1] + pos[v][1]) / 2
            ax.text(x, y, m.fmt_ms(ms), fontsize=9.5, color=col,
                    ha="center", va="center", zorder=7, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=col,
                              lw=1.0))

    # Legend box
    legend = (f"Path A  {row['a_ms']:.1f} ms   {chain(row['a_path'])}\n"
              f"Path B  {row['b_ms']:.1f} ms   {chain(row['b_path'])}\n"
              f"Differential  {row['diff']:.1f} ms")
    ax.text(0.01, 0.02, legend, transform=ax.transAxes, fontsize=11,
            family="monospace", va="bottom", ha="left", zorder=8,
            bbox=dict(boxstyle="round,pad=0.6", fc="white", ec="#888888"))
    ax.plot([], [], color=A_COLOR, lw=4.5, label="Path A")
    ax.plot([], [], color=B_COLOR, lw=4.5, label="Path B")
    ax.legend(loc="upper right", fontsize=11, frameon=True)

    ax.set_title(f"Backbone6 — highest A/B differential to AWS East: "
                 f"{row['site']} ({row['diff']:.1f} ms)", fontsize=15, pad=14)
    fig.text(0.5, 0.02,
             "Diverse = no shared links, transit sites or AWS on-ramp. "
             "Latency = great-circle km × 1.3 × 4.9 µs/km; AWS East assumed "
             "us-east-1 (Ashburn, VA). Excludes equipment delay.",
             ha="center", fontsize=9.5, color="#555555")
    ax.axis("off")
    ax.margins(0.05)
    plt.tight_layout(rect=(0, 0.04, 1, 1))
    plt.savefig(out, dpi=200, facecolor="white")
    print(f"Saved {out}")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "Backbone-Split5.numbers"
    backbone, sites = m.load(src)
    G, _ = m.build_graph(backbone, sites)
    rows = analyse(G)

    for r in rows:
        print(f"{r['site']:5} A {r['a_ms']:5.1f}  B {r['b_ms']:5.1f}  "
              f"diff {r['diff']:5.1f}  min {r['min_diff']:4.1f}")
    write_table(rows, "diverse_paths_aws_east.md", "diverse_paths_aws_east.csv")
    draw_paths(G, rows[0], "diverse_paths_sec1.png")


if __name__ == "__main__":
    main()
