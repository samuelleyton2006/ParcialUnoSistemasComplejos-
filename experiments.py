"""
experiments.py
---------------
Ejecuta el diseño experimental pedido en el parcial:

  - 3 escenarios de carga: baja, media, alta
  - 2 condiciones por escenario: sin control / con control
  - N repeticiones por condicion, con semillas fijas y comparables
    (misma semilla i se usa en control=False y control=True, para que
    la unica diferencia entre condiciones sea el mecanismo de control).

Guarda:
  - outputs/runs_summary.csv       -> una fila por corrida (repeticion)
  - outputs/history_<escenario>_<control>.csv -> serie de tiempo de UNA
    corrida representativa (la primera repeticion) por combinacion,
    para graficar la dinamica en el tiempo.
"""

import csv
import os
import statistics

from model import NetworkCongestionModel

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")

# ---------------------------------------------------------------------------
# Definicion de escenarios (justificados en calibrate_scenarios.md / README)
# ---------------------------------------------------------------------------
SCENARIOS = {
    "baja":  {"base_gen_rate": 0.08},
    "media": {"base_gen_rate": 0.25},
    "alta":  {"base_gen_rate": 0.50},
}

FIXED_PARAMS = dict(
    num_nodes=50,
    k=4,
    p_rewire=0.12,
    edge_capacity=1,
    max_queue_size=10,
    threshold_warning=0.5,
    threshold_critical=0.8,
    aimd_decrease=0.5,
    aimd_increase=0.02,
    detour_slack=2,
    n_hotspots=3,
    hotspot_bias=0.55,
)

N_REPETITIONS = 10     # minimo sugerido por el enunciado
N_STEPS = 300           # pasos de simulacion por corrida
BASE_SEED = 1000         # semillas: BASE_SEED + i, i=0..N_REPETITIONS-1


def run_single(scenario_name, control_enabled, seed, n_steps=N_STEPS, keep_history=False):
    params = dict(FIXED_PARAMS)
    params.update(SCENARIOS[scenario_name])
    params["control_enabled"] = control_enabled
    params["seed"] = seed
    model = NetworkCongestionModel(**params)
    model.run(n_steps)
    summary = model.summary()
    summary.update(
        {
            "scenario": scenario_name,
            "control_enabled": control_enabled,
            "seed": seed,
        }
    )
    if keep_history:
        return summary, model.history
    return summary, None


def run_all_experiments(n_repetitions=N_REPETITIONS, n_steps=N_STEPS, verbose=True):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_summaries = []

    for scenario_name in SCENARIOS:
        for control_enabled in (False, True):
            for i in range(n_repetitions):
                seed = BASE_SEED + i
                keep_hist = i == 0  # guardamos la serie de tiempo solo de la 1a repeticion
                summary, history = run_single(
                    scenario_name, control_enabled, seed, n_steps, keep_history=keep_hist
                )
                all_summaries.append(summary)
                if verbose:
                    print(
                        f"[{scenario_name:5s}] control={control_enabled!s:5s} "
                        f"seed={seed} -> delivery_ratio={summary['delivery_ratio']:.3f} "
                        f"prop_cong_nodes={summary['prop_congested_nodes']:.3f} "
                        f"mean_latency={summary['mean_latency']:.2f}"
                    )
                if history is not None:
                    fname = os.path.join(
                        OUTPUT_DIR, f"history_{scenario_name}_control_{control_enabled}.csv"
                    )
                    _write_history_csv(fname, history)

    _write_summary_csv(os.path.join(OUTPUT_DIR, "runs_summary.csv"), all_summaries)
    _write_aggregate_csv(
        os.path.join(OUTPUT_DIR, "runs_aggregate.csv"), all_summaries, n_repetitions
    )
    return all_summaries


def _write_history_csv(path, history):
    keys = list(history.keys())
    rows = zip(*[history[k] for k in keys])
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(keys)
        writer.writerows(rows)


def _write_summary_csv(path, summaries):
    if not summaries:
        return
    keys = list(summaries[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in summaries:
            writer.writerow(row)


def _write_aggregate_csv(path, summaries, n_repetitions):
    """Promedio y desviacion estandar por (escenario, control)."""
    groups = {}
    for s in summaries:
        key = (s["scenario"], s["control_enabled"])
        groups.setdefault(key, []).append(s)

    metric_keys = [
        "delivery_ratio",
        "mean_latency",
        "mean_queue_len",
        "max_queue_len",
        "prop_congested_edges",
        "prop_congested_nodes",
        "dropped",
        "generated",
        "delivered",
        "mean_recovery_time_steps",
        "n_congestion_episodes",
    ]

    rows = []
    for (scenario, control), items in groups.items():
        row = {"scenario": scenario, "control_enabled": control, "n": len(items)}
        for mk in metric_keys:
            vals = [it[mk] for it in items]
            row[f"{mk}_mean"] = statistics.mean(vals)
            row[f"{mk}_std"] = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        rows.append(row)

    if rows:
        keys = list(rows[0].keys())
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)


if __name__ == "__main__":
    run_all_experiments()
    print(f"\nResultados guardados en: {OUTPUT_DIR}")
