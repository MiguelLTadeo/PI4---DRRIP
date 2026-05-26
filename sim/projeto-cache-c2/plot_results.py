"""
plot_results.py
---------------
Lê results/hit_rates.csv e results/overhead.csv (gerados pelo simulador C)
e produz gráficos comparativos:

  plots/01_hit_rate_l1.png       L1 hit rate, 3 políticas, 3 configs
  plots/02_hit_rate_l2.png       L2 hit rate
  plots/03_amat.png              AMAT
  plots/04_overhead.png          bits de SRAM por política
  plots/05_mixed_access_zoom.png zoom no benchmark favorável ao DRRIP
  plots/06_hit_rates_table.png   tabela com a média dos hit rates e deltas

Único requisito: matplotlib.
"""

import csv
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


COLORS = {
    "LRU":            "#377eb8",  # azul
    "DRRIP_jaleel":   "#e41a1c",  # vermelho — nosso
    "DRRIP_champsim": "#4daf4a",  # verde — champsim
}

LABELS = {
    "LRU":            "LRU",
    "DRRIP_jaleel":   "DRRIP (Jaleel)",
    "DRRIP_champsim": "DRRIP (ChampSim)",
}

plt.rcParams.update({
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "legend.fontsize": 9,
})


def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# -----------------------------------------------------------------------------
def plot_hit_rate(rows, level, out_path):
    """level: 'l1' ou 'l2'"""
    field = "l1_hit_rate" if level == "l1" else "l2_hit_rate"
    title = "L1D" if level == "l1" else "L2 unificada"

    data = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        data[r["config"]][r["benchmark"]][r["policy"]] = float(r[field]) * 100

    configs = sorted(data.keys())
    benches = ["streaming_hotset", "matrix_conv", "linked_list",
               "pattern_search", "mixed_access"]
    policies = ["LRU", "DRRIP_jaleel", "DRRIP_champsim"]

    fig, axes = plt.subplots(1, len(configs), figsize=(16, 5), sharey=True)
    if len(configs) == 1:
        axes = [axes]

    x = np.arange(len(benches))
    width = 0.27

    for ax, cfg in zip(axes, configs):
        for i, pol in enumerate(policies):
            vals = [data[cfg][b].get(pol, 0) for b in benches]
            offset = (i - 1) * width
            ax.bar(x + offset, vals, width,
                   label=LABELS[pol], color=COLORS[pol],
                   edgecolor="black", linewidth=0.5)

        # Anotação: Δ entre DRRIP-jaleel e LRU
        for i, b in enumerate(benches):
            lru = data[cfg][b].get("LRU", 0)
            drrip = data[cfg][b].get("DRRIP_jaleel", 0)
            delta = drrip - lru
            if abs(delta) >= 0.5:
                ax.annotate(f"{delta:+.1f}", (i, max(lru, drrip)),
                            ha="center", va="bottom", fontsize=8,
                            color="darkgreen" if delta > 0 else "darkred",
                            xytext=(0, 3), textcoords="offset points")

        ax.set_xticks(x)
        ax.set_xticklabels([b.replace("_", "\n") for b in benches], fontsize=8.5)
        ax.set_title(f"Config {cfg}")
        ax.set_ylim(0, 109)
        ax.grid(axis="y", linestyle=":", alpha=0.5)

    axes[0].set_ylabel(f"Hit rate (%) — {title}")
    axes[-1].legend(loc="lower right")
    fig.suptitle(f"Hit rate {title} — 3 políticas × 3 configurações",
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=130)
    plt.close(fig)


# -----------------------------------------------------------------------------
def plot_amat(rows, out_path):
    data = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        data[r["config"]][r["benchmark"]][r["policy"]] = float(r["amat_cycles"])

    configs = sorted(data.keys())
    benches = ["streaming_hotset", "matrix_conv", "linked_list",
               "pattern_search", "mixed_access"]
    policies = ["LRU", "DRRIP_jaleel", "DRRIP_champsim"]

    fig, axes = plt.subplots(1, len(configs), figsize=(16, 5), sharey=True)
    if len(configs) == 1:
        axes = [axes]

    x = np.arange(len(benches))
    width = 0.27

    for ax, cfg in zip(axes, configs):
        for i, pol in enumerate(policies):
            vals = [data[cfg][b].get(pol, 0) for b in benches]
            offset = (i - 1) * width
            ax.bar(x + offset, vals, width,
                   label=LABELS[pol], color=COLORS[pol],
                   edgecolor="black", linewidth=0.5)

        for i, b in enumerate(benches):
            lru = data[cfg][b].get("LRU", 0)
            drrip = data[cfg][b].get("DRRIP_jaleel", 0)
            if lru > 0:
                speedup = (lru - drrip) / lru * 100
                if abs(speedup) >= 1:
                    ax.annotate(f"{speedup:+.1f}%",
                                (i, max(lru, drrip)),
                                ha="center", va="bottom", fontsize=8,
                                color="darkgreen" if speedup > 0 else "darkred",
                                xytext=(0, 3), textcoords="offset points")

        ax.set_xticks(x)
        ax.set_xticklabels([b.replace("_", "\n") for b in benches], fontsize=8.5)
        ax.set_title(f"Config {cfg}")
        ax.grid(axis="y", linestyle=":", alpha=0.5)

    axes[0].set_ylabel("AMAT (ciclos)")
    axes[-1].legend(loc="upper right")
    fig.suptitle("AMAT — 3 políticas × 3 configurações  "
                 "(% = speedup DRRIP-Jaleel vs LRU)",
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=130)
    plt.close(fig)


# -----------------------------------------------------------------------------
def plot_overhead(rows, out_path):
    """Agrupa por (cache_label, policy) e mostra bits totais."""
    by_cache = defaultdict(dict)
    for r in rows:
        by_cache[r["cache"]][r["policy"]] = int(r["total_bits"])

    labels = sorted(by_cache.keys(), key=lambda x: (x[:3], x[-1]))
    policies = ["LRU", "DRRIP_jaleel", "DRRIP_champsim"]

    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(len(labels))
    width = 0.27

    for i, pol in enumerate(policies):
        vals = [by_cache[l].get(pol, 0) for l in labels]
        offset = (i - 1) * width
        ax.bar(x + offset, vals, width,
               label=LABELS[pol], color=COLORS[pol],
               edgecolor="black", linewidth=0.5)
        for j, v in enumerate(vals):
            ax.annotate(f"{v}", (j + offset, v), ha="center", va="bottom",
                        fontsize=7, xytext=(0, 2), textcoords="offset points")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("Bits de SRAM totais")
    ax.set_title("Overhead de armazenamento — LRU vs DRRIP (Jaleel) vs DRRIP (ChampSim)",
                 fontweight="bold")
    ax.legend()
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=130)
    plt.close(fig)


# -----------------------------------------------------------------------------
def plot_mixed_access_zoom(rows, out_path):
    mixed = [r for r in rows if r["benchmark"] == "mixed_access"]
    configs = sorted({r["config"] for r in mixed})
    policies = ["LRU", "DRRIP_jaleel", "DRRIP_champsim"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    x = np.arange(len(configs))
    width = 0.27

    # L1 hit rate
    for i, pol in enumerate(policies):
        vals = []
        for cfg in configs:
            v = next((float(r["l1_hit_rate"]) * 100
                      for r in mixed if r["config"] == cfg and r["policy"] == pol),
                     0)
            vals.append(v)
        offset = (i - 1) * width
        ax1.bar(x + offset, vals, width,
                label=LABELS[pol], color=COLORS[pol],
                edgecolor="black", linewidth=0.5)
        for j, v in enumerate(vals):
            ax1.annotate(f"{v:.1f}%", (j + offset, v),
                         ha="center", va="bottom", fontsize=8,
                         xytext=(0, 2), textcoords="offset points")
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"Config {c}" for c in configs])
    ax1.set_ylabel("L1D Hit rate (%)")
    ax1.set_title("Hit rate L1D — benchmark mixed_access")
    ax1.set_ylim(0, 100)
    ax1.grid(axis="y", linestyle=":", alpha=0.5)
    ax1.legend(loc="lower right")

    # AMAT
    for i, pol in enumerate(policies):
        vals = []
        for cfg in configs:
            v = next((float(r["amat_cycles"])
                      for r in mixed if r["config"] == cfg and r["policy"] == pol),
                     0)
            vals.append(v)
        offset = (i - 1) * width
        ax2.bar(x + offset, vals, width,
                label=LABELS[pol], color=COLORS[pol],
                edgecolor="black", linewidth=0.5)
        for j, v in enumerate(vals):
            ax2.annotate(f"{v:.2f}", (j + offset, v),
                         ha="center", va="bottom", fontsize=8,
                         xytext=(0, 2), textcoords="offset points")
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"Config {c}" for c in configs])
    ax2.set_ylabel("AMAT (ciclos)")
    ax2.set_title("AMAT — benchmark mixed_access")
    ax2.grid(axis="y", linestyle=":", alpha=0.5)
    ax2.legend(loc="upper right")

    fig.suptitle("Zoom no benchmark mixed_access — "
                 "working set + scan invasivo (Fig. 1d, Jaleel et al.)",
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=130)
    plt.close(fig)


# -----------------------------------------------------------------------------
def plot_summary_table(rows, out_path):
    """Calcula médias das configs e plota tabela comparativa formatada em PNG."""
    data = defaultdict(lambda: defaultdict(lambda: {'l1': [], 'l2': []}))

    for r in rows:
        bench = r["benchmark"]
        pol = r["policy"]
        data[bench][pol]['l1'].append(float(r["l1_hit_rate"]))
        data[bench][pol]['l2'].append(float(r["l2_hit_rate"]))

    benchmarks = ["streaming_hotset", "matrix_conv", "linked_list", "pattern_search", "mixed_access"]
    policies = ["LRU", "DRRIP_jaleel", "DRRIP_champsim"]

    columns = [
        "TRACE",
        "LRU\nL1", "LRU\nL2",
        "DRRIP\nL1", "DRRIP\nL2",
        "CHAMPSIM\nL1", "CHAMPSIM\nL2",
        "Δ L1\nDRRIP", "Δ L1\nCHAMPSIM"
    ]

    cell_text = []
    cell_colors = []

    for b in benchmarks:
        row_data = [b]
        row_colors = ["#1f2937"] 

        means = {}
        for p in policies:
            l1_mean = (sum(data[b][p]['l1']) / len(data[b][p]['l1'])) * 100 if data[b][p]['l1'] else 0
            l2_mean = (sum(data[b][p]['l2']) / len(data[b][p]['l2'])) * 100 if data[b][p]['l2'] else 0
            means[p] = {'l1': l1_mean, 'l2': l2_mean}

            row_data.extend([f"{l1_mean:.2f}%", f"{l2_mean:.2f}%"])
            row_colors.extend(["#2d3748", "#2d3748"])

        delta_jaleel = means["DRRIP_jaleel"]["l1"] - means["LRU"]["l1"]
        delta_champsim = means["DRRIP_champsim"]["l1"] - means["LRU"]["l1"]

        row_data.extend([f"{delta_jaleel:+.2f}", f"{delta_champsim:+.2f}"])

        for delta in [delta_jaleel, delta_champsim]:
            if delta > 0.5:
                row_colors.append("#065f46") 
            elif delta < -0.5:
                row_colors.append("#7f1d1d") 
            else:
                row_colors.append("#2d3748")

        cell_text.append(row_data)
        cell_colors.append(row_colors)

    fig, ax = plt.subplots(figsize=(14, 3.5)) 
    ax.axis('tight')
    ax.axis('off') 

    table = ax.table(
        cellText=cell_text,
        colLabels=columns,
        cellColours=cell_colors,
        loc='center',
        cellLoc='center'
    )

    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.0, 2.0) 

    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor('#4b5563') 
        if row == 0:
            cell.set_facecolor("#1e3a8a") 
            cell.set_text_props(weight='bold', color='white', fontsize=10)
        else:
            texto = cell.get_text().get_text()
            if col >= 7 and row > 0: 
                try:
                    val = float(texto)
                    if val > 0:
                        cell.set_text_props(color='#34d399', weight='bold') 
                    elif val < 0:
                        cell.set_text_props(color='#f87171', weight='bold') 
                    else:
                        cell.set_text_props(color='#d1d5db')
                except ValueError:
                    cell.set_text_props(color='#d1d5db')
            else:
                cell.set_text_props(color='#f3f4f6') 

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=200, facecolor='#111827')
    plt.close(fig)


# -----------------------------------------------------------------------------
def main():
    hit_rows = load_csv("results/hit_rates.csv")
    ov_rows = load_csv("results/overhead.csv")

    os.makedirs("plots", exist_ok=True)
    plot_hit_rate(hit_rows, "l1", "plots/01_hit_rate_l1.png")
    plot_hit_rate(hit_rows, "l2", "plots/02_hit_rate_l2.png")
    plot_amat(hit_rows,            "plots/03_amat.png")
    plot_overhead(ov_rows,         "plots/04_overhead.png")
    plot_mixed_access_zoom(hit_rows, "plots/05_mixed_access_zoom.png")
    
    # Adicionando a sua tabela à pipeline!
    plot_summary_table(hit_rows,   "plots/06_hit_rates_table.png")

    print("Gráficos gerados:")
    for f in sorted(os.listdir("plots")):
        print("  plots/" + f)


if __name__ == "__main__":
    main()