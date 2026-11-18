# Pump closure: what the thermal FEA shows

Figures made from the saved results in `../out/` (nothing was re-solved; the model inputs are the illustrative ones in `closure.json`). Regenerate with `python fig0N_*.py` (needs numpy, scipy, h5py, matplotlib, pandas).

| Figure | What it shows |
|---|---|
| `fig01_model_overview.png` | The 2D axisymmetric model: 9 bodies, 5 film sets, 6 contacts, 13,037 nodes / 6,188 quadratic triangles |
| `fig02_temperature_evolution.png` | Temperature fields at 5, 30, 60, 120, 240, 360 min and steady state, plus the rise still to come at 6 h |
| `fig03_heatup_history.png` | Film heats, flange bore/rim/stud temperatures, and the heat across each contact over 6 h |
| `fig04_steady_heat_flux.png` | Steady heat-flux magnitude and streamlines: where the heat actually goes |
| `fig05_contact_jumps.png` | Temperature jump across the seal land, main seat and barrier foot |
| `fig06_seat_sensitivity.png` | Five steady solves with the main-seat conductance scaled 0.1x to 10x |
| `fig07_verification.png` | Energy balance, mesh refinement, adaptive time step |

## Features worth pointing at

1. **The flange temperature gradient reverses sign.** The bore (r = 340 mm) is cooled by the motor cavity and sits near 51-55 °C almost from the start. The rim (r = 800 mm) first dips to about 39.4 °C (ambient is 30 °C), then rises. Bore minus rim peaks at +13.6 K at 25 min, crosses zero at about 1.5 h, and reaches -39.9 K at 6 h (-44.1 K steady). A one-dimensional or lumped estimate gives one sign; the 2D assembly model shows both.
2. **Heat paths peak at different times and one reverses.** The seated joint peaks near 3.5 kW around 1.2-1.3 h; the stud path peaks near 0.74 kW around 1.7 h. The vertical fit between casing and barrier carries heat barrier to casing for the first hour (down to about -0.9 kW), reverses at about 1.0 h, and ends at +0.81 kW casing to barrier. At steady state the studs carry 13 % of the heat entering the flange (479 W of 3.65 kW).
3. **Contacts are real temperature jumps, not smeared bonds.** At steady state the jump is 1.4-3.4 K across the 3000 W/m²K main seat and up to 5.7 K across the 500 W/m²K seal land. Summing h·ΔT·2πr from the stored nodal temperatures gives 2359 W for the main seat (solver-side value 2345 W) and 131 W for the seal land (138 W); the barrier foot gives 655 W against 694 W because the corner nodes shared with the vertical fit are left out of that check.
4. **The cooling passage is a heat sink.** The highest element flux in the steady case (about 88 kW/m²) is in the barrier, next to the Ø16 mm passage at (r, z) = (461, 77) mm.
5. **Seat conductance moves heat between paths but barely moves temperatures.** Across a 100x range of main-seat conductance the seat heat changes from 1840 to 2431 W (+32 %), while the seal land (+69 % at 0.1x), barrier foot, vertical fit and stud anchor take up the difference. Flange rim temperature changes by 4.5 K (95.3 to 99.8 °C), the bore by 0.1 K. From 3x to 10x the seat heat changes by 1 %: the seat is no longer the limiting resistance.
6. **Six hours is close to, not at, steady state.** At 6 h the rim is 95.0 °C against 99.3 °C steady, and the mean stud 117.4 against 120.2 °C. The largest remaining rise is 4.4 K, in the outer flange.

## Numerical checks visible in the results

- Relative energy imbalance is at most 2.5e-13 over all stored steps.
- Halving the element sizes (13,037 to 46,051 nodes) changes steady bore, rim and mean-stud temperatures by 0.026, 0.008 and 0.069 K, and the hot-film heat by 0.009 %. The `README.md` one level up quotes sheet-5 criteria of 1 K and 2 %.
- Steady hot-film heat of 35.19 kW equals the outflow through M, Cw, J and A (21.35 + 8.99 + 1.48 + 3.38 kW).

## Limits

Ring-average (axisymmetric) results only: no bolt holes, thread roots, nozzles or azimuthal variation. The thermal stress the flange gradient would cause is outside this program (no structural coupling). Peak times above come from 300 s output spacing. The flux and contact-jump figures were computed by me from the stored nodal temperatures (linear gradient per element; nodal jump at duplicated contact nodes), not by the solver. All inputs are illustrative.
