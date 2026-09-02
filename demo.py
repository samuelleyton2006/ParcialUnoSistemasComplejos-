import argparse
import os

from model import NetworkCongestionModel
from experiments import SCENARIOS, FIXED_PARAMS, OUTPUT_DIR
from visualize import plot_network_snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()), default="alta")
    parser.add_argument("--control", action="store_true", help="activa el mecanismo de control")
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--seed", type=int, default=2024)
    args = parser.parse_args()

    params = dict(FIXED_PARAMS)
    params.update(SCENARIOS[args.scenario])
    params["control_enabled"] = args.control
    params["seed"] = args.seed

    print(f"Ejecutando escenario '{args.scenario}' | control={args.control} | "
          f"seed={args.seed} | pasos={args.steps}")
    print(f"Parametros: {params}\n")

    model = NetworkCongestionModel(**params)
    model.run(args.steps)
    summary = model.summary()

    print("=== Metricas obligatorias ===")
    for k, v in summary.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    plot_network_snapshot(
        scenario_name=args.scenario,
        control_enabled=args.control,
        step_to_run=args.steps,
        seed=args.seed,
        tag=f"demo_{args.scenario}_control_{args.control}",
    )


if __name__ == "__main__":
    main()
