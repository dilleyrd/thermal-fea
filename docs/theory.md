# Theory reference

Every equation the code implements. Implement these exactly; do not re-derive.
Symbols: T temperature [K], t time [s], k conductivity [W/m·K], ρ density [kg/m³],
c specific heat [J/kg·K], Q volumetric heat generation [W/m³], q heat flux [W/m²],
h heat-transfer coefficient [W/m²·K], ε emissivity, σ = 5.670374419e-8 W/m²·K⁴.

## §1 Governing equation and weak form

ρc ∂T/∂t = ∇·(D ∇T) + Q in the domain, with D the 2×2 conductivity matrix.

Boundary conditions on the boundary Γ (n = outward normal, q_n = −n·D∇T = heat leaving):
- Fixed temperature: T = T̄
- Heat flux into the body: −q_n = q̄
- Convection: q_n = h (T − T∞)
- Radiation to ambient: q_n = ε σ (T⁴ − T∞⁴)

Discretised with T ≈ N(ξ,η)·T_e the semi-discrete system is

  **C Ṫ + K T = F**

All integrals carry the **geometry factor g**:
- planar: g = thickness of the region [m] (default 1)
- axisymmetric: g = 2π r, with r = the x coordinate at the integration point

so that every assembled force term is in watts.

## §2 Element matrices

For each element, with B = the 2×n matrix of ∂N/∂x, ∂N/∂y and |J| the Jacobian determinant:

- Conduction: K_e = Σ_gp Bᵀ D B · g · |J| · w
- Capacitance: C_e = Σ_gp ρc · NᵀN · g · |J| · w
- Heat generation: F_e = Σ_gp Q · Nᵀ · g · |J| · w

Orthotropic D with principal conductivities k1, k2 and material angle θ (radians,
counter-clockwise from x): D = R diag(k1, k2) Rᵀ, R = [[cosθ, −sinθ],[sinθ, cosθ]].
Isotropic: D = k I.

Temperature-dependent properties are evaluated **at each integration point** from the
interpolated temperature N·T_e.

### Boundary (edge) element terms
For an edge with shape functions N (1D), |J_s| = ds/dξ:

- Flux: F_e = Σ_gp q̄ · Nᵀ · g · |J_s| · w
- Convection: K_e = Σ_gp h · NᵀN · g · |J_s| · w ;  F_e = Σ_gp h T∞ · Nᵀ · g · |J_s| · w
- Total heat flow P [W] applied to a boundary set: convert to uniform flux
  q̄ = P / A, where A = Σ over the set of ∫ g ds.
- Total power P [W] applied to a region: Q = P / V, V = ∫ g dA.

## §3 Shape functions and quadrature

Node ordering is **gmsh ordering**: corners counter-clockwise, then mid-side nodes in the
order (0-1, 1-2, 2-0) for triangles and (0-1, 1-2, 2-3, 3-0) for quads.

**T3** (ξ,η ∈ unit triangle): N = [1−ξ−η, ξ, η]

**T6** with L1 = 1−ξ−η, L2 = ξ, L3 = η:
N = [L1(2L1−1), L2(2L2−1), L3(2L3−1), 4L1L2, 4L2L3, 4L3L1]

**Q4** (ξ,η ∈ [−1,1]), corner signs (ξi,ηi) = (−1,−1),(1,−1),(1,1),(−1,1):
N_i = ¼(1+ξξi)(1+ηηi)

**Q8** (serendipity): corners N_i = ¼(1+ξξi)(1+ηηi)(ξξi+ηηi−1);
mid-sides with ξi = 0: N_i = ½(1−ξ²)(1+ηηi); with ηi = 0: N_i = ½(1+ξξi)(1−η²).
Mid-side positions: (0,−1),(1,0),(0,1),(−1,0).

**L2** edge (ξ ∈ [−1,1]): N = [½(1−ξ), ½(1+ξ)]

**L3** edge, gmsh order (end, end, middle): N = [½ξ(ξ−1), ½ξ(ξ+1), 1−ξ²]

Quadrature (weights sum to the reference area: ½ for triangles, 4 for quads, 2 for lines):

| Element | Rule |
|---|---|
| T3 | 3-point: (1/6,1/6), (2/3,1/6), (1/6,2/3), each w = 1/6 |
| T6 | 6-point degree-4 rule (Dunavant) |
| Q4 | 2×2 Gauss |
| Q8 | 3×3 Gauss |
| L2 | 2-point Gauss |
| L3 | 3-point Gauss |

Dunavant degree 4, in area coordinates, weights given for reference area ½:
- a = 0.445948490915965, b = 0.108103018168070, w = 0.223381589678011 / 2;
  points (a,a),(a,b),(b,a) as (ξ,η)
- a = 0.091576213509771, b = 0.816847572980459, w = 0.109951743655322 / 2;
  points (a,a),(a,b),(b,a)

Use the same rule for K, C and F of an element type (keeps the code simple and is exact or
better for all terms on straight-sided elements).

### Lumped capacitance (option)
- T3, Q4: row-sum, C_ii = Σ_j C_ij.
- T6, Q8: HRZ lumping, C_ii = C_ii(consistent) · (Σ_ij C_ij) / (Σ_k C_kk).
  Never use row-sum for quadratic elements (gives zero or negative corner terms).

## §4 Fixed temperatures

Partition DOFs into free (f) and prescribed (p). Solve
K_ff T_f = F_f − K_fp T̄_p. Never use the penalty method.
Reaction heat flow at prescribed nodes (positive = heat entering the body through the
constraint) for the transient system:

  R_p = (C Ṫ + K T − F)_p

## §5 Nonlinear steady solution

Residual at free DOFs: **r(T) = F(T) − K(T) T** (K includes convection and radiation
tangent-free parts; F includes all load vectors). Radiation to ambient contributes to r

  r_rad = −Σ_gp ε σ ((N·T)⁴ − T∞⁴) Nᵀ g |J_s| w

and to the tangent

  K_rad = Σ_gp 4 ε σ (N·T)³ NᵀN g |J_s| w

Iteration (modified Newton — property derivatives dk/dT, dh/dT are deliberately omitted
from the tangent):

1. Assemble K(Tⁱ), F(Tⁱ), K_rad(Tⁱ), r(Tⁱ) with properties and coefficients at Tⁱ.
2. Solve (K + K_rad)_ff ΔT_f = r_f.
3. Line search: s = 1; while ‖r(Tⁱ + sΔT)‖ > (1 − 1e-4·s)‖r(Tⁱ)‖ and s > 1/32: s ← s/2.
4. Tⁱ⁺¹ = Tⁱ + sΔT.
5. Converged when ‖r_f‖₂ ≤ rtol · F_ref **and** ‖sΔT‖∞ ≤ ttol.
   F_ref = max(‖F‖₂, ‖K T‖₂, 1e-12). Defaults rtol = 1e-6, ttol = 1e-4 K, max 30 iterations.
   Round-off floor: the residual test also passes when
   ‖r_f‖₂ ≤ N ε (‖(|K| |T|)_f‖₂ + ‖F_f‖₂ + ‖r_extra,f‖₂), with N = 100 and ε the machine
   precision (2.2e-16); ‖sΔT‖∞ ≤ ttol is still required. |K| and |T| are the element-wise
   absolute values, the subscript f keeps the free rows, and r_extra is the part of r that
   is not F − K T (for example r_rad). At equilibrium F and K T cancel and F_ref falls to
   round-off; the floor then accepts a residual at the round-off level of the sums that
   form it (owner, Q29.1 D1).
6. Not converged after the limit → raise `ConvergenceError` (steady) or cut the step (transient).

A problem is **linear** when no property, coefficient or load depends on T and there is no
radiation. Detect this once; a linear problem takes exactly one solve with no iteration.

If any temperature becomes ≤ 0 K during iteration, treat the iteration as failed
(halve the line-search step; if that fails, raise).

## §6 Transient solution (θ-method)

With g(T, t) = F(T, t) − K(T) T − (radiation term) the "heat-flow imbalance", the step from
t_n to t_{n+1} = t_n + Δt solves for T_{n+1}:

  **R(T_{n+1}) = C(T_θ) (T_{n+1} − T_n)/Δt − θ g(T_{n+1}, t_{n+1}) − (1−θ) g(T_n, t_n) = 0**

with T_θ = θ T_{n+1} + (1−θ) T_n used only to evaluate ρc.
Tangent: **A = C/Δt + θ (K + K_rad)** evaluated at the current iterate.
Newton update: A_ff ΔT_f = −R_f. Line search and convergence test as in §5, with
F_ref = max(‖C(T_{n+1}−T_n)/Δt‖₂, ‖F‖₂, ‖K T‖₂, 1e-12). The round-off floor of §5 applies
unchanged, with K, F and r_extra assembled at the iterate T_{n+1}.

- θ = 1 backward Euler (**default**; unconditionally stable, no oscillation)
- θ = 2/3 Galerkin
- θ = 1/2 Crank–Nicolson (second order; may oscillate after a thermal shock)

g(T_n, t_n) is stored from the end of the previous step, not recomputed. At a step where a
prescribed temperature or a load jumps discontinuously, use θ = 1 for that one step.

Prescribed temperatures: set T_{n+1,p} = T̄(t_{n+1}) before the first iteration.

Linear case: A is constant while Δt is constant — factorise once and reuse (`splu` object
cached, keyed on Δt).

### §6.1 Automatic time stepping

After a converged step compute the predictor T_pred = T_n + (Δt/Δt_prev)(T_n − T_{n−1})
(for the first step skip the error test) and the error

  e = ‖T_{n+1} − T_pred‖∞ / max(T_range, 1 K),  T_range = max(T) − min(T) over the model

- If e > 4·tol: reject the step, Δt ← Δt/2, redo.
- Otherwise accept and set Δt_next = Δt · clip(0.9 √(tol/e), 0.5, 2.0).
- Default tol = 0.02. Clamp to [Δt_min, Δt_max].
- Newton failure: Δt ← Δt/4, redo. If Δt < Δt_min: raise `ConvergenceError`.
- Always shorten a step so that it lands exactly on the next **mandatory time**: every
  requested output time, every breakpoint of every load table, and the end time.
- Also limit the step so the largest nodal change ≤ `max_dT_per_step` if the user set it.

Suggested initial step (shown in the GUI): Δt₀ = h_min² / (4 α_max), α = k/(ρc),
h_min = smallest element edge length.

Oscillation warning: if consistent capacitance is used and Δt < h² ρc /(6k) for more than
5% of elements, log a warning recommending lumped capacitance or a finer mesh.

## §7 Recovered quantities

- Gradient at any element point: ∇T = B T_e. Flux q = −D ∇T.
- Nodal flux: evaluate q at each element's own nodes (B at the node's local coordinates),
  then average the contributions of all elements sharing the node **that belong to the same
  region**. A node on a material interface therefore has one flux value per region.
- Element flux: value at the element centroid.
- Heat flow through a boundary set [W] (positive out of the body):
  - convection set: Σ_gp h (T − T∞) g |J_s| w
  - radiation set: Σ_gp εσ(T⁴ − T∞⁴) g |J_s| w
  - flux set: −Σ_gp q̄ g |J_s| w
  - fixed-temperature set: −Σ R_p over its nodes (§4)
- Stored energy rate: Ė = Σ (C Ṫ), with Ṫ = (T_{n+1} − T_n)/Δt.
- **Energy balance:** (generation + heat in through all boundaries) − Ė = imbalance.
  Report imbalance / max(|terms|).

## §8 Convection from correlations

Source of every correlation in §8 and §8.1, unless a row names another: **[I]** Bergman,
Lavine, Incropera and DeWitt, *Fundamentals of Heat and Mass Transfer*, 7th ed., Wiley, 2011.
The equation numbers below are the book's (owner's decision, 2026-11-23).

h = Nu · k_f / L_c. Fluid properties at the **film temperature** T_film = (T_s + T∞)/2
unless the correlation states otherwise. T_s is the wall temperature of the *previous
nonlinear iteration* (lagged), either local (at each integration point; default) or the
area average over the boundary set (option).

Re = ρ V L/μ, Pr = μ c_p/k_f, Ra = g β |T_s − T∞| L³ Pr ρ²/μ², g = 9.80665 m/s².
For ideal gases β = 1/T_film; for liquids β comes from the property table.

| ID | Situation | Formula | L_c | Validity | [I] |
|---|---|---|---|---|---|
| `plate_forced_avg` | Flat plate, parallel flow, average | Re ≤ 5e5: Nu = 0.664 Re^½ Pr^⅓; else Nu = (0.037 Re^0.8 − 871) Pr^⅓ | plate length | Pr ≥ 0.6; when Re > 5e5 also Pr ≤ 60 and Re ≤ 1e8 | 7.30, 7.38 |
| `plate_forced_local` | Flat plate, local at distance x from leading edge | Re_x ≤ 5e5: Nu_x = 0.332 Re_x^½ Pr^⅓; else Nu_x = 0.0296 Re_x^0.8 Pr^⅓ | x | Pr ≥ 0.6; when Re_x > 5e5 also Pr ≤ 60 and Re_x ≤ 1e8 | 7.23, 7.36 |
| `cylinder_crossflow` | Cylinder in cross flow (Churchill–Bernstein) | Nu = 0.3 + 0.62 Re^½ Pr^⅓ [1+(0.4/Pr)^⅔]^(−¼) [1+(Re/282000)^⅝]^(⅘) | diameter | Re·Pr ≥ 0.2 | 7.54 |
| `square_corner_crossflow` | Square cylinder, a corner facing the flow, gas | Nu = 0.304 Re^0.59 Pr^⅓ | D = diagonal (width across the flow) | 6000 ≤ Re ≤ 60000 | 7.52, Table 7.3 |
| `square_face_crossflow` | Square cylinder, a face facing the flow, gas | Nu = 0.158 Re^0.66 Pr^⅓ | D = side | 5000 ≤ Re ≤ 60000 | 7.52, Table 7.3 |
| `hexagon_face_crossflow` | Hexagonal cylinder, a face facing the flow, gas | Re ≤ 20400: Nu = 0.164 Re^0.638 Pr^⅓; else Nu = 0.039 Re^0.78 Pr^⅓ | D = corner-to-corner width across the flow | 5200 ≤ Re ≤ 105000 | 7.52, Table 7.3 |
| `hexagon_corner_crossflow` | Hexagonal cylinder, a corner facing the flow, gas | Nu = 0.150 Re^0.638 Pr^⅓ | D = face-to-face width across the flow | 4500 ≤ Re ≤ 90700 | 7.52, Table 7.3 |
| `plate_front_crossflow` | Thin plate across the flow, upstream face, gas | Nu = 0.667 Re^0.500 Pr^⅓ | D = plate height across the flow | 10000 ≤ Re ≤ 50000 | 7.52, Table 7.3 |
| `plate_back_crossflow` | Thin plate across the flow, downstream face, gas | Nu = 0.191 Re^0.667 Pr^⅓ | D = plate height across the flow | 7000 ≤ Re ≤ 80000 | 7.52, Table 7.3 |
| `sphere_forced` | Sphere in a free stream (Whitaker) | Nu = 2 + (0.4 Re^½ + 0.06 Re^⅔) Pr^0.4 (μ/μ_s)^¼. **All properties at T∞**, except μ_s at T_s | diameter | 0.71 ≤ Pr ≤ 380, 3.5 ≤ Re ≤ 7.6e4, 1.0 ≤ μ/μ_s ≤ 3.2 | 7.56 |
| `slot_jet` | Single slot nozzle impinging on the surface, average over \|x\| ≤ x_r from the jet's centre line (Martin) | Nu / Pr^0.42 = 3.06 / (0.5/A_r + H/W + 2.78) · Re^m, m = 0.695 − [1/(4 A_r) + (H/(2W))^1.33 + 3.06]^(−1), A_r = W/(2 x_r); Re = V 2W/ν with V the jet exit velocity | 2W | 3000 ≤ Re ≤ 9e4, 2 ≤ H/W ≤ 10, 0.025 ≤ A_r ≤ 0.125 | 7.75, 7.76 |
| `round_jet` | Single round nozzle impinging on the surface, average over r ≤ r_r from the jet's axis (Martin) | Nu / Pr^0.42 = G · 2 Re^½ (1 + 0.005 Re^0.55)^½, G = 2 A_r^½ (1 − 2.2 A_r^½) / (1 + 0.2 (H/D − 6) A_r^½), A_r = D²/(4 r_r²); Re = V D/ν with V the jet exit velocity | D (nozzle) | 2000 ≤ Re ≤ 4e5, 2 ≤ H/D ≤ 12, 0.004 ≤ A_r ≤ 0.04 | 7.71, 7.72 |
| `duct_internal` | Internal flow, circular or by hydraulic diameter | see §8.1 | D_h | | |
| `vplate_natural` | Vertical plate (Churchill–Chu) | Nu = {0.825 + 0.387 Ra^(1/6) / [1+(0.492/Pr)^(9/16)]^(8/27)}² | height | all Ra | 9.26 |
| `vplate_natural_laminar` | Vertical plate, laminar (Churchill–Chu; slightly more accurate than 9.26 for Ra ≤ 1e9) | Nu = 0.68 + 0.670 Ra^¼ / [1+(0.492/Pr)^(9/16)]^(4/9) | height | Ra ≤ 1e9 | 9.27 |
| `inclined_natural` | Plate inclined θ from vertical: the top face of a cold plate or the bottom face of a hot plate | as `vplate_natural` with g → g cos θ | length | 0 ≤ θ ≤ 60°; for the other face [I] makes no recommendation (see below) | 9.26, §9.6.2 |
| `hplate_up_natural` | Horizontal, hot face up or cold face down | Ra ≤ 1e7: Nu = 0.54 Ra^¼; else Nu = 0.15 Ra^⅓ | area/perimeter | 1e4 ≤ Ra ≤ 1e11; when Ra ≤ 1e7 also Pr ≥ 0.7 | 9.30, 9.31 |
| `hplate_down_natural` | Horizontal, hot face down or cold face up | Nu = 0.52 Ra^(1/5) | area/perimeter | 1e4 ≤ Ra ≤ 1e9, Pr ≥ 0.7 | 9.32 |
| `hcyl_natural` | Horizontal cylinder (Churchill–Chu) | Nu = {0.60 + 0.387 Ra^(1/6) / [1+(0.559/Pr)^(9/16)]^(8/27)}² | diameter | Ra ≤ 1e12 | 9.34 |
| `sphere_natural` | Sphere (Churchill) | Nu = 2 + 0.589 Ra^¼ / [1+(0.469/Pr)^(9/16)]^(4/9) | diameter | Pr ≥ 0.7, Ra ≤ 1e11 | 9.35 |
| `vchannel_natural` | Vertical channel between two parallel isothermal plates, both at T_s (Bar-Cohen–Rohsenow) | Nu_S = [576/(Ra_S S/L)² + 2.87/(Ra_S S/L)^½]^(−½), Ra_S = Ra with L → S; h = Nu_S k_f / S | S (plate spacing); L = channel height | none stated | 9.45, Table 9.3 |
| `vchannel_one_side_natural` | Vertical channel, this plate at T_s, the opposite plate adiabatic (Bar-Cohen–Rohsenow) | Nu_S = [144/(Ra_S S/L)² + 2.87/(Ra_S S/L)^½]^(−½), Ra_S and h as above | S; L = channel height | none stated | 9.45, Table 9.3 |
| `power_law` | User form | h = C · \|T_s − T∞\|ⁿ | — | — | — |

For the horizontal-plate pair, pick "up" or "down" automatically at run time from the sign
of (T_s − T∞) and the declared face direction. Outside a validity range: still evaluate,
and emit one warning per boundary condition per solve.
`plate_forced_local` needs the leading-edge point and flow direction; x is the distance of
the integration point from the leading edge along the flow direction (minimum x = 1e-6 m).

`inclined_natural`: when the face direction is declared, a face for which [I] makes no
recommendation counts as outside the validity range: the top face (`up`) of a hot plate
(T_s > T∞), or the bottom face (`down`) of a cold plate. When no face direction is declared,
this is not checked.

**Characteristic lengths in a 2D model.**
- **Horizontal plates.** [I] defines L = A_s/P (Eq. 9.29). In a planar model a horizontal
  face is a strip of unit depth, so A_s/P is half the strip's width; [I] Example 9.3 uses w/2
  in the same way. In an axisymmetric model, a horizontal ring from r_i to r_o gives
  A_s/P = (r_o − r_i)/2. Either way, the automatic L_c of `hplate_up_natural` and
  `hplate_down_natural` is **half the total length of the selection**. This settles Q17.2.
- **Other correlations.** For the other plate correlations and the vertical channels
  (channel height), the automatic L_c is the total length of the selection.
- **Diameters.** The cylinder, sphere and non-circular cylinder correlations need L_c (the
  diameter or D) given.
- **An explicit L_c always overrides the automatic one.**

**Extra inputs** (Data §8 `params`):
- **Vertical channels:** `S`, the plate spacing [m].
- **`slot_jet`:** `W`, the slot width [m]; `H`, the nozzle-to-surface distance [m]; `x_r`,
  the half-width of the region averaged over [m]. The default `x_r` is half the total length
  of the selection.
- **`round_jet`:** `D`, the nozzle diameter [m]; `H` [m]; `r_r`, the radius of the region
  averaged over [m]. In an axisymmetric model the default `r_r` is the largest radial
  coordinate of the selection; a planar model must give `r_r`.
- **The jets take their L_c from these inputs**, so a given L_c is refused.

### §8.1 Internal duct flow
Re = ṁ D_h /(A μ), D_h = 4A/P_wet. Properties at the bulk fluid temperature.

- Laminar (Re ≤ 2300): Nu_lam from the tables below ([I] Tables 8.1 and 8.2).
- Turbulent (Re ≥ 4000): Gnielinski ([I] 8.62, with f from 8.21)
  Nu = (f/8)(Re − 1000) Pr / [1 + 12.7 (f/8)^½ (Pr^⅔ − 1)], f = (0.790 ln Re − 1.64)⁻²
  (valid 0.5 ≤ Pr ≤ 2000, 3000 ≤ Re ≤ 5e6).
- Transition (2300 < Re < 4000): linear interpolation in Re between Nu_lam and
  Nu_Gnielinski(Re = 4000). [I] gives no transition correlation; this rule is the program's.

| Cross-section (`cross_section`) | Nu_lam, constant wall T | Nu_lam, constant flux |
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
([I] Table 8.2). D_h = D_o − D_i. The stream gives `diameter_ratio` = D_i/D_o. Nu is
linearly interpolated in D_i/D_o between the rows; the program, not [I], sets that rule.

| D_i/D_o | Nu_i: inner surface heated (`annulus_inner`) | Nu_o: outer surface heated (`annulus_outer`) |
|---|---|---|
| 0 | — | 3.66 |
| 0.05 | 17.46 | 4.06 |
| 0.10 | 11.56 | 4.11 |
| 0.25 | 7.37 | 4.23 |
| 0.50 | 5.74 | 4.43 |
| 1.00 | 4.86 | 4.86 |

- `annulus_inner` needs 0.05 ≤ D_i/D_o ≤ 1. `annulus_outer` needs 0 ≤ D_i/D_o ≤ 1.
- [I] gives only constant-temperature values for the annulus, so a constant-flux request is
  refused.

Default is the constant-wall-temperature value. Optional user selections, each replacing
Gnielinski as the turbulent formula (the laminar value and the transition rule are kept):
- **Dittus–Boelter** ([I] 8.60): Nu = 0.023 Re^0.8 Pr^n. n = 0.4 if the wall is hotter
  than the fluid, else 0.3. Valid for 0.6 ≤ Pr ≤ 160 and Re ≥ 1e4.
- **Sieder–Tate** ([I] 8.61): Nu = 0.027 Re^(4/5) Pr^(1/3) (μ/μ_s)^0.14. μ_s is taken at the
  cell's mean wall temperature T̄_w; the other properties at the bulk temperature. Valid for
  0.7 ≤ Pr ≤ 16700 and Re ≥ 1e4. [I] recommends it for flows with large property variation,
  such as oils.

Friction factor, all regimes (Churchill 1977, not in [I]), roughness e:
f = 8 [ (8/Re)¹² + (A + B)^(−1.5) ]^(1/12),
A = [2.457 ln( 1 / ((7/Re)^0.9 + 0.27 e/D_h) )]¹⁶, B = (37530/Re)¹⁶

Pressure drop of a duct of length L with minor-loss coefficient K_minor:
Δp = (f L/D_h + K_minor) · ρ V²/2, V = ṁ/(ρ A).

### §8.2 Correlations of [I] that are not used
Recorded so that no task adds them without a decision. On 2026-11-23 the owner judged the
correlations in use adequate and declined the enclosure, mixed-convection and Table 8.1 f·Re
additions (Q30.4):
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
  Churchill 1977 is kept; it applies to circular ducts and to D_h. Using Table 8.1's f·Re
  would need a rule for joining it to the turbulent branch, which [I] does not give
  (OPEN_QUESTIONS Q30).
- **Isoflux vertical channels (9.46), inclined channels (9.47), and the isolated-plate
  optimum spacings (Table 9.3).** The isothermal form 9.45 is used.
- **Enclosures: rectangular cavities, concentric cylinders and spheres (9.49–9.63).** They
  couple two surfaces across a cavity, and a convection load sees only one ambient
  temperature (Q30).
- **Mixed free and forced convection (9.64).** This needs two correlations in one load
  (Q30).
- **Boiling and condensation (chapter 10).** The fluids here do not change phase.

## §9 Flow solver

### §9.1 Stream (fluid temperature along a wall)
A stream is a 1D fluid path with mass flow ṁ [kg/s], inlet temperature T_in, flow area A,
wetted perimeter P_wet (for D_h), fluid, and one or more **wall boundary sets** that it
cools or heats. The stream is divided into N cells along its path coordinate s. Fluid node
0 is the inlet (prescribed T_in); fluid node j is the outlet of cell j−1. Fluid nodes are
extra DOFs appended after the mesh nodes.

Each wall edge element i belongs to the cell containing the s-coordinate of its midpoint
(s = projection of the midpoint onto the stream path polyline). Per edge element:
- conductance G_i = h_i · ∫ g ds over the edge (h from §8.1 using the cell's upstream
  fluid-node temperature for properties, lagged)
- wall temperature T_w,i = Σ_j w_j T_j with w_j = ∫ N_j g ds / ∫ g ds

Per cell with upstream fluid node u and downstream node d:
- G = Σ G_i, T̄_w = Σ G_i T_w,i / G, NTU = G /(ṁ c_p)
- φ = (1 − e^(−NTU)) / NTU  (φ = 1 when NTU < 1e-8)
- Effective fluid temperature seen by the wall: **T_f\* = (1 − φ) T̄_w + φ T_u**
- Heat from wall edge i to fluid: Q_i = G_i (T_w,i − T_f\*)
- Fluid energy equation: ṁ c_p (T_d − T_u) − Σ_i Q_i = 0

Q_i is removed from the wall nodes of edge i with the same weights w_j. This scheme is
exact for a constant wall temperature per cell, cannot oscillate for any NTU, and conserves
energy exactly. The resulting matrix rows are linear in the unknown temperatures (for
frozen h and c_p) and **unsymmetric**. Fluid thermal storage is neglected (quasi-steady
fluid) — state this in the user guide.

Matrix contributions for one cell, written as a conductance-type matrix K_s such that the
heat *leaving* each DOF is K_s·T: for wall DOF a (weight w_a,i on edge i):
row a gets Σ_i w_a,i G_i (T_w,i − (1−φ) T̄_w − φ T_u), and row d gets
ṁ c_p (T_d − T_u) − Σ_i G_i (T_w,i − (1−φ) T̄_w − φ T_u). Expand T_w,i and T̄_w into nodal
weights to obtain the coefficients. Implement this by building the small dense cell matrix
with NumPy and scattering it.

A stream may also be **through-plane** (planar models: flow perpendicular to the model
plane, such as a cooling hole seen in cross-section). Then the fluid temperature is uniform
on the boundary set and equals the specified bulk temperature; the stream only supplies h
from §8.1. No fluid DOFs are created.

### §9.2 Network (flow distribution)
Nodes carry pressure; branches are ducts (§8.1 pressure drop), minor-loss elements, or
fixed-flow sources. Boundary conditions: prescribed pressure at a node, or prescribed mass
flow into a node. Unknowns: nodal pressures.

Branch law: ṁ = sign(Δp) · A √( 2 ρ |Δp| / (f L/D_h + K_minor) ).
Linearise as ṁ = c (p_i − p_j) with c = ṁ/Δp from the previous iterate (start with
laminar f = 64/Re assumption at Re = 1000). Iterate: assemble Σ c (p_i − p_j) = source at
each node, solve, update ṁ and f, under-relax c with factor 0.5, until the largest relative
change in any ṁ < 1e-6 (max 200 iterations). Each branch's ṁ then feeds the stream
attached to it. Fluid properties in the network use each branch's mean stream temperature;
the hydraulic and thermal solutions are alternated inside the nonlinear loop
(hydraulics updated at most once per nonlinear iteration, and only when a branch's mean
temperature has changed by more than 1 K).

## §10 Enclosure radiation (grey, diffuse)

Faces = boundary edge elements of the enclosure, i = 1…n, length-based area A_i = ∫ g ds,
emissivity ε_i, face temperature T_i = Σ w_j T_j (weights as in §9.1), E_b,i = σ T_i⁴.
View-factor matrix F (n×n). Open enclosures: F_i∞ = 1 − Σ_j F_ij radiates to a black
ambient at T_∞.

With E = diag(ε): solve **(I − (I − E) F) J = E·E_b + (I − E) F_∞ σT_∞⁴** for radiosity J.
Net flux leaving face i: q_i = J_i − Σ_j F_ij J_j − F_i∞ σ T_∞⁴.

Precompute once per mesh: M = (I − F)(I − (I−E)F)⁻¹ E and the ambient vector. Then
q = M E_b + q_∞, heat Q_i = A_i q_i, distributed to the face's nodes with weights w_j.
Residual contribution: −Q. Tangent: ∂Q_i/∂T_j = A_i M_ij 4σT_j³ (dense block; insert it
fully when n ≤ 3000, otherwise only its diagonal).

### §10.1 View factors, planar
For two straight segments i (endpoints a1,a2) and j (endpoints b1,b2) that fully see each
other (Hottel crossed strings):

  F_ij = [ |a1b2| + |a2b1| − |a1b1| − |a2b2| ] / (2 L_i)   (use the absolute value;
  "crossed" strings are the two that intersect)

Visibility: a pair is *facing* if each midpoint lies on the outward-normal side of the
other. A pair is *fully visible* if facing and none of the four end-to-end sight lines
intersects any other enclosure segment. If facing but not fully visible, subdivide both
segments into m = 8 sub-segments, apply crossed strings to each fully visible sub-pair
(testing sight lines between sub-segment endpoints), and sum:
F_ij = Σ_sub L_sub,i F_sub / L_i. Use a uniform grid or `shapely.STRtree`-free hand-written
segment-intersection test vectorised with NumPy.

Afterwards enforce reciprocity (A_i F_ij ← ½(A_i F_ij + A_j F_ji)) and, for closed
enclosures, scale rows so Σ_j F_ij = 1 (repeat both steps 5 times).

### §10.2 View factors, axisymmetric (task M9.5)
Each face is a conical ring. Compute F_ij by numerical integration of the 3D kernel
cosθ_i cosθ_j /(π r²) over the azimuth of ring j (and sub-divisions of both generators),
with blockage tested by intersecting each ray with every other ring's cone frustum.
Validate against concentric-cylinder and coaxial-disk closed forms (V-22).

## §11 Thermal contact resistance
Along an interface curve the mesh has duplicated nodes (one set per side). For each pair of
matching edge elements with contact conductance h_c [W/m²·K] add, over the 2n interface
DOFs [side A; side B]:

  K_c = Σ_gp h_c g |J_s| w · [[NᵀN, −NᵀN], [−NᵀN, NᵀN]]

## §12 Phase change (apparent heat capacity)
Latent heat L released between T_sol and T_liq is modelled by replacing ρc with
ρc + ρL/(T_liq − T_sol) for T_sol ≤ T ≤ T_liq. Require T_liq − T_sol ≥ 1 K, force lumped
capacitance and backward Euler, and limit max_dT_per_step to (T_liq − T_sol)/2.
