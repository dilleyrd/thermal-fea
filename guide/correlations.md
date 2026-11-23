# Correlation reference

!!! info "Generated page"
    This page is generated from `src/thermalfea/convection/correlation_info.py` and `docs/theory.md` §8 by `scripts/build_guide.py`.
    Do not edit it here: change the source and run the script again.

Every convection correlation of the program, with its formula, characteristic length, inputs, validity range and the place in the [theory manual](theory.md) it comes from. The texts are copied from the project documents; nothing on this page is computed.

## Common relations (Theory §8) {#corr-common}

Source of every correlation in §8 and §8.1, unless a row names another: **[I]** Bergman,
Lavine, Incropera and DeWitt, *Fundamentals of Heat and Mass Transfer*, 7th ed., Wiley, 2011.
The equation numbers below are the book's (owner's decision, 2026-11-23).

h = Nu · k\_f / L\_c. Fluid properties at the **film temperature** T\_film = (T\_s + T∞)/2
unless the correlation states otherwise. T\_s is the wall temperature of the *previous
nonlinear iteration* (lagged), either local (at each integration point; default) or the
area average over the boundary set (option).

Re = ρ V L/μ, Pr = μ c\_p/k\_f, Ra = g β |T\_s − T∞| L³ Pr ρ²/μ², g = 9.80665 m/s².
For ideal gases β = 1/T\_film; for liquids β comes from the property table.

## Summary

| ID | Situation | Characteristic length | Validity |
|---|---|---|---|
| [`plate_forced_avg`](#corr-plate-forced-avg) | Flat plate, parallel flow, average | plate length | Pr ≥ 0.6; when Re &gt; 5e5 also Pr ≤ 60 and Re ≤ 1e8 |
| [`plate_forced_local`](#corr-plate-forced-local) | Flat plate, local at distance x from leading edge | x | Pr ≥ 0.6; when Re\_x &gt; 5e5 also Pr ≤ 60 and Re\_x ≤ 1e8 |
| [`cylinder_crossflow`](#corr-cylinder-crossflow) | Cylinder in cross flow (Churchill–Bernstein) | diameter | Re·Pr ≥ 0.2 |
| [`square_corner_crossflow`](#corr-square-corner-crossflow) | Square cylinder, a corner facing the flow, gas | D = diagonal (width across the flow) | 6000 ≤ Re ≤ 60000 |
| [`square_face_crossflow`](#corr-square-face-crossflow) | Square cylinder, a face facing the flow, gas | D = side | 5000 ≤ Re ≤ 60000 |
| [`hexagon_face_crossflow`](#corr-hexagon-face-crossflow) | Hexagonal cylinder, a face facing the flow, gas | D = corner-to-corner width across the flow | 5200 ≤ Re ≤ 105000 |
| [`hexagon_corner_crossflow`](#corr-hexagon-corner-crossflow) | Hexagonal cylinder, a corner facing the flow, gas | D = face-to-face width across the flow | 4500 ≤ Re ≤ 90700 |
| [`plate_front_crossflow`](#corr-plate-front-crossflow) | Thin plate across the flow, upstream face, gas | D = plate height across the flow | 10000 ≤ Re ≤ 50000 |
| [`plate_back_crossflow`](#corr-plate-back-crossflow) | Thin plate across the flow, downstream face, gas | D = plate height across the flow | 7000 ≤ Re ≤ 80000 |
| [`sphere_forced`](#corr-sphere-forced) | Sphere in a free stream (Whitaker) | diameter | 0.71 ≤ Pr ≤ 380, 3.5 ≤ Re ≤ 7.6e4, 1.0 ≤ μ/μ\_s ≤ 3.2 |
| [`duct_internal`](#corr-duct-internal) | Internal flow, circular or by hydraulic diameter | D\_h | Gnielinski: 0.5 ≤ Pr ≤ 2000, 3000 ≤ Re ≤ 5e6. Dittus–Boelter: 0.6 ≤ Pr ≤ 160 and Re ≥ 1e4. (The validity column of the §8 table is empty for this entry; the ranges are those stated in §8.1.) |
| [`vplate_natural`](#corr-vplate-natural) | Vertical plate (Churchill–Chu) | height | all Ra |
| [`vplate_natural_laminar`](#corr-vplate-natural-laminar) | Vertical plate, laminar (Churchill–Chu; slightly more accurate than 9.26 for Ra ≤ 1e9) | height | Ra ≤ 1e9 |
| [`inclined_natural`](#corr-inclined-natural) | Plate inclined θ from vertical | length | 0 ≤ θ ≤ 60°; for the other face [I] makes no recommendation (see below) |
| [`hplate_up_natural`](#corr-hplate-up-natural) | Horizontal, hot face up or cold face down | area/perimeter | 1e4 ≤ Ra ≤ 1e11; when Ra ≤ 1e7 also Pr ≥ 0.7 |
| [`hplate_down_natural`](#corr-hplate-down-natural) | Horizontal, hot face down or cold face up | area/perimeter | 1e4 ≤ Ra ≤ 1e9, Pr ≥ 0.7 |
| [`hcyl_natural`](#corr-hcyl-natural) | Horizontal cylinder (Churchill–Chu) | diameter | Ra ≤ 1e12 |
| [`sphere_natural`](#corr-sphere-natural) | Sphere (Churchill) | diameter | Pr ≥ 0.7, Ra ≤ 1e11 |
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
- **Validity range (as recorded):** Pr ≥ 0.6; when Re &gt; 5e5 also Pr ≤ 60 and Re ≤ 1e8
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 7.30, 7.38.

### `plate_forced_local`: Flat plate, local at distance x from leading edge {#corr-plate-forced-local}

Formula (copied from the theory document):

```text
Re_x ≤ 5e5: Nu_x = 0.332 Re_x^½ Pr^⅓; else Nu_x = 0.0296 Re_x^0.8 Pr^⅓
```

- **Characteristic length L_c:** x
- **Inputs:** `x`, `velocity`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** Pr ≥ 0.6; when Re\_x &gt; 5e5 also Pr ≤ 60 and Re\_x ≤ 1e8
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 7.23, 7.36.

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
- **Literature source:** Incropera 7th ed. Eq. 7.54.

### `square_corner_crossflow`: Square cylinder, a corner facing the flow, gas {#corr-square-corner-crossflow}

Formula (copied from the theory document):

```text
Nu = 0.304 Re^0.59 Pr^⅓
```

- **Characteristic length L_c:** D = diagonal (width across the flow)
- **Inputs:** `length`, `velocity`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** 6000 ≤ Re ≤ 60000
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 7.52, Table 7.3.

### `square_face_crossflow`: Square cylinder, a face facing the flow, gas {#corr-square-face-crossflow}

Formula (copied from the theory document):

```text
Nu = 0.158 Re^0.66 Pr^⅓
```

- **Characteristic length L_c:** D = side
- **Inputs:** `length`, `velocity`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** 5000 ≤ Re ≤ 60000
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 7.52, Table 7.3.

### `hexagon_face_crossflow`: Hexagonal cylinder, a face facing the flow, gas {#corr-hexagon-face-crossflow}

Formula (copied from the theory document):

```text
Re ≤ 20400: Nu = 0.164 Re^0.638 Pr^⅓; else Nu = 0.039 Re^0.78 Pr^⅓
```

- **Characteristic length L_c:** D = corner-to-corner width across the flow
- **Inputs:** `length`, `velocity`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** 5200 ≤ Re ≤ 105000
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 7.52, Table 7.3.

### `hexagon_corner_crossflow`: Hexagonal cylinder, a corner facing the flow, gas {#corr-hexagon-corner-crossflow}

Formula (copied from the theory document):

```text
Nu = 0.150 Re^0.638 Pr^⅓
```

- **Characteristic length L_c:** D = face-to-face width across the flow
- **Inputs:** `length`, `velocity`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** 4500 ≤ Re ≤ 90700
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 7.52, Table 7.3.

### `plate_front_crossflow`: Thin plate across the flow, upstream face, gas {#corr-plate-front-crossflow}

Formula (copied from the theory document):

```text
Nu = 0.667 Re^0.500 Pr^⅓
```

- **Characteristic length L_c:** D = plate height across the flow
- **Inputs:** `length`, `velocity`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** 10000 ≤ Re ≤ 50000
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 7.52, Table 7.3.

### `plate_back_crossflow`: Thin plate across the flow, downstream face, gas {#corr-plate-back-crossflow}

Formula (copied from the theory document):

```text
Nu = 0.191 Re^0.667 Pr^⅓
```

- **Characteristic length L_c:** D = plate height across the flow
- **Inputs:** `length`, `velocity`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** 7000 ≤ Re ≤ 80000
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 7.52, Table 7.3.

### `sphere_forced`: Sphere in a free stream (Whitaker) {#corr-sphere-forced}

Formula (copied from the theory document):

```text
Nu = 2 + (0.4 Re^½ + 0.06 Re^⅔) Pr^0.4 (μ/μ_s)^¼. **All properties at T∞**, except μ_s at T_s
```

- **Characteristic length L_c:** diameter
- **Inputs:** `length`, `velocity`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** All fluid properties at T∞, except μ\_s at T\_s.
- **Validity range (as recorded):** 0.71 ≤ Pr ≤ 380, 3.5 ≤ Re ≤ 7.6e4, 1.0 ≤ μ/μ\_s ≤ 3.2
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 7.56.

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
- **Validity range (as recorded):** Gnielinski: 0.5 ≤ Pr ≤ 2000, 3000 ≤ Re ≤ 5e6. Dittus–Boelter: 0.6 ≤ Pr ≤ 160 and Re ≥ 1e4. (The validity column of the §8 table is empty for this entry; the ranges are those stated in §8.1.)
- **Theory section:** [Theory §8.1](theory.md#sec-8-1)
- **Literature source:** Incropera 7th ed. Eq. 8.62 (f from 8.21), Eq. 8.60, Tables 8.1, 8.2.
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
- **Literature source:** Incropera 7th ed. Eq. 9.26.

### `vplate_natural_laminar`: Vertical plate, laminar (Churchill–Chu; slightly more accurate than 9.26 for Ra ≤ 1e9) {#corr-vplate-natural-laminar}

Formula (copied from the theory document):

```text
Nu = 0.68 + 0.670 Ra^¼ / [1+(0.492/Pr)^(9/16)]^(4/9)
```

- **Characteristic length L_c:** height
- **Inputs:** `length`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** Ra ≤ 1e9
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 9.27.

### `inclined_natural`: Plate inclined θ from vertical {#corr-inclined-natural}

Formula (copied from the theory document):

```text
as `vplate_natural` with g → g cos θ
```

- **Characteristic length L_c:** length
- **Inputs:** `length`, `theta_deg`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** 0 ≤ θ ≤ 60°; for the other face [I] makes no recommendation (see below)
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 9.26, Sec. 9.6.2.

### `hplate_up_natural`: Horizontal, hot face up or cold face down {#corr-hplate-up-natural}

Formula (copied from the theory document):

```text
Ra ≤ 1e7: Nu = 0.54 Ra^¼; else Nu = 0.15 Ra^⅓
```

- **Characteristic length L_c:** area/perimeter
- **Inputs:** `length`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** 1e4 ≤ Ra ≤ 1e11; when Ra ≤ 1e7 also Pr ≥ 0.7
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 9.30, 9.31.

### `hplate_down_natural`: Horizontal, hot face down or cold face up {#corr-hplate-down-natural}

Formula (copied from the theory document):

```text
Nu = 0.52 Ra^(1/5)
```

- **Characteristic length L_c:** area/perimeter
- **Inputs:** `length`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** 1e4 ≤ Ra ≤ 1e9, Pr ≥ 0.7
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 9.32.

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
- **Literature source:** Incropera 7th ed. Eq. 9.34.

### `sphere_natural`: Sphere (Churchill) {#corr-sphere-natural}

Formula (copied from the theory document):

```text
Nu = 2 + 0.589 Ra^¼ / [1+(0.469/Pr)^(9/16)]^(4/9)
```

- **Characteristic length L_c:** diameter
- **Inputs:** `length`, the surface and fluid temperatures, and the fluid (the keyword inputs of `thermalfea.api.htc`).
- **Fluid properties evaluated at:** Fluid properties at the film temperature T\_film = (T\_s + T∞)/2.
- **Validity range (as recorded):** Pr ≥ 0.7, Ra ≤ 1e11
- **Theory section:** [Theory §8](theory.md#sec-8)
- **Literature source:** Incropera 7th ed. Eq. 9.35.

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
- **Literature source:** user form; not from the reference text.

## Validity ranges and warnings

For the horizontal-plate pair, pick "up" or "down" automatically at run time from the sign
of (T\_s − T∞) and the declared face direction. Outside a validity range: still evaluate,
and emit one warning per boundary condition per solve.
`plate_forced_local` needs the leading-edge point and flow direction; x is the distance of
the integration point from the leading edge along the flow direction (minimum x = 1e-6 m).

`inclined_natural`: when the face direction is declared, a face for which [I] makes no
recommendation counts as outside the validity range: the top face (`up`) of a hot plate
(T\_s &gt; T∞), or the bottom face (`down`) of a cold plate. When no face direction is declared,
this is not checked.

**Characteristic lengths in a 2D model.**

- **Horizontal plates.** [I] defines L = A\_s/P (Eq. 9.29). In a planar model a horizontal
  face is a strip of unit depth, so A\_s/P is half the strip's width; [I] Example 9.3 uses w/2
  in the same way. In an axisymmetric model, a horizontal ring from r\_i to r\_o gives
  A\_s/P = (r\_o − r\_i)/2. Either way, the automatic L\_c of `hplate_up_natural` and
  `hplate_down_natural` is **half the total length of the selection**. This settles Q17.2.
- **Other correlations.** For the other plate correlations and the vertical channels
  (channel height), the automatic L\_c is the total length of the selection.
- **Diameters.** The cylinder, sphere and non-circular cylinder correlations need L\_c (the
  diameter or D) given.
- **An explicit L\_c always overrides the automatic one.**

**Extra inputs** (Data §8 `params`):

- **Vertical channels:** `S`, the plate spacing [m].
- **`slot_jet`:** `W`, the slot width [m]; `H`, the nozzle-to-surface distance [m]; `x_r`,
  the half-width of the region averaged over [m]. The default `x_r` is half the total length
  of the selection.
- **`round_jet`:** `D`, the nozzle diameter [m]; `H` [m]; `r_r`, the radius of the region
  averaged over [m]. In an axisymmetric model the default `r_r` is the largest radial
  coordinate of the selection; a planar model must give `r_r`.
- **The jets take their L\_c from these inputs**, so a given L\_c is refused.

## Internal duct flow, friction factor and pressure drop (Theory §8.1)

This is the text of §8.1 of the theory document, unchanged. It holds the laminar Nusselt numbers, the turbulent and transition relations, the optional Dittus–Boelter relation, the Churchill friction factor and the pressure drop of a duct.

Re = ṁ D\_h /(A μ), D\_h = 4A/P\_wet. Properties at the bulk fluid temperature.

- Laminar (Re ≤ 2300): Nu\_lam from the tables below ([I] Tables 8.1 and 8.2).
- Turbulent (Re ≥ 4000): Gnielinski ([I] 8.62, with f from 8.21)
  Nu = (f/8)(Re − 1000) Pr / [1 + 12.7 (f/8)^½ (Pr^⅔ − 1)], f = (0.790 ln Re − 1.64)⁻²
  (valid 0.5 ≤ Pr ≤ 2000, 3000 ≤ Re ≤ 5e6).
- Transition (2300 &lt; Re &lt; 4000): linear interpolation in Re between Nu\_lam and
  Nu\_Gnielinski(Re = 4000). [I] gives no transition correlation; this rule is the program's.

| Cross-section (`cross_section`) | Nu\_lam, constant wall T | Nu\_lam, constant flux |
|---|---|---|
| Circular (`circular`) | 3.66 | 4.36 |
| Parallel plates, both heated (`parallel_plates`) | 7.54 | 8.23 |
| Parallel plates, one side insulated (`parallel_plates_one_side`) | 4.86 | 5.39 |
| Square (`square`) | 2.98 | 3.61 |
| Rectangle, sides b/a = 1.43 (`rectangle_1_43`) | 3.08 | 3.73 |
| Rectangle, b/a = 2.0 (`rectangle_2`) | 3.39 | 4.12 |
| Rectangle, b/a = 3.0 (`rectangle_3`) | 3.96 | 4.79 |
| Rectangle, b/a = 4.0 (`rectangle_4`) | 4.44 | 5.33 |
| Rectangle, b/a = 8.0 (`rectangle_8`) | 5.60 | 6.49 |
| Triangle (`triangle`) | 2.49 | 3.11 |

**Concentric annulus**, one surface at constant temperature and the other insulated
([I] Table 8.2). D\_h = D\_o − D\_i. The stream gives `diameter_ratio` = D\_i/D\_o. Nu is
linearly interpolated in D\_i/D\_o between the rows; the program, not [I], sets that rule.

| D\_i/D\_o | Nu\_i: inner surface heated (`annulus_inner`) | Nu\_o: outer surface heated (`annulus_outer`) |
|---|---|---|
| 0 | — | 3.66 |
| 0.05 | 17.46 | 4.06 |
| 0.10 | 11.56 | 4.11 |
| 0.25 | 7.37 | 4.23 |
| 0.50 | 5.74 | 4.43 |
| 1.00 | 4.86 | 4.86 |

- `annulus_inner` needs 0.05 ≤ D\_i/D\_o ≤ 1. `annulus_outer` needs 0 ≤ D\_i/D\_o ≤ 1.
- [I] gives only constant-temperature values for the annulus, so a constant-flux request is
  refused.

Default is the constant-wall-temperature value. Optional user selections, each replacing
Gnielinski as the turbulent formula (the laminar value and the transition rule are kept):

- **Dittus–Boelter** ([I] 8.60): Nu = 0.023 Re^0.8 Pr^n. n = 0.4 if the wall is hotter
  than the fluid, else 0.3. Valid for 0.6 ≤ Pr ≤ 160 and Re ≥ 1e4.
- **Sieder–Tate** ([I] 8.61): Nu = 0.027 Re^(4/5) Pr^(1/3) (μ/μ\_s)^0.14. μ\_s is taken at the
  cell's mean wall temperature T̄\_w; the other properties at the bulk temperature. Valid for
  0.7 ≤ Pr ≤ 16700 and Re ≥ 1e4. [I] recommends it for flows with large property variation,
  such as oils.

Friction factor, all regimes (Churchill 1977, not in [I]), roughness e:
f = 8 [ (8/Re)¹² + (A + B)^(−1.5) ]^(1/12),
A = [2.457 ln( 1 / ((7/Re)^0.9 + 0.27 e/D\_h) )]¹⁶, B = (37530/Re)¹⁶

Pressure drop of a duct of length L with minor-loss coefficient K\_minor:
Δp = (f L/D\_h + K\_minor) · ρ V²/2, V = ṁ/(ρ A).

### §8.2 Correlations of [I] that are not used {#sec-8-2}

Recorded so that no task adds them without a decision:

- **Circular cylinder, Hilpert ([I] 7.52, Table 7.2) and Zukauskas (7.53).** These cover the
  same case as Churchill–Bernstein (7.54), which is kept. **Horizontal cylinder, Morgan
  (9.33, Table 9.1)** is not used either; Churchill–Chu (9.34) is kept.
- **Liquid-metal forms**: the flat plate (7.32) and fully developed tube flow (8.64, 8.65).
  Mercury is the only liquid metal built in. Other correlations used outside their Pr range
  warn as usual.
- **Flat plate with uniform surface flux (7.45–7.48) or an unheated starting length
  (7.60–7.64).** The surface conditions these assume are not known to a load.
- **Tube banks (7.58, 7.59), packed beds (7.81), falling drops (7.57), and arrays of jets
  (7.73, 7.77).** These need array geometry and a mean fluid temperature that a single-surface
  load does not have.
- **Laminar entry lengths (8.57, 8.58).** These give a Nusselt number averaged from the inlet
  to x, but the stream needs a local value in each cell.
- **Colebrook friction (8.20) and laminar f·Re of non-circular sections (Table 8.1).**
  Churchill 1977 is kept; it applies to circular ducts and to D\_h. Using Table 8.1's f·Re
  would need a rule for joining it to the turbulent branch, which [I] does not give
  (OPEN\_QUESTIONS Q30).
- **Isoflux vertical channels (9.46), inclined channels (9.47), and the isolated-plate
  optimum spacings (Table 9.3).** The isothermal form 9.45 is used.
- **Enclosures: rectangular cavities, concentric cylinders and spheres (9.49–9.63).** They
  couple two surfaces across a cavity, and a convection load sees only one ambient
  temperature (Q30).
- **Mixed free and forced convection (9.64).** This needs two correlations in one load
  (Q30).
- **Boiling and condensation (chapter 10).** The fluids here do not change phase.

The stream and network equations that use these relations are in [Theory §9](theory.md#sec-9).

## Literature sources

Every correlation except the user power law comes from Bergman, Lavine, Incropera and DeWitt, *Fundamentals of Heat and Mass Transfer*, 7th ed., Wiley, 2011; each entry above gives its equation numbers. The Churchill friction factor (1977) is not in that book. The correlations of the book that the program does not use, and why, are listed in [Theory §8.2](theory.md#sec-8-2).
