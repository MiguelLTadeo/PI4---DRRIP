"""
plot_results.py
---------------
Gera gráficos comparativos LRU vs DRRIP a partir dos CSVs em results/.

Saídas (em results/plots/):
    01_hit_rate_l1.png         barras agrupadas L1D hit rate
    02_hit_rate_l2.png         barras agrupadas L2 hit rate
    03_amat.png                AMAT por benchmark/config
    04_overhead.png            overhead de metadados (bits)
    05_mixed_access_zoom.png   zoom no benchmark mixed_access (caso favorável)
"""

from __future__ import annotations

import csv
import os
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


# Cores e estilo
COLOR_LRU = "#377eb8"      # azul
COLOR_DRRIP = "#e41a1c"    # vermelho
plt.rcParams.update({
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "legend.fontsize": 9,
    "figure.figsize": (10, 5),
    "figure.dpi": 110,
})


def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# =============================================================================
# 1+2. Hit rate (L1 e L2) - barras agrupadas
# =============================================================================

def plot_hit_rate_bars(rows, level: str, out_path: str):
    """level in {'l1d', 'l2'}"""
    field = "l1d_hit_rate" if level == "l1d" else "l2_hit_rate"
    title_level = "L1D" if level == "l1d" else "L2 unificada"

    # Estrutura: dict[(config, benchmark)] -> dict[policy -> float]
    data = defaultdict(dict)
    for r in rows:
        data[(r["config"], r["benchmark"])][r["policy"]] = float(r[field]) * 100

    configs = sorted({r["config"] for r in rows})
    benches = ["streaming_hotset", "matrix_conv", "linked_list",
               "pattern_search", "mixed_access"]

    fig, axes = plt.subplots(1, len(configs), figsize=(15, 5),
                              sharey=True)
    if len(configs) == 1:
        axes = [axes]

    x = np.arange(len(benches))
    width = 0.38

    for ax, cfg in zip(axes, configs):
        lru_vals = [data[(cfg, b)]["LRU"] for b in benches]
        drrip_vals = [data[(cfg, b)]["DRRIP"] for b in benches]
        ax.bar(x - width / 2, lru_vals, width, label="LRU", color=COLOR_LRU,
               edgecolor="black", linewidth=0.6)
        ax.bar(x + width / 2, drrip_vals, width, label="DRRIP",
               color=COLOR_DRRIP, edgecolor="black", linewidth=0.6)

        # Anota deltas em pp acima das barras DRRIP
        for i, (lv, dv) in enumerate(zip(lru_vals, drrip_vals)):
            delta = dv - lv
            if abs(delta) >= 0.05:
                ax.annotate(f"{delta:+.1f}", (i + width / 2, dv),
                            ha="center", va="bottom", fontsize=8,
                            color="darkgreen" if delta > 0 else "darkred",
                            xytext=(0, 2), textcoords="offset points")

        ax.set_xticks(x)
        ax.set_xticklabels([b.replace("_", "\n") for b in benches],
                           fontsize=8.5)
        ax.set_title(f"Config {cfg}")
        ax.set_ylim(0, 109)
        ax.grid(axis="y", linestyle=":", alpha=0.5)

    axes[0].set_ylabel(f"Hit rate (%) — {title_level}")
    axes[-1].legend(loc="lower right")
    fig.suptitle(f"Hit rate {title_level}: LRU vs DRRIP  "
                 f"(deltas em pontos percentuais sobre as barras)",
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


# =============================================================================
# 3. AMAT
# =============================================================================

def plot_amat(rows, out_path):
    data = defaultdict(dict)
    for r in rows:
        data[(r["config"], r["benchmark"])][r["policy"]] = float(r["amat_cycles"])

    configs = sorted({r["config"] for r in rows})
    benches = ["streaming_hotset", "matrix_conv", "linked_list",
               "pattern_search", "mixed_access"]

    fig, axes = plt.subplots(1, len(configs), figsize=(15, 5), sharey=True)
    if len(configs) == 1:
        axes = [axes]

    x = np.arange(len(benches))
    width = 0.38

    for ax, cfg in zip(axes, configs):
        lru_vals = [data[(cfg, b)]["LRU"] for b in benches]
        drrip_vals = [data[(cfg, b)]["DRRIP"] for b in benches]
        ax.bar(x - width / 2, lru_vals, width, label="LRU", color=COLOR_LRU,
               edgecolor="black", linewidth=0.6)
        ax.bar(x + width / 2, drrip_vals, width, label="DRRIP",
               color=COLOR_DRRIP, edgecolor="black", linewidth=0.6)

        for i, (lv, dv) in enumerate(zip(lru_vals, drrip_vals)):
            speedup = (lv - dv) / lv * 100 if lv else 0
            if abs(speedup) >= 0.5:
                ax.annotate(f"{speedup:+.1f}%",
                            (i + width / 2, dv),
                            ha="center", va="bottom", fontsize=8,
                            color="darkgreen" if speedup > 0 else "darkred",
                            xytext=(0, 2), textcoords="offset points")

        ax.set_xticks(x)
        ax.set_xticklabels([b.replace("_", "\n") for b in benches],
                           fontsize=8.5)
        ax.set_title(f"Config {cfg}")
        ax.grid(axis="y", linestyle=":", alpha=0.5)

    axes[0].set_ylabel("AMAT (ciclos)")
    axes[-1].legend(loc="upper right")
    fig.suptitle("AMAT (Average Memory Access Time): LRU vs DRRIP  "
                 "(% = speedup do DRRIP)",
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


# =============================================================================
# 4. Overhead
# =============================================================================

def plot_overhead(overhead_rows, out_path):
    labels = [r["cache"] for r in overhead_rows]
    lru_pol = [int(r["LRU_policy_bits_per_set"]) for r in overhead_rows]
    drrip_pol = [int(r["DRRIP_policy_bits_per_set"]) for r in overhead_rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Painel A: bits por conjunto (apenas estado de POLÍTICA)
    x = np.arange(len(labels))
    width = 0.38
    ax1.bar(x - width / 2, lru_pol, width, label="LRU", color=COLOR_LRU,
            edgecolor="black", linewidth=0.6)
    ax1.bar(x + width / 2, drrip_pol, width, label="DRRIP", color=COLOR_DRRIP,
            edgecolor="black", linewidth=0.6)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=30, ha="right", fontsize=8.5)
    ax1.set_ylabel("Bits de metadados de política / conjunto")
    ax1.set_title("Estado de política por conjunto\n(LRU = n·log₂n, DRRIP = n·M, M=2)")
    ax1.grid(axis="y", linestyle=":", alpha=0.5)
    ax1.legend()
    for i, (a, b) in enumerate(zip(lru_pol, drrip_pol)):
        ax1.annotate(str(a), (i - width / 2, a), ha="center", va="bottom",
                     fontsize=8, xytext=(0, 2), textcoords="offset points")
        ax1.annotate(str(b), (i + width / 2, b), ha="center", va="bottom",
                     fontsize=8, xytext=(0, 2), textcoords="offset points")

    # Painel B: economia total (%)
    savings = [float(r["savings_%"].replace("+", "")) for r in overhead_rows]
    colors = ["#2ca02c" if s > 0 else "#d62728" for s in savings]
    bars = ax2.bar(x, savings, color=colors, edgecolor="black", linewidth=0.6)
    ax2.axhline(0, color="black", linewidth=0.7)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=30, ha="right", fontsize=8.5)
    ax2.set_ylabel("Economia total de bits (DRRIP vs LRU, %)")
    ax2.set_title("Redução de overhead total\n(área de SRAM economizada)")
    ax2.grid(axis="y", linestyle=":", alpha=0.5)
    for bar, val in zip(bars, savings):
        ax2.annotate(f"{val:+.2f}%", (bar.get_x() + bar.get_width() / 2, val),
                     ha="center", va="bottom" if val >= 0 else "top",
                     fontsize=8, xytext=(0, 2 if val >= 0 else -2),
                     textcoords="offset points")

    fig.suptitle("Overhead de armazenamento DRRIP vs LRU",
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


# =============================================================================
# 5. Zoom no mixed_access
# =============================================================================

def plot_mixed_access_zoom(rows, out_path):
    """Foco no mixed_access: barra dupla de hit rate L1 + texto explicativo."""
    mixed = [r for r in rows if r["benchmark"] == "mixed_access"]
    mixed.sort(key=lambda r: (r["config"], r["policy"]))
    configs = sorted({r["config"] for r in mixed})

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # painel A: hit rate L1
    x = np.arange(len(configs))
    width = 0.38
    lru = [next(float(r["l1d_hit_rate"]) * 100 for r in mixed
                if r["config"] == c and r["policy"] == "LRU")
           for c in configs]
    drrip = [next(float(r["l1d_hit_rate"]) * 100 for r in mixed
                  if r["config"] == c and r["policy"] == "DRRIP")
             for c in configs]
    ax1.bar(x - width / 2, lru, width, label="LRU", color=COLOR_LRU,
            edgecolor="black", linewidth=0.6)
    ax1.bar(x + width / 2, drrip, width, label="DRRIP", color=COLOR_DRRIP,
            edgecolor="black", linewidth=0.6)
    for i, (lv, dv) in enumerate(zip(lru, drrip)):
        ax1.annotate(f"{lv:.1f}%", (i - width / 2, lv), ha="center",
                     va="bottom", fontsize=9, xytext=(0, 2),
                     textcoords="offset points")
        ax1.annotate(f"{dv:.1f}%\n(+{dv-lv:.1f} pp)",
                     (i + width / 2, dv), ha="center", va="bottom",
                     fontsize=9, color="darkgreen", xytext=(0, 2),
                     textcoords="offset points")
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"Config {c}" for c in configs])
    ax1.set_ylabel("L1D Hit rate (%)")
    ax1.set_title("Hit rate L1D — benchmark mixed_access")
    ax1.set_ylim(0, max(drrip) * 1.20)
    ax1.grid(axis="y", linestyle=":", alpha=0.5)
    ax1.legend()

    # painel B: AMAT
    lru_amat = [next(float(r["amat_cycles"]) for r in mixed
                     if r["config"] == c and r["policy"] == "LRU")
                for c in configs]
    drrip_amat = [next(float(r["amat_cycles"]) for r in mixed
                       if r["config"] == c and r["policy"] == "DRRIP")
                  for c in configs]
    ax2.bar(x - width / 2, lru_amat, width, label="LRU", color=COLOR_LRU,
            edgecolor="black", linewidth=0.6)
    ax2.bar(x + width / 2, drrip_amat, width, label="DRRIP", color=COLOR_DRRIP,
            edgecolor="black", linewidth=0.6)
    for i, (lv, dv) in enumerate(zip(lru_amat, drrip_amat)):
        sp = (lv - dv) / lv * 100
        ax2.annotate(f"{lv:.2f}", (i - width / 2, lv), ha="center",
                     va="bottom", fontsize=9, xytext=(0, 2),
                     textcoords="offset points")
        ax2.annotate(f"{dv:.2f}\n({sp:+.1f}%)",
                     (i + width / 2, dv), ha="center", va="bottom",
                     fontsize=9, color="darkgreen", xytext=(0, 2),
                     textcoords="offset points")
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"Config {c}" for c in configs])
    ax2.set_ylabel("AMAT (ciclos)")
    ax2.set_title("AMAT — benchmark mixed_access")
    ax2.grid(axis="y", linestyle=":", alpha=0.5)
    ax2.legend()

    fig.suptitle("Caso favorável ao DRRIP: padrão "
                 "{working-set + scan invasivo} (Fig. 1d, Jaleel et al. 2010)",
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


# =============================================================================
# main
# =============================================================================
def _hit_rate_global(l1_hit: float, l2_hit: float) -> float:
    """Hit rate global da hierarquia: 1 - (1-h_L1)*(1-h_L2).
 
    Significa: fração dos acessos da CPU que NÃO foram até a memória
    principal — capturados em L1 ou em L2.
    """
    return 1.0 - (1.0 - l1_hit) * (1.0 - l2_hit)
 
 
def plot_summary_table_image(rows, out_path: str):
    """Gera uma figura PNG com a tabela-resumo no formato:
 
        | Trace | LRU-L1 | LRU-Global | DRRIP-L1 | DRRIP-Global | Δ L1 | Interpretação |
 
    Cada linha agrega as 3 configs por média. A coluna 'Interpretação'
    explica em uma frase curta o que está acontecendo, no estilo
    didático adotado por outras equipes da disciplina.
    """
    by_bench = defaultdict(lambda: {"LRU": [], "DRRIP": []})
    for r in rows:
        by_bench[r["benchmark"]][r["policy"]].append(r)
 
    bench_order = [
        "streaming_hotset",
        "matrix_conv",
        "linked_list",
        "pattern_search",
        "mixed_access",
    ]
 
    # Frase curta por benchmark — coluna "Interpretação"
    interp = {
        "streaming_hotset":
            "Empate; localidade\nintra-bloco satura",
        "matrix_conv":
            "Empate; reuso vertical\n3×1 cabe na cache",
        "linked_list":
            "Empate em L1; DRRIP\nmelhora L2 em Config C",
        "pattern_search":
            "Empate; janela cabe\nem um conjunto",
        "mixed_access":
            "DRRIP preserva working\nset durante o scan",
    }
 
    # Calcula médias entre configs
    def avg(items, key):
        return sum(float(r[key]) for r in items) / len(items)
 
    def hit_global_avg(items):
        l1s = [float(r["l1d_hit_rate"]) for r in items]
        l2s = [float(r["l2_hit_rate"]) for r in items]
        gs = [_hit_rate_global(l1, l2) for l1, l2 in zip(l1s, l2s)]
        return sum(gs) / len(gs)
 
    table_rows = []
    for bench in bench_order:
        lru_items = by_bench[bench]["LRU"]
        dr_items = by_bench[bench]["DRRIP"]
 
        lru_l1 = avg(lru_items, "l1d_hit_rate") * 100
        dr_l1 = avg(dr_items, "l1d_hit_rate") * 100
        lru_g = hit_global_avg(lru_items) * 100
        dr_g = hit_global_avg(dr_items) * 100
        delta_l1 = dr_l1 - lru_l1
 
        table_rows.append({
            "trace": bench,
            "lru_l1": f"{lru_l1:.2f}%",
            "lru_g":  f"{lru_g:.2f}%",
            "dr_l1":  f"{dr_l1:.2f}%",
            "dr_g":   f"{dr_g:.2f}%",
            "delta":  f"{delta_l1:+.2f}",
            "interp": interp[bench],
            "highlight": abs(delta_l1) >= 0.1,
        })
 
    # Renderiza como figura matplotlib
    fig, ax = plt.subplots(figsize=(14, 4.5))
    ax.axis("off")
 
    header = ["Trace", "LRU - L1", "LRU - Global",
              "DRRIP - L1", "DRRIP - Global",
              "Δ L1 (pp)", "Interpretação"]
    cells = [
        [r["trace"], r["lru_l1"], r["lru_g"], r["dr_l1"], r["dr_g"],
         r["delta"], r["interp"]]
        for r in table_rows
    ]
 
    tbl = ax.table(
        cellText=cells,
        colLabels=header,
        loc="center",
        cellLoc="center",
        colWidths=[0.14, 0.10, 0.12, 0.11, 0.12, 0.10, 0.31],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    tbl.scale(1, 2.0)
 
    # Cabeçalho azul-escuro, fonte branca (estilo do colega)
    header_color = "#1f3a93"
    for c in range(len(header)):
        cell = tbl[(0, c)]
        cell.set_facecolor(header_color)
        cell.set_text_props(color="white", fontweight="bold")
        cell.set_edgecolor("white")
 
    # Linhas zebra + destaque da linha onde DRRIP ganha
    for i, row in enumerate(table_rows, start=1):
        if row["highlight"]:
            bg = "#fff3a3"          # amarelo claro — destaca a linha de ganho
            txt_color_delta = "#1b7f1b"   # verde forte no delta
        elif i % 2 == 0:
            bg = "#e8eef9"
            txt_color_delta = "#666666"
        else:
            bg = "white"
            txt_color_delta = "#666666"
 
        for c in range(len(header)):
            cell = tbl[(i, c)]
            cell.set_facecolor(bg)
            cell.set_edgecolor("#bbbbbb")
            if c == 5:  # coluna do delta
                cell.set_text_props(
                    color=txt_color_delta,
                    fontweight="bold" if row["highlight"] else "normal",
                )
            if c == 0:  # coluna do trace
                cell.set_text_props(fontweight="bold")
 
    ax.set_title(
        "Tabela geral dos resultados — LRU vs DRRIP\n"
        "Hit rate L1 e Global (média entre Configs A, B, C)",
        fontsize=13, fontweight="bold", pad=12,
    )
 
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=140)
    plt.close(fig)
 

def main():
    rows = load_csv("results/hit_rates.csv")
    overhead = load_csv("results/overhead.csv")
 
    out_dir = "results/plots"
    os.makedirs(out_dir, exist_ok=True)
 
    plot_hit_rate_bars(rows, "l1d", os.path.join(out_dir, "01_hit_rate_l1.png"))
    plot_hit_rate_bars(rows, "l2",  os.path.join(out_dir, "02_hit_rate_l2.png"))
    plot_amat(rows,                  os.path.join(out_dir, "03_amat.png"))
    plot_overhead(overhead,          os.path.join(out_dir, "04_overhead.png"))
    plot_mixed_access_zoom(rows,     os.path.join(out_dir, "05_mixed_access_zoom.png"))
    plot_summary_table_image(rows,   os.path.join(out_dir, "06_summary_table.png"))
 
    print(f"Gráficos gerados em {out_dir}/")
    for name in sorted(os.listdir(out_dir)):
        print(f"  - {name}")
 
 
if __name__ == "__main__":
    main()
