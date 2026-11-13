# Verification cases

Each case becomes one test in `tests/verification/test_vNN_*.py` and one runnable script in
`examples/`. Tests compute the analytic answer from the formula given here — do not paste
in pre-computed numbers, except the published NAFEMS targets.

Unless stated: planar, thickness 1 m, k = 50 W/m·K, ρ = 7800, c = 500, temperatures in K.
"1D" cases are modelled as a 2D strip (length L in x, height L/10) with the long sides
adiabatic. Run every case with **all four element types** unless noted. Tolerance is on the
relative error against the analytic value, with the mesh size given.

## Steady conduction

| ID | Problem | Analytic answer | Mesh | Tol |
|---|---|---|---|---|
| V-01 | Slab L = 0.1, T(0) = 400, T(L) = 300 | T(x) linear; flux q = k ΔT/L everywhere | 10 elements along x | 1e-10 |
| V-02 | Slab, T(0) = 400, convection at x = L: h = 100, T∞ = 300 | T(L) = T∞ + (T0 − T∞)/(1 + hL/k); heat flow = k (T0 − T(L))/L | 10 | 1e-10 |
| V-03 | Slab, both faces 300 K, Q = 1e6 W/m³ | T(x) = 300 + Q/(2k) · x (L − x) | 20 | linear 1e-3, quadratic 1e-10 |
| V-04 | Slab, flux q̄ = 5000 W/m² in at x = 0, T(L) = 300 | T(0) = 300 + q̄ L/k | 10 | 1e-10 |
| V-05 | Hollow cylinder, axisymmetric, r_i = 0.05, r_o = 0.1, T_i = 400, T_o = 300 | T(r) = T_i − (T_i − T_o) ln(r/r_i)/ln(r_o/r_i); heat flow per height = 2πk (T_i − T_o)/ln(r_o/r_i) | 40 radial | linear 1e-3, quadratic 1e-5 |
| V-06 | Same cylinder modelled **planar** as a quarter annulus (symmetry on the cut edges) | same T(r); heat flow ×¼ | size 0.004 | 2e-3 |
| V-07 | Solid cylinder, axisymmetric, radius R = 0.05, Q = 1e6, surface convection h = 500, T∞ = 300 | T(r) = T∞ + QR/(2h) + Q (R² − r²)/(4k) | 20 radial | linear 1e-3 |
| V-08 | Straight fin, L = 0.1, thickness 0.004, base 400 K, h = 50 on both long faces and tip, T∞ = 300, k = 200. Model the fin in 2D with its real thickness. | 1D fin with convecting tip: θ/θ_b = [cosh m(L−x) + (h/mk) sinh m(L−x)] / [cosh mL + (h/mk) sinh mL], m = √(2h/(k·thickness)) | size 0.001 | 5e-3 (1D theory is approximate; Bi is small) |
| V-09 | Rectangle a × b = 1 × 1, three sides at 300 K, top side at 400 K | θ(x,y) = (2/π) Σ_{n=1..199} [((−1)^{n+1} + 1)/n] sin(nπx/a) sinh(nπy/a)/sinh(nπb/a), T = 300 + 100 θ. Check at (0.5, 0.5) (θ = 0.25) and (0.5, 0.75) | size 0.02 | 1e-3 at interior points |
| V-10 | **NAFEMS T4.** Rectangle 0.6 (x) × 1.0 (y), k = 52. Bottom edge 100 °C; left edge adiabatic; right and top edges convection h = 750, T∞ = 0 °C | T at (0.6, 0.2) = **18.3 °C** | size 0.05, then 0.025 | within 0.15 °C at the fine mesh |
| V-11 | Two-layer slab, layers 0.05 m each, k1 = 50, k2 = 5, T(0) = 400, T(L) = 300 | Series resistance; interface T = 400 − 100·(L1/k1)/(L1/k1 + L2/k2); nodal flux has one value per region at the interface and both equal q | 10 per layer | 1e-10 |
| V-12 | Orthotropic square 1 × 1, k1 = 50, k2 = 5, material angle 30°, manufactured solution T = 300 + 50 x² + 30 xy + 20 y² imposed on all edges, with Q = −∇·(D∇T) (a constant; compute it from D) | the manufactured T | size 0.05, quadratic elements | 1e-9 |

## Nonlinear steady

| ID | Problem | Analytic answer | Tol |
|---|---|---|---|
| V-13 | Slab L = 0.1, T(0) = 400, T(L) = 300, k(T) = k0 (1 + β (T − 300)), k0 = 50, β = 0.01 | Kirchhoff: with U(T) = (T−300) + β (T−300)²/2, U is linear in x. Solve the quadratic for T(x). Flux = k0 (U(400) − U(300))/L | 1e-4, 40 elements |
| V-14 | **NAFEMS T2.** Bar L = 0.1, k = 55.6, T(0) = 1000 K, far end radiates to 300 K with ε = 0.98, σ = 5.67e-8 | T at radiating end = **927.0 K** (also the root of k (1000 − T)/L = εσ (T⁴ − 300⁴)) | 0.1 K |
| V-15 | Slab with natural convection: T(0) = 400, face x = L uses `vplate_natural`, air, T∞ = 300, height 0.5 | Solve the scalar equation k (400 − T_s)/L = h(T_s)(T_s − T∞) with `scipy.optimize.brentq` using the same correlation function | 1e-5 |

## Transient

| ID | Problem | Analytic answer | Settings | Tol |
|---|---|---|---|---|
| V-16 | Lumped body: square 0.01 × 0.01, k = 400, initial 400 K, convection on all four edges h = 20, T∞ = 300 (Bi ≪ 0.1) | T(t) = T∞ + (T_i − T∞) exp(−h A t /(ρ c V)), A = 0.04·1, V = 1e-4·1; check at t = τ and 3τ, τ = ρcV/(hA) | fixed Δt = τ/200, θ = 1 then ½ | 5e-3 (θ=1), 1e-4 (θ=½) |
| V-17 | Slab half-thickness L = 0.05 (symmetry at x = 0), initial 400, convection at x = L: h = 500, T∞ = 300 | θ* = Σ_{n=1..20} C_n exp(−ζ_n² Fo) cos(ζ_n x/L); ζ_n tan ζ_n = Bi (roots by `brentq` in ((n−1)π, (n−½)π)); C_n = 4 sin ζ_n /(2ζ_n + sin 2ζ_n); Fo = αt/L². Check centre and surface at Fo = 0.2 and 1.0 | 40 elements, auto time step | 2e-3 |
| V-18 | Semi-infinite solid: slab L = 0.5, initial 300, T(0) steps to 400 at t = 0⁺ | T(x,t) = 400 − 100 erf(x / (2√(αt))); check x = 0.01, 0.02 at t = 30 s (far end stays undisturbed) | graded mesh (size 0.001 near x = 0), lumped capacitance, auto time step | 1e-2 |
| V-19 | **NAFEMS T3.** Bar L = 0.1, k = 35.0, c = 440.5, ρ = 7200. T(0,t) = 0 °C, T(L,t) = 100 sin(πt/40) °C, initial 0 °C | T at x = 0.08, t = 32 s = **36.60 °C** | 20 quadratic elements, Δt = 0.5, θ = ½ and θ = 1 | 0.3 °C (θ=½), 1.0 °C (θ=1) |
| V-20 | Radiative cooling of a lumped body: as V-16 but radiation ε = 0.8 to 300 K instead of convection, initial 800 K | Integrate ρcV dT/dt = −εσA (T⁴ − T∞⁴) with `scipy.integrate.solve_ivp` (rtol 1e-10) | auto time step, time_tol = 0.005 | 2e-3 |
| V-21 | Time-stepping order: V-16 with Δt, Δt/2, Δt/4 | observed order ≈ 1 (θ = 1), ≈ 2 (θ = ½) | fixed steps | order within ±0.15 |

## Enclosure radiation

| ID | Problem | Analytic answer | Tol |
|---|---|---|---|
| V-22a | View factors: two parallel segments, width w = 1, gap d = 0.5, directly opposed | F = √(1 + (d/w)²) − d/w | 1e-10 (single segment each); 1e-6 summed over a 20-element mesh |
| V-22b | Two perpendicular segments of equal width sharing an edge | F = 1 − √2/2 | 1e-6 |
| V-22c | Closed square cavity, 10 elements per side | every row sums to 1; reciprocity error < 1e-12 | — |
| V-22d | Parallel plates with a blocking strip between them covering the middle half | compare with crossed-strings applied by hand to the unblocked strips | 2e-2 |
| V-23 | Two long parallel plates separated by a narrow gap (geometry in the note below the table), outer faces held at 600 K and 300 K, ε1 = 0.8, ε2 = 0.5 | q = σ (T1⁴ − T2⁴)/(1/ε1 + 1/ε2 − 1) between the gap-facing surface temperatures; solve the 1D series network (conduction–radiation–conduction) with `brentq` | 5e-3 on heat flux at the centre |
| V-24 | Concentric cylinders, planar cross-section, r1 = 0.05 (outer surface of a solid rod at 600 K core), r2 = 0.1 (inner surface of a ring whose outside is 300 K) | q1 = σ (T1⁴ − T2⁴)/(1/ε1 + (1 − ε2)/ε2 · r1/r2) | 1e-2 |

## Flow and convection

| ID | Problem | Analytic answer | Tol |
|---|---|---|---|
| V-25 | Correlation spot checks: each correlation function against values computed by hand in the test from the Theory §8 formula with fixed property inputs (pure-function test; Pr = 0.7, several Re / Ra spanning each branch) | formula | 1e-12 |
| V-26 | Churchill friction factor | Laminar: f → 64/Re at Re = 500 (1e-3). Smooth turbulent Re = 1e5: within 3% of (0.790 ln Re − 1.64)⁻² | as stated |
| V-27 | Stream, constant wall temperature: wall is a fixed-temperature edge at 350 K, length 1 m, water, T_in = 300, ṁ chosen so NTU ≈ 1, constant h override | T_out = T_w − (T_w − T_in) exp(−hA/(ṁ c_p)) | 1e-6 (the scheme is exact here), for 1 cell and for 20 cells |
| V-28 | Stream, constant heat flux: thin wall strip with flux q̄ on the outside, stream inside | T_out = T_in + q̄ A /(ṁ c_p); wall-to-fluid ΔT = q̄/h far from the inlet | 1e-6 on T_out, 1e-2 on ΔT |
| V-29 | Energy conservation with a stream: any model; Σ boundary heat flows + ṁ c_p (T_in − T_out) = 0 | — | 1e-8 relative |
| V-30 | Network: two identical parallel ducts between two pressure nodes | equal split; total flow matches the single-duct law. Laminar single duct: Δp = 32 μ L V/D² | 1e-5 |
| V-31 | Network: two parallel ducts, one twice as long, turbulent | flows satisfy equal Δp using the Churchill f; check by evaluating Δp for each branch | 1e-5 |

## Mesh convergence and robustness

| ID | Problem | Requirement |
|---|---|---|
| V-32 | Manufactured solution T = 300 + 50 sin(πx) sin(πy) on the unit square, Q = 2π²·k·50 sin(πx) sin(πy) (given to the solver as an `Expression`), T = 300 on all edges; sizes 0.1, 0.05, 0.025 | L2 error order ≥ 1.9 (T3, Q4), ≥ 2.8 (T6, Q8) |
| V-33 | Patch test: irregular 8-element patch, linear temperature field imposed on the boundary | interior nodes exact to 1e-12; flux constant to 1e-10; all element types |
| V-34 | Energy balance on every case above | imbalance < 1e-3 of throughput (< 1e-8 for linear steady cases) |
| V-35 | Thermal contact: V-11 with a contact conductance h_c = 2000 at the interface | temperature jump = q/h_c; q from series resistance including 1/h_c; 1e-9 |
| V-36 | Phase change (Stefan problem, one phase): semi-infinite slab initially at T_m = 300 (liquid at its freezing point), surface dropped to 280 K; L = 1e5 J/kg, T_liq − T_sol = 1 K centred on T_m | interface position X(t) = 2λ√(αt), λ from λ e^{λ²} erf(λ) = c (T_m − T_s)/(L √π) by `brentq` | 5% on X at two times |

## Extensibility guard

| ID | Problem | Requirement |
|---|---|---|
| V-37 | 3D patch test. Inside the test only: register a 4-node tetrahedron `Tet4` (N = [1−ξ−η−ζ, ξ, η, ζ], 1-point rule at (¼,¼,¼) with w = 1/6, facet type `T3`) and build a `Mesh` with `dim = 3` of a unit cube split into 6 tetrahedra plus one interior node arrangement of your choice. Impose T = 300 + 10x + 20y + 30z on all boundary nodes, k = 50, and solve with the unmodified kernel, `ConductionTerm` and steady driver. Also integrate a unit flux over one cube face using `facet_geometry` on T3 facets. | Interior temperatures exact to 1e-10; flux = (−500, −1000, −1500) in every element; face integral = 1.0. The test must pass **without any change to library code that mentions `Tet4` or dim = 3**. |

Note on V-23: model two solid slabs each 1 m wide (x) and 0.02 m thick (y), separated by a 0.01 m gap, enclosure
= the two gap-facing edges, `open_to_ambient = True` with T_ambient = 300 K (the open ends
are 1% of the view and are ignored by sampling only |x − 0.5| < 0.1).
