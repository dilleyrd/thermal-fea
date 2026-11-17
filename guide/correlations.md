# Correlation reference

!!! info "Generated page"
    This page is generated from `src/thermalfea/convection/correlation_info.py` and `docs/theory.md` §8 by `scripts/build_guide.py`.
    Do not edit it here: change the source and run the script again.

Every convection correlation of the program, with its formula, characteristic length, inputs, validity range and the place in the [theory manual](theory.md) it comes from. The texts are copied from the project documents; nothing on this page is computed.

## Common relations (Theory §8) {#corr-common}

h = Nu · k\_f / L\_c. Fluid properties at the **film temperature** T\_film = (T\_s + T∞)/2
unless the correlation states otherwise. T\_s is the wall temperature of the *previous
nonlinear iteration* (lagged), either local (at each integration point; default) or the
area average over the boundary set (option).

Re = ρ V L/μ, Pr = μ c\_p/k\_f, Ra = g β |T\_s − T∞| L³ Pr ρ²/μ², g = 9.80665 m/s².
For ideal gases β = 1/T\_film; for liquids β comes from the property table.

## Summary

| ID | Situation | Characteristic length | Validity |
|---|---|---|---|
| [`plate_forced_avg`](#corr-plate-forced-avg) | Flat plate, parallel flow, average | plate length | Pr ≥ 0.6, Re ≤ 1e8 |
| [`plate_forced_local`](#corr-plate-forced-local) | Flat plate, local at distance x from leading edge | x | Pr ≥ 0.6 |
| [`cylinder_crossflow`](#corr-cylinder-crossflow) | Cylinder in cross flow (Churchill–Bernstein) | diameter | Re·Pr ≥ 0.2 |
| [`duct_internal`](#corr-duct-internal) | Internal flow, circular or by hydraulic diameter | D\_h | Gnielinski: 0.5 ≤ Pr ≤ 2000, Re ≤ 5e6. Dittus–Boelter: Re ≥ 1e4. (The validity column of the §8 table is empty for this entry; the ranges are those stated in §8.1.) |
| [`vplate_natural`](#corr-vplate-natural) | Vertical plate (Churchill–Chu) | height | all Ra |
| [`inclined_natural`](#corr-inclined-natural) | Plate inclined θ from vertical | length | θ ≤ 60° |
| [`hplate_up_natural`](#corr-hplate-up-natural) | Horizontal, hot face up or cold face down | area/perimeter | 1e4 ≤ Ra ≤ 1e11 |
| [`hplate_down_natural`](#corr-hplate-down-natural) | Horizontal, hot face down or cold face up | area/perimeter | 1e5 ≤ Ra ≤ 1e10 |
| [`hcyl_natural`](#corr-hcyl-natural) | Horizontal cylinder (Churchill–Chu) | diameter | Ra ≤ 1e12 |
| [`power_law`](#corr-power-law) | User form | — | Not stated in the theory document. |

## Correlations

### `plate_forced_avg`: Flat plate, parallel flow, average {#corr-plate-forced-avg}

Formula (copied from the theory document):

```text
Re ≤ 5e5: Nu = 0.664 Re^½ Pr^⅓; else Nu = (0.037 Re^0.8 − 871) Pr^⅓
```

- **Characteristic length L_c:** plate length
- **Inputs:** `length`, `velocity`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** Pr ≥ 0.6, Re ≤ 1e8
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** source not yet recorded; to be confirmed in the release check, task M11.1.

### `plate_forced_local`: Flat plate, local at distance x from leading edge {#corr-plate-forced-local}

Formula (copied from the theory document):

```text
Re_x ≤ 5e5: Nu_x = 0.332 Re_x^½ Pr^⅓; else Nu_x = 0.0296 Re_x^0.8 Pr^⅓
```

- **Characteristic length L_c:** x
- **Inputs:** `x`, `velocity`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** Pr ≥ 0.6
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** source not yet recorded; to be confirmed in the release check, task M11.1.

### `cylinder_crossflow`: Cylinder in cross flow (Churchill–Bernstein) {#corr-cylinder-crossflow}

Formula (copied from the theory document):

```text
Nu = 0.3 + 0.62 Re^½ Pr^⅓ [1+(0.4/Pr)^⅔]^(−¼) [1+(Re/282000)^⅝]^(⅘)
```

- **Characteristic length L_c:** diameter
- **Inputs:** `length`, `velocity`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** Re·Pr ≥ 0.2
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** source not yet recorded; to be confirmed in the release check, task M11.1.

### `duct_internal`: Internal flow, circular or by hydraulic diameter {#corr-duct-internal}

Formula (copied from the theory document):

```text
Re = ṁ D_h /(A μ), D_h = 4A/P_wet. Properties at the bulk fluid temperature.
Laminar (Re ≤ 2300): Nu_lam from the table (constant wall T: circular 3.66, parallel plates both heated 7.54, parallel plates one side insulated 4.86, square 2.98; constant flux: 4.36, 8.23, 5.39, 3.61).
Turbulent (Re ≥ 4000): Gnielinski Nu = (f/8)(Re − 1000) Pr / [1 + 12.7 (f/8)^½ (Pr^⅔ − 1)], f = (0.790 ln Re − 1.64)⁻².
Transition (2300 < Re < 4000): linear interpolation in Re between Nu_lam and Nu_Gnielinski(Re = 4000).
Optional: Dittus–Boelter, Nu = 0.023 Re^0.8 Pr^n, n = 0.4 if wall hotter than fluid, else 0.3.
```

- **Characteristic length L_c:** D\_h
- **Inputs:** `mass_flow`, `area`, `wetted_perimeter`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** The bulk fluid temperature (Theory §8.1).
- **Validity range (as recorded):** Gnielinski: 0.5 ≤ Pr ≤ 2000, Re ≤ 5e6. Dittus–Boelter: Re ≥ 1e4. (The validity column of the §8 table is empty for this entry; the ranges are those stated in §8.1.)
- **Theory section:** [Theory §8](theory.md#sec-8), [Theory §8.1](theory.md#sec-8-1)
- **Literature source:** source not yet recorded; to be confirmed in the release check, task M11.1.
- **Note:** Not offered as a convection boundary condition: internal flow belongs to streams (see [Theory §9](theory.md#sec-9)).

### `vplate_natural`: Vertical plate (Churchill–Chu) {#corr-vplate-natural}

Formula (copied from the theory document):

```text
Nu = {0.825 + 0.387 Ra^(1/6) / [1+(0.492/Pr)^(9/16)]^(8/27)}²
```

- **Characteristic length L_c:** height
- **Inputs:** `length`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** all Ra
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** source not yet recorded; to be confirmed in the release check, task M11.1.

### `inclined_natural`: Plate inclined θ from vertical {#corr-inclined-natural}

Formula (copied from the theory document):

```text
as `vplate_natural` with g → g cos θ
```

- **Characteristic length L_c:** length
- **Inputs:** `length`, `theta_deg`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** θ ≤ 60°
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** source not yet recorded; to be confirmed in the release check, task M11.1.

### `hplate_up_natural`: Horizontal, hot face up or cold face down {#corr-hplate-up-natural}

Formula (copied from the theory document):

```text
Ra ≤ 1e7: Nu = 0.54 Ra^¼; else Nu = 0.15 Ra^⅓
```

- **Characteristic length L_c:** area/perimeter
- **Inputs:** `length`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** 1e4 ≤ Ra ≤ 1e11
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** source not yet recorded; to be confirmed in the release check, task M11.1.

### `hplate_down_natural`: Horizontal, hot face down or cold face up {#corr-hplate-down-natural}

Formula (copied from the theory document):

```text
Nu = 0.27 Ra^¼
```

- **Characteristic length L_c:** area/perimeter
- **Inputs:** `length`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** 1e5 ≤ Ra ≤ 1e10
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** source not yet recorded; to be confirmed in the release check, task M11.1.

### `hcyl_natural`: Horizontal cylinder (Churchill–Chu) {#corr-hcyl-natural}

Formula (copied from the theory document):

```text
Nu = {0.60 + 0.387 Ra^(1/6) / [1+(0.559/Pr)^(9/16)]^(8/27)}²
```

- **Characteristic length L_c:** diameter
- **Inputs:** `length`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** Ra ≤ 1e12
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** source not yet recorded; to be confirmed in the release check, task M11.1.

### `power_law`: User form {#corr-power-law}

Formula (copied from the theory document):

```text
h = C · |T_s − T∞|ⁿ
```

- **Characteristic length L_c:** —
- **Inputs:** `C`, `n`, and the surface and fluid temperatures. No fluid is used.
- **Fluid properties evaluated at:** None: the correlation does not use fluid properties.
- **Validity range (as recorded):** Not stated in the theory document.
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** source not yet recorded; to be confirmed in the release check, task M11.1.

## Validity ranges and warnings

For the horizontal-plate pair, pick "up" or "down" automatically at run time from the sign
of (T\_s − T∞) and the declared face direction. Outside a validity range: still evaluate,
and emit one warning per boundary condition per solve.
`plate_forced_local` needs the leading-edge point and flow direction; x is the distance of
the integration point from the leading edge along the flow direction (minimum x = 1e-6 m).

## Internal duct flow, friction factor and pressure drop (Theory §8.1)

This is the text of §8.1 of the theory document, unchanged. It holds the laminar Nusselt numbers, the turbulent and transition relations, the optional Dittus–Boelter relation, the Churchill friction factor and the pressure drop of a duct.

Re = ṁ D\_h /(A μ), D\_h = 4A/P\_wet. Properties at the bulk fluid temperature.

- Laminar (Re ≤ 2300): Nu\_lam from the table below.
- Turbulent (Re ≥ 4000): Gnielinski
  Nu = (f/8)(Re − 1000) Pr / [1 + 12.7 (f/8)^½ (Pr^⅔ − 1)], f = (0.790 ln Re − 1.64)⁻²
  (valid 0.5 ≤ Pr ≤ 2000, Re ≤ 5e6).
- Transition (2300 &lt; Re &lt; 4000): linear interpolation in Re between Nu\_lam and
  Nu\_Gnielinski(Re = 4000).

| Cross-section | Nu\_lam, constant wall T | Nu\_lam, constant flux |
|---|---|---|
| Circular | 3.66 | 4.36 |
| Parallel plates, both heated | 7.54 | 8.23 |
| Parallel plates, one side insulated | 4.86 | 5.39 |
| Square | 2.98 | 3.61 |

Default is the constant-wall-temperature value. Optional user selection: Dittus–Boelter,
Nu = 0.023 Re^0.8 Pr^n, n = 0.4 if wall hotter than fluid, else 0.3 (Re ≥ 1e4).

Friction factor, all regimes (Churchill 1977), roughness e:
f = 8 [ (8/Re)¹² + (A + B)^(−1.5) ]^(1/12),
A = [2.457 ln( 1 / ((7/Re)^0.9 + 0.27 e/D\_h) )]¹⁶, B = (37530/Re)¹⁶

Pressure drop of a duct of length L with minor-loss coefficient K\_minor:
Δp = (f L/D\_h + K\_minor) · ρ V²/2, V = ṁ/(ρ A).

The stream and network equations that use these relations are in [Theory §9](theory.md#sec-9).

## Literature sources

The theory document names the Churchill–Bernstein, Churchill–Chu, Gnielinski and Dittus–Boelter relations and gives the year of the Churchill friction factor (1977). It gives no reference text or edition for any correlation. For every entry the literature source is: source not yet recorded; to be confirmed in the release check, task M11.1.
