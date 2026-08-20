# Plot

Plotters reshape processed panels or analysis exhibits for presentation; they do
not read raw data or define a new estimand.

| Owner | Output and consumer |
|---|---|
| `build_vehicle_excess_use_transition.py` | transition figure used by paper/deck |
| `build_bridge_adoption_capital_path.py` | stablecoin and WETH bridge-capital paths around first use of the supported stablecoin |
| `build_within_day_contrasts.py` | within-day role-contrast figure used by paper/deck |
| `build_visual_experiments.py` | named experimental figures used by the deck |
| `build_route_replay.py` | route-replay manifest and deck macros |
| `render_vehicle_dominance_timelapse.py` | 18-second H.264 vehicle contest and final-month keyframe; route-count share, supported-value share, and active ultimate-pair breadth evolve from 2020 to 2026 |

Edit the owner, never the generated file. An unconsumed figure is removed
from the live tree.

Render the vehicle-currency film and its final-month keyframe with:

```bash
./scripts/run scripts/plot/render_vehicle_dominance_timelapse.py
```

The owner reads `data/processed/endpoint_candidate_choices.parquet` for the
monthly WETH, USDC, USDT, and DAI contest. Each frame places route-count share
on the horizontal axis and strict supported-value share on the vertical axis;
bubble area records active ordered ultimate pairs, and fading trails retain only
the prior six months. The final frame therefore cannot reproduce the full
history. The owner writes the H.264 MP4 plus PDF and PNG keyframes under
`output/figures/`.
