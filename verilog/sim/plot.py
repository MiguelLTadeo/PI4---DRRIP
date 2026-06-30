"""Gera gráfico Hit rate L1D — LRU vs DRRIP (Verilog), 3 painéis."""

import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

CONFIGS    = ['A', 'B', 'C']
BENCHMARKS = ['streaming_hotset', 'matrix_conv', 'linked_list',
              'pattern_search',   'mixed_access']
LABELS     = ['streaming\nhotset', 'matrix\nconv', 'linked\nlist',
              'pattern\nsearch',   'mixed\naccess']
COLORS = {'LRU': '#3a76c4', 'DRRIP': '#2a9d3f'}

R = {c: {b: {} for b in BENCHMARKS} for c in CONFIGS}
with open('sim/results.csv') as f:
    for row in csv.DictReader(f):
        R[row['config']][row['benchmark']][row['policy']] = float(row['hit_rate']) * 100


def panel(ax, cfg, title):
    x = np.arange(len(BENCHMARKS))
    w = 0.38
    for i, pol in enumerate(['LRU', 'DRRIP']):
        vals = [R[cfg][b][pol] for b in BENCHMARKS]
        offset = (i - 0.5) * w
        ax.bar(x + offset, vals, w, label=pol, color=COLORS[pol],
               edgecolor='black', linewidth=0.5)
    # Anotação de delta
    for j, b in enumerate(BENCHMARKS):
        d = R[cfg][b]['DRRIP'] - R[cfg][b]['LRU']
        if abs(d) >= 0.1:
            color = '#1b8a35' if d > 0 else '#c43030'
            sign  = '+' if d > 0 else ''
            ax.text(j + 0.5 * w, R[cfg][b]['DRRIP'] + 1.5,
                    f'{sign}{d:.1f}', ha='center', va='bottom',
                    color=color, fontsize=9, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(LABELS, fontsize=9)
    ax.set_ylim(0, 105)
    ax.set_title(title, fontsize=11)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)


fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), sharey=True)
for k, cfg in enumerate(CONFIGS):
    panel(axes[k], cfg, f'Config {cfg}')
axes[0].set_ylabel('Hit rate (%) — L1D Verilog', fontsize=10)
axes[-1].legend(loc='lower right', fontsize=9, framealpha=0.95)
fig.suptitle('Hit rate L1D — LRU vs DRRIP (implementação Verilog)',
             fontsize=13, fontweight='bold')
fig.tight_layout(rect=[0, 0, 1, 0.95])
fig.savefig('docs/hit_rate_verilog.png', dpi=130, bbox_inches='tight')
print("gerado: docs/hit_rate_verilog.png")
