"""
visualize.py
------------
Genera las evidencias graficas pedidas en el parcial:

  1. network_snapshot_<tag>.png   -> estado de la red (nodos coloreados por
     nivel de congestion: normal / warning / critical) en un paso dado.
  2. timeseries_<escenario>.png   -> dinamica en el tiempo (cola media,
     proporcion de nodos congestionados, throughput) comparando
     sin control vs con control, para un escenario.
  3. comparison_bars.png          -> barras comparativas (con barras de error)
     de las metricas obligatorias entre condiciones, para los 3 escenarios.

Todas las figuras se guardan en outputs/.
"""

import os
import csv
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx

from model import NetworkCongestionModel
from experiments import SCENARIOS, FIXED_PARAMS, OUTPUT_DIR

STATUS_COLOR = {"normal": "#4CAF50", "warning": "#FFC107", "critical": "#E53935"}


def plot_network_snapshot(scenario_name="alta", control_enabled=False, step_to_run=150,
                           seed=2024, tag=None):
    params = dict(FIXED_PARAMS)
    params.update(SCENARIOS[scenario_name])
    params["control_enabled"] = control_enabled
    params["seed"] = seed
    model = NetworkCongestionModel(**params)
    model.run(step_to_run)

    pos = nx.spring_layout(model.G, seed=1)
    colors = [STATUS_COLOR[model.agents_by_id[n].status] for n in model.G.nodes]
    sizes = [120 + 400 * model.agents_by_id[n].occupancy for n in model.G.nodes]

    fig, ax = plt.subplots(figsize=(8, 7))
    nx.draw_networkx_edges(model.G, pos, ax=ax, alpha=0.3, edge_color="#888888")
    nx.draw_networkx_nodes(model.G, pos, ax=ax, node_color=colors, node_size=sizes,
                            edgecolors="black", linewidths=0.5)
    nx.draw_networkx_nodes(model.G, pos, ax=ax, nodelist=model.hotspots,
                            node_color="none", node_size=[s + 220 for s in
                            [120 + 400 * model.agents_by_id[n].occupancy for n in model.hotspots]],
                            edgecolors="#1565C0", linewidths=2.5)
    nx.draw_networkx_labels(model.G, pos, ax=ax, font_size=7)

    legend_handles = [
        plt.Line2D([0], [0], marker='o', color='w', label=lbl,
                   markerfacecolor=col, markersize=10, markeredgecolor='black')
        for lbl, col in [("Normal", STATUS_COLOR["normal"]),
                          ("Proximo a congestion", STATUS_COLOR["warning"]),
                          ("Congestionado", STATUS_COLOR["critical"])]
    ]
    legend_handles.append(
        plt.Line2D([0], [0], marker='o', color='w', label="Hotspot (gateway)",
                   markerfacecolor='none', markersize=12, markeredgecolor='#1565C0', markeredgewidth=2)
    )
    ax.legend(handles=legend_handles, loc="upper left", fontsize=8, framealpha=0.9)

    ctrl_txt = "CON control" if control_enabled else "SIN control"
    ax.set_title(f"Estado de la red — escenario '{scenario_name}' ({ctrl_txt}), paso {step_to_run}\n"
                 f"Tamano del nodo = ocupacion de su cola", fontsize=11)
    ax.axis("off")

    tag = tag or f"{scenario_name}_control_{control_enabled}"
    out_path = os.path.join(OUTPUT_DIR, f"network_snapshot_{tag}.png")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print("guardado:", out_path)
    return out_path


def plot_timeseries(scenario_name):
    """Compara sin/con control la evolucion temporal de metricas clave,
    usando las corridas representativas guardadas por experiments.py."""
    def load_history(tag):
        path = os.path.join(OUTPUT_DIR, f"history_{scenario_name}_control_{tag}.csv")
        with open(path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        cols = {k: [float(r[k]) for r in rows] for k in rows[0].keys()}
        return cols

    hist_false = load_history(False)
    hist_true = load_history(True)

    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True)

    axes[0].plot(hist_false["step"], hist_false["mean_queue"], label="Sin control", color="#E53935")
    axes[0].plot(hist_true["step"], hist_true["mean_queue"], label="Con control", color="#1E88E5")
    axes[0].set_ylabel("Cola media (paquetes)")
    axes[0].legend(fontsize=8)
    axes[0].set_title(f"Dinamica temporal — escenario '{scenario_name}'")

    axes[1].plot(hist_false["step"], hist_false["prop_congested_nodes"], color="#E53935")
    axes[1].plot(hist_true["step"], hist_true["prop_congested_nodes"], color="#1E88E5")
    axes[1].set_ylabel("Prop. nodos\ncongestionados")

    axes[2].plot(hist_false["step"], hist_false["throughput"], color="#E53935", alpha=0.6)
    axes[2].plot(hist_true["step"], hist_true["throughput"], color="#1E88E5", alpha=0.6)
    axes[2].set_ylabel("Throughput\n(paquetes entregados/paso)")
    axes[2].set_xlabel("Paso de simulacion")

    fig.tight_layout()
    out_path = os.path.join(OUTPUT_DIR, f"timeseries_{scenario_name}.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print("guardado:", out_path)
    return out_path


def plot_comparison_bars():
    agg_path = os.path.join(OUTPUT_DIR, "runs_aggregate.csv")
    with open(agg_path) as f:
        rows = list(csv.DictReader(f))

    scenarios = list(SCENARIOS.keys())
    metrics = [
        ("delivery_ratio", "Tasa de entrega"),
        ("mean_latency", "Latencia media (pasos)"),
        ("prop_congested_nodes", "Prop. nodos congestionados"),
        ("dropped", "Paquetes descartados (total)"),
    ]

    fig, axes = plt.subplots(1, 4, figsize=(18, 4.5))
    x = range(len(scenarios))
    width = 0.35

    for ax, (mkey, mlabel) in zip(axes, metrics):
        for offset, control, color, label in [(-width/2, "False", "#E53935", "Sin control"),
                                                (width/2, "True", "#1E88E5", "Con control")]:
            means, stds = [], []
            for sc in scenarios:
                row = next(r for r in rows if r["scenario"] == sc and r["control_enabled"] == control)
                means.append(float(row[f"{mkey}_mean"]))
                stds.append(float(row[f"{mkey}_std"]))
            ax.bar([xi + offset for xi in x], means, width=width, yerr=stds, capsize=3,
                   color=color, label=label)
        ax.set_xticks(list(x))
        ax.set_xticklabels(scenarios)
        ax.set_title(mlabel, fontsize=10)
        ax.grid(axis="y", alpha=0.3)

    axes[0].legend(fontsize=8)
    fig.suptitle("Comparacion sin control vs con control por escenario de carga\n"
                 "(media ± desv. estandar sobre 10 repeticiones)", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    out_path = os.path.join(OUTPUT_DIR, "comparison_bars.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print("guardado:", out_path)
    return out_path


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for sc in SCENARIOS:
        plot_network_snapshot(scenario_name=sc, control_enabled=False, step_to_run=150)
        plot_network_snapshot(scenario_name=sc, control_enabled=True, step_to_run=150)
        plot_timeseries(sc)
    plot_comparison_bars()
