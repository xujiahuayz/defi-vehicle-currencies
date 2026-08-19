# Plot

Plotters reshape processed panels or analysis exhibits for presentation; they do
not read raw data or define a new estimand.

| Owner | Output and consumer |
|---|---|
| `build_vehicle_excess_use_transition.py` | transition figure used by paper/deck |
| `build_within_day_contrasts.py` | within-day role-contrast figure used by paper/deck |
| `build_visual_experiments.py` | named experimental figures used by the deck |
| `build_route_replay.py` | route-replay manifest and deck macros |
| `render_vehicle_dominance_timelapse.py` | 11-second H.264 vehicle-share film and static poster; monthly named-currency shares plus the registered ordered-ultimate-pair decomposition |

Edit the owner, never the generated file. An unconsumed figure is removed
from the live tree.

Render the short vehicle-currency film and its final-state poster with:

```bash
./scripts/run scripts/plot/render_vehicle_dominance_timelapse.py
```

The owner reads `data/processed/endpoint_candidate_choices.parquet` for the
monthly WETH, USDC, USDT, and DAI contest and
`output/exhibits/vehicle_transition_pair_decomposition.jsonl` for the closing
2024-to-2026 ordered-ultimate-pair accounting. It writes the H.264 MP4 plus PDF
and PNG poster files under `output/figures/`.
