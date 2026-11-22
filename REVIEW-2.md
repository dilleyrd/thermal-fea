# ThermalFEA Codebase & Architecture Review

**Baseline check (2026-11-21):** Clean working tree on `main` (`353a3ca`); `ruff check .` passes; `scripts/build_guide.py --check` is up to date; full offscreen `pytest` suite passes (**2,011 passed** in 111 s).

> [!NOTE]
> The repository already contains [REVIEW.md](file:///d:/Documents/Projects/thermal-fea/REVIEW.md) (Nov 20, 2026) tracking 9 findings (3 fixed in `M11.11`, 6 open in `M11.12`–`M11.16`) plus 6 GUI/guide defects in `Q26.4` (`M11.7`–`M11.10`). **All findings below are newly identified issues** not covered by those lists, except where a deeper root cause extends an existing item.

---

## 1. Directory Structure & Packaging Review

### Strengths
The repository is unusually well disciplined for an agent-built engineering codebase:
- Clean `src/` package layout (`core`, `materials`, `model`, `geometry`, `meshing`, `physics`, `convection`, `flow`, `solver`, `post`, `gui`) with explicit architectural boundaries enforced by [test_layers.py](file:///d:/Documents/Projects/thermal-fea/tests/unit/test_layers.py).
- Registry-driven extensibility (`ElementType`, `BoundaryCondition`, `Term`, `Constraint`, `FlowProvider`, `SceneView`) backed by a 3D tetrahedron guard test ([test_v37_tet_guard.py](file:///d:/Documents/Projects/thermal-fea/tests/verification/test_v37_tet_guard.py)).
- Rich analytical verification suite (`V-01`–`V-37`) paired with runnable scripts in `examples/`, offscreen GUI tests (`tests/gui/`), and a reproducible MkDocs user guide (`guide/`).

### Structural & Packaging Issues

| Severity | Issue | Location |
|---|---|---|
| **High** | **Undeclared runtime dependency `Pillow` & unused mandatory dependency `pandas`.** [export.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/post/export.py#L22) unconditionally executes `from PIL import Image` (transitively imported by `api.py`), yet `Pillow` is missing from `dependencies` in [pyproject.toml](file:///d:/Documents/Projects/thermal-fea/pyproject.toml#L10-L19). Conversely, `pandas` is declared as a mandatory core dependency despite **zero** imports anywhere in `src/thermalfea/`—it is used solely by 4 scripts in `examples/pump_closure/showcase/` to read small CSVs, unnecessarily bloating every install and future PyInstaller build. | [pyproject.toml](file:///d:/Documents/Projects/thermal-fea/pyproject.toml#L10-L19), [export.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/post/export.py#L22) |
| **Medium** | **~30.5 MB of committed binary outputs & 4.1 MB of byte-duplicated images.** `examples/pump_closure/out/` commits 10 `.h5` files totaling 26.4 MB (three of which—`closure_steady.tfea.h5`, `closure_steady_mesh1.tfea.h5`, and `closure_steady_seat1.tfea.h5`—are identical 778 KB files). All 12 pump-closure images (4.1 MB) are committed **twice, byte-for-byte identical**, under both `examples/pump_closure/` and `guide/examples/img/`. | [.gitignore](file:///d:/Documents/Projects/thermal-fea/.gitignore#L10-L12), `examples/pump_closure/out/`, `guide/examples/img/` |
| **Medium** | **Transitive `gmsh` C++ load inside `gui/`.** Three GUI modules import `BuiltGeometry` from `geometry.builder` at runtime (not under `TYPE_CHECKING`, unlike [scene.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/scene.py#L34)). Because `builder.py` imports `gmsh_session.py`, which runs `import gmsh`, merely importing `gui.document` or `gui.viewport_mpl` eagerly loads the `gmsh` binary library. | [document.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/document.py#L44), [viewport_mpl.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/viewport_mpl.py#L52), [selection_editor.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/property_panels/selection_editor.py#L31) |
| **Low** | **Missing repo metadata & packaging polish.** No root `README.md`; `pyproject.toml` omits `readme`, `license`, `urls`, and a `[project.gui-scripts]` entry point (or `thermalfea gui` subcommand—users must invoke `python -m thermalfea.gui.app`); [tests/gui/.gitkeep](file:///d:/Documents/Projects/thermal-fea/tests/gui/.gitkeep) is leftover scaffolding; `.deepeval/` is present in workspace root and `.gitignore`. | [pyproject.toml](file:///d:/Documents/Projects/thermal-fea/pyproject.toml#L5-L28), [cli.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/cli.py#L86-L106) |

---

## 2. Newly Identified Errors & Bugs

### 2.1 High-Severity Bugs (Wrong Results, Crashes, or Broken Core Workflows)

#### Solver & Numerics

1. **Nonlinear residual reference $F_{\mathrm{ref}}$ collapses to round-off at uniform temperature / radiative equilibrium, causing false `ConvergenceError`**
   - **Where:** [nonlinear.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/nonlinear.py#L70-L72), [transient.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/transient.py#L206-L213)
   - **Cause:** `Assembled.reference(u)` computes $\max(\|F\|_2, \|Ku\|_2, 10^{-12})$. At uniform temperature $u = c\mathbf{1}$, $Ku$ cancels to floating-point round-off because constant vectors lie in the nullspace of pure conduction $K$. Radiation puts its flux in `r_extra` (not `F`), so $\|F\|_2 = 0$, and near steady state $\|C(u-u_{\mathrm{prev}})/\Delta t\|_2 \to 0$. Consequently $\|r_f\|_2 / F_{\mathrm{ref}} \approx 0.7\text{--}0.9 \gg \mathrm{rtol}$ even when $\max|\Delta T| \sim 10^{-15}\,\mathrm{K}$. (Notably, [transient.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/transient.py#L397) already noticed this cancellation for the startup check and used `abs(K) @ np.abs(T)`, whereas `reference()` did not.)
   - **Impact:** Steady radiation equilibrium, uniform-T nonlinear conduction, and long transient radiation cooling runs that reach equilibrium crash with `ConvergenceError` despite machine-precision convergence.

2. **Transient restart always crashes when a `FlowNetwork` supplies a stream's mass flow**
   - **Where:** [run.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/run.py#L306-L314), [transient.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/transient.py#L245-L253), [stream.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/flow/stream.py#L217-L235)
   - **Cause:** On `restart=True`, `initial_state(..., resume=True)` skips `provider.initialize()`, leaving `term.mass_flow_override = None`. Immediately on line 314, `run_transient` calls `term_heats(problem, start, t0)` before `provider.update()` has ever run, raising `ModelError: stream '...' has no mass flow: give one, or attach it to a network branch`. (If a fallback `mass_flow` exists, `heats_prev` is silently computed with the wrong flow, corrupting step 1's energy balance for $\theta < 1$.)

3. **Quasi-steady stream DOFs ($C = 0$) exhibit permanent undamped sawtooth oscillation with $\theta < 1$ after restart with changed flow/loads**
   - **Where:** [transient.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/transient.py#L196-L200), [transient.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/transient.py#L401)
   - **Cause:** Fluid DOFs have zero capacitance (index-1 algebraic constraint $g_d = 0$), yet `StepSystem.residual` applies $\theta g_{n+1} + (1-\theta)g_n = 0$ uniformly. On `resume=True`, `startup` is forced `False` even when stream `mass_flow` or `h_override` changed between runs (permitted by `M11.11`). With $\theta = 0.5$, nonzero $g_d(T_0, t_0)$ forces $g_d(T_{n+1}) = -g_d(T_n)$ forever—reproduced as a permanent ~10 K step-to-step outlet temperature oscillation.

4. **Unscaled pivot-ratio singularity check falsely rejects well-conditioned multi-scale / small-$\Delta t$ stream-coupled systems**
   - **Where:** [linear.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/linear.py#L23), [linear.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/linear.py#L77-L82)
   - **Cause:** `SuperLUFactorization` raises `SolverError` when `pivots.min() <= 1e-13 * pivots.max()` on the unequilibrated matrix. In transient solid+stream problems, solid pivots scale as $C/\Delta t$ while quasi-steady fluid pivots stay at $\theta \dot{m} c_p$; a small air flow at $\Delta t = 10^{-7}\,\mathrm{s}$ exceeds the $10^{13}$ ratio and aborts as "singular" despite being well-posed and accurately solvable.

5. **Adaptive error estimator and `max_dT_per_step` include prescribed DOFs and never reset across discontinuities**
   - **Where:** [transient.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/transient.py#L477-L490), [timestep.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/timestep.py#L66-L70)
   - **Cause:** `error_estimate()` and `max|T_new - T|` include fixed DOFs, and `T_before` is not reset when `discontinuous` is `True`. A step jump in `FixedTemperature` makes `|T_new - T_pred|` equal to the full jump regardless of $\Delta t$, forcing ~30 consecutive rejections and collapsing $\Delta t$ to `dt_min` twice in a row.

6. **Valid curved quadratic elements fail `Mesh.validate()` and receive inverted `Mesh.outward_normals()`**
   - **Where:** [mesh.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/core/mesh.py#L215), [mesh.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/core/mesh.py#L244-L248), [mesh.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/core/mesh.py#L355-L360)
   - **Cause:** Orientation is tested using `normal · (facet_mid - node_average_centroid) > 0`. On curved `Q8`/`T6` elements along a concave boundary (e.g., thin annular ring), the mean node position lies *outside* the inner arc, inverting the vector. Valid positive-Jacobian curved elements fail `Mesh.validate()` with `"oriented towards their parent element"`.

#### Convection & Flow

7. **Pipe-network solver fails to converge (`ConvergenceError`) and loses mass conservation on near-balanced bridges / near-zero-flow `loss` branches**
   - **Where:** [network.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/flow/network.py#L80-L84), [network.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/flow/network.py#L223-L241)
   - **Cause:** For a `"loss"` branch ($L/D = 0, K_{\mathrm{minor}} > 0$), $c_{\mathrm{new}} = \dot{m}_{\mathrm{new}}/\Delta p \propto 1/\sqrt{|\Delta p|} \to \infty$ as $\Delta p \to 0$. Without conductance regularization or an absolute flow floor in `_rel_change`, a near-balanced Wheatstone bridge drives $c$ to huge values, ill-conditioning the nodal matrix and stalling convergence at ~3% relative error until hitting the 200-iteration cap.

8. **Hydraulics are re-solved inside Newton line-search trials (violates Theory §9.2 and breaks line search)**
   - **Where:** [coupling.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/flow/coupling.py#L171-L208), [steady.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/steady.py#L51-L52), [nonlinear.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/nonlinear.py#L174-L185)
   - **Cause:** `assemble()` calls `provider.update(state)` unconditionally on every line-search trial `T + s * dT` (and in `_jumps()` probes), mutating `self._last_T` and `mass_flow_override` on *rejected* overshoot trials. This breaks Armijo descent and aborts solvable runs with `ModelError` if a full step `s = 1` momentarily reverses a branch flow before backtracking can halve `s`.

9. **`StreamTerm` Dittus–Boelter heating flag averages `0 K` for empty cells and uses a single global flag**
   - **Where:** [stream.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/flow/stream.py#L354-L359), [correlations.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/convection/correlations.py#L332-L349)
   - **Cause:** Fluid cells with no wall edges get `wall = 0.0` (0 K), which is included in `np.mean(wall) > np.mean(T_up)`. With ≥15% unheated/empty cells on a heated water stream, `heating` flips from `True` ($n=0.4$) to `False` ($n=0.3$), causing a ~20% systematic error in $h$.

10. **`inclined_natural` produces `NaN` for $|\theta| > 90^\circ$ and misses validity warnings for $\theta < -60^\circ$**
    - **Where:** [evaluator.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/convection/evaluator.py#L141-L143), [correlations.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/convection/correlations.py#L628), [calculator.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/convection/calculator.py#L235-L238)
    - **Cause:** $g \cos\theta < 0$ for $|\theta| > 90^\circ$ makes $\mathrm{Ra} < 0$, so `Ra**(1/6)` evaluates to `NaN` and poisons $K$ and $F$. Meanwhile validity is `{"theta_deg": (None, 60)}`, omitting the `-60` lower bound.

#### Geometry, Meshing & Validation

11. **DXF `LWPOLYLINE` major arcs ($|\text{bulge}| > 1$, sweep $> 180^\circ$) place the arc center on the wrong side of the chord**
    - **Where:** [dxf.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/geometry/dxf.py#L300-L309)
    - **Cause:** `side = math.copysign(radius - sagitta, bulge)` discards the negative sign of `radius - sagitta` when `sagitta > radius`, mirroring the arc center across the chord. Reproduced: a 253.7° CCW arc (`bulge = 2.0`, true area 4.21 m²) silently imports as a corrupted 0.70 m² surface (6× too small). Fix: `side = (radius - sagitta) * (1.0 if bulge > 0.0 else -1.0)`.

12. **Structured meshing (`_apply_structured`) is order-dependent across adjacent surfaces and misses surfaces with holes**
    - **Where:** [mesher.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/meshing/mesher.py#L141-L171)
    - **Cause:** Auto-computed divisions (`round(measure / global_size)`) are committed to shared edges before propagating explicit `curve_divisions` from later surfaces in `structured_surfaces`, causing spurious `"opposite sides have different numbers of divisions"` failures depending solely on list order. Also, checking only `len(boundary) in (3, 4)` misses a 3-sided outer boundary containing a 1-curve circular hole (4 boundary curves total), crashing inside gmsh.

13. **`api.solve(model, mesh)` silently skips all validation when `built=None` (default), and `validate()` has major coverage & correctness flaws**
    - **Where:** [api.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/api.py#L472-L474), [validate.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/model/validate.py#L85-L281), [settings.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/model/settings.py#L143-L151)
    - **Cause:**
      - Calling `api.solve(model, mesh)` (the documented `Data §11` signature) bypasses `validate()` completely—axisymmetric `x < 0`, negative $k/\rho/c_p$, radiation `T <= 0`, and duplicate fixed temperatures all go unchecked.
      - Inside `validate()`:
        - All non-`FixedTemperature` BCs accept selection dims `(0, 1, 2)` ([validate.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/model/validate.py#L212)), so `HeatFlux` on a surface or `HeatGeneration` on a curve passes with zero errors.
        - Fluid lookup is case-sensitive (`bc.fluid not in library.fluids()`), contradicting case-insensitive `library.fluid()`—`fluid="air"` passes `api.htc`/solver but is blocked by `validate()`.
        - `_sample(fn)` checks only `t = 0.0`, missing negative Kelvin values reached later in a time `Table`.
        - `_extremes()` uses Python `min(values)`, where `min([300.0, nan]) == 300.0`, letting `NaN` material properties pass positivity checks.
        - `dt_min <= 0`, `time_tol <= 0`, `max_dT_per_step <= 0`, `rtol <= 0`, `ttol <= 0` are unchecked (`dt_min = 0` underflows to `0.0` in `newton_failed()` and crashes with `ZeroDivisionError`).
        - `Stream`, `FlowNetwork`, `InitialCondition`, temperature-dependent `Contact.conductance`, empty geometry/BC selections, and duplicate BC/stream/contact names are unvalidated.

#### GUI

14. **Viewport axes permanently shrinks by ~20% on every `set_field()` call (colorbar layout leak)**
    - **Where:** [viewport_mpl.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/viewport_mpl.py#L447-L460), [viewport_mpl.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/viewport_mpl.py#L614-L617)
    - **Cause:** `self._ax` is created with `fig.add_axes(AXES_RECT)` (width `0.98`). Each `fig.colorbar(mappable, ax=ax, ...)` steals ~20% of `ax`'s width, and `_clear_layer("results")` removes the colorbar without restoring `self._ax.set_position(AXES_RECT)`. Width shrinks monotonically (`0.98 → 0.78 → 0.63 → 0.50 → ...`), collapsing the viewport to a sliver during transient animation playback or slider scrubbing.

15. **`File > New` / `Open` / `Examples` never clears Result objects, Probes, unit-follow state, or an open `ResultPanel`**
    - **Where:** [results_tools.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/results_tools.py#L340-L395), [panels.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/panels.py#L193-L199)
    - **Cause:** `ResultController._on_results_changed()` sets `self._results = None` without clearing `self.objects`, `self.shown`, `self.probes`, or `results.probe`. Result nodes from Model A remain in Model B's tree and Properties panel.

16. **Background `Document.set_built` clobbers concurrent selection edits; `GeometryController` async races on model switch or failed build**
    - **Where:** [document.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/document.py#L290-L305), [geometry_tools.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/geometry_tools.py#L353-L383)
    - **Cause:** `set_built` compares only `source_json["geometry"] == current["geometry"]` and overwrites `self.model.selections` with the worker's stale copy—discarding any selection edited while gmsh was building. Furthermore, `_async_built` lacks document-generation tracking (can attach Model A's geometry to Model B), and `_async_failed` drops pending rebuilds for a valid edit made while an invalid build was failing.

17. **Impossible to switch Contour colour scale to "Manual" from any uniform field (e.g., transient step 0)**
    - **Where:** [results_tools.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/results_tools.py#L576-L586), [results.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/property_panels/results.py#L238-L240)
    - **Cause:** Switching to `"Manual"` seeds `vmin`/`vmax` from `_auto_range` (where `vmin == vmax` on a uniform field) and immediately rejects `not new.vmin < new.vmax`, reverting the combo box back to `"Auto"` so the min/max boxes remain read-only.

18. **`MplSceneView._reset_overlays` does not clear `_sel_tags`, and `ChartController` retains stale `selected_nodes` across remeshes / new models**
    - **Where:** [viewport_mpl.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/viewport_mpl.py#L986-L990), [chart_tools.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/chart_tools.py#L165), [chart_tools.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/chart_tools.py#L449-L456)
    - **Cause:** Remeshing coarser or opening a new model leaves old node indices in `ChartController.selected_nodes` and old entity tags highlighted in the viewport, causing `Nodal history...` to plot wrong nodes or fail with out-of-range indices.

19. **`BackgroundTask.shutdown()` fails to park timed-out `QThread` (Qt process-abort risk)**
    - **Where:** [worker.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/worker.py#L261-L273)
    - **Cause:** Unlike `SerialWorker.shutdown()`, `BackgroundTask.shutdown()` never parks a thread that exceeds `JOIN_TIMEOUT_MS`; destroying the running `QThread` on window close triggers Qt's fatal abort.

---

### 2.2 Medium-Severity Bugs & Inconsistencies

#### Physics, Solver & Results I/O
- **Silent ignored arguments in material properties & integral loads:** [properties.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/physics/properties.py#L19-L20) calls `fn(T=T)` without rejecting time/space `Table`/`Expression` on `Material`; [body_loads.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/physics/body_loads.py#L77-L99) and [surface_loads.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/physics/surface_loads.py#L94-L116) fail to reject spatial `Expression`s on `HeatPower`/`HeatFlow`, silently evaluating at `(0, 0)`.
- **Discontinuity detector `_jumps()` false positives & false negatives:** [transient.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/transient.py#L256-L281) falsely triggers $\theta = 1$ on smooth periodic loads returning near their start value (e.g., $\sin(\pi t)$ on $[0, 1]$), misses right-continuous step jumps `where(t >= t_jump, ...)` when a step lands on `t_jump`, fails when $\Delta t / t < 10^{-8}$ (float64 underflow of `t + 1e-8*dt`), and triples assembly cost while mutating `FlowProvider` state.
- **Mixed-element (`T3 + Q4`) `per_region` IC double-counting:** [initial.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/initial.py#L34-L52) averages over `(tag, ElementBlock)` pairs instead of distinct regions, weighting a mixed-element region twice at interfaces.
- **Dead `Term.results()` outputs:** [run.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/run.py#L65-L89) only collects `provider.results()`, never `term.results()`, so `ContactTerm` (`contact_heat:<name>`) and `CorrelationConvectionTerm` (`h_mean:<name>`) results are never written to HDF5.
- **Premature `/meta` overwrite on restart failure:** [results_writer.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/results_writer.py#L338-L350) overwrites `/meta/model`, `/meta/model_hash`, and `/meta/settings` inside `_reopen()` before step 1 succeeds; a failed restart corrupts the existing file's metadata.
- **Contact split leaves `node_sets` and `point_nodes` un-updated:** [contact_split.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/core/contact_split.py#L252-L260) leaves 0D point BCs at an outer contact corner constraining only the lower-region node; also line 133 raises raw `ValueError` on orphaned contact facets, and `partner` keying by `(tag, node)` can collide at multi-contact junctions on hand-built meshes.
- **Quadratic `L3` boundary overshoot (`T_film <= 0 K`) aborts Newton:** [fluid_props.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/convection/fluid_props.py#L107-L110) raises `ModelError` when `N · T_e <= 0` at a Gauss point (possible with positive nodal `T` because quadratic `L3` shape functions go down to `-0.125`), bypassing `newton()`'s line-search backtracking and `transient.py`'s time-step cutback.
- **Missing input guards in convection & flow:** Negative velocity in [evaluator.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/convection/evaluator.py#L296-L298) (`NaN`), negative `C` / `0**(-n)` in `power_law` ([evaluator.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/convection/evaluator.py#L187-L190)), axisymmetric curve on `r = 0` (`ZeroDivisionError` / `0/0` in [evaluator.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/convection/evaluator.py#L258) and [stream.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/flow/stream.py#L291)), unchecked `stream.mass_flow.depends_on_T` ([stream.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/flow/stream.py#L206-L215)), unchecked negative `K_minor`/`roughness`/self-loops in [network.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/flow/network.py#L165-L176), and missing duct validity warnings in [stream.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/flow/stream.py#L349-L362).

#### Geometry, Model & Post-Processing
- **Selection `resolve()` ignores `Fingerprint.bbox` and allows duplicate tag matches:** [selections.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/model/selections.py#L86-L99), [selections.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/model/selections.py#L124-L141) — concentric equal-area surfaces or 90°-rotated rectangles are misidentified or mapped to duplicate tags `[1, 1]`.
- **`Transform` ownership & `curve_ends` bugs:** [builder.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/geometry/builder.py#L336-L361) drops point ownership on `Transform(copy=False)` and omits `curve_ends` on `Transform(copy=True)`; [geometry_edit.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/model/geometry_edit.py#L28-L50) restricts `Transform` to `SURFACE_OPS`, blocking transformed points/curves in `Line`/`SurfaceFromCurves`.
- **DXF duplicate overlapping segments & fit-point spline nesting:** [dxf.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/geometry/dxf.py#L553-L599) lets two coinciding segments form a degenerate zero-area OCC surface; [dxf.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/geometry/dxf.py#L314-L318) uses un-sampled fit points for `nest_loops` polygon containment.
- **`quality.report()` turns `+inf` aspect ratio into finite `1.79769e+308`:** [quality.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/meshing/quality.py#L131) calls `np.nan_to_num(aspect, nan=np.inf)` without `posinf=np.inf`, breaking `np.isfinite` masking in `values_in_block_order`.
- **`Expression` accepts `10**400` and `1e309` (`inf`):** [functions.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/core/functions.py#L205-L207) crashes later at call time with uncaught `OverflowError`.
- **Serialization flaws:** [serialize.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/model/serialize.py#L44), [serialize.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/model/serialize.py#L123-L155), [serialize.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/model/serialize.py#L193) — `Literal[1, 2]` accepts JSON `true` (`True in (1, 2)`), non-finite floats pass, `dict(data)` is a shallow copy before `migrate()`, and NumPy integer/bool scalars are rejected by `to_json`.
- **User fluids completely unreachable:** `load_user_library()` reads user fluids from `materials.json`, but [library.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/materials/library.py#L51-L53) only queries `_builtin_fluids()` everywhere.
- **CLI & API suppress warnings:** [cli.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/cli.py#L128) defaults logging to `logging.ERROR` (hiding all correlation, fluid-clamp, and oscillation warnings without `-v`), and [api.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/api.py#L473) discards validation warnings.
- **Post-processing & export bugs:**
  - [results.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/post/results.py#L98-L154): `@cached_property` on `mesh`/`_reaction_names` goes stale if the file is re-solved or restarted, contradicting the docstring.
  - [flow.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/post/flow.py#L115-L131): `wall_temperature` produces sawtooth plots on unstructured asymmetric two-wall channels (1e-9 nodal `s`-matching) and crashes with `ValueError` on empty `mesh.facets`.
  - [export.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/post/export.py#L170-L171), [export.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/post/export.py#L288-L293): `history_csv` does not escape commas in BC names; `vtu()` does not XML-escape filenames in `.pvd`; 0-step files and `fps=nan` raise raw exceptions.
  - [plots.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/post/plots.py#L451-L454): `_selected_temperatures` opens/closes HDF5 3× per step and decompresses the entire mesh on every step.

#### GUI Medium-Severity Issues
- **Renaming a stream breaks `FlowNetwork` branch references:** [tree.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/tree.py#L630-L641) updates `region.material` on material rename, but not `NetBranch.stream` on stream rename.
- **`ModelTree.add_stream()` creates invalid `in_plane` stream with `path=None`:** [tree.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/tree.py#L579-L594) when `streams[0]` is `through_plane`.
- **`CorrelationPanel` offers forbidden `"duct_internal"` as a BC choice:** [correlation.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/property_panels/correlation.py#L173-L179).
- **`SelectionEditor` UX/state bugs:** [selection_editor.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/property_panels/selection_editor.py#L229-L302) updates its displayed label even when `Apply` fails, calls `view.set_selection_mode` without syncing the toolbar, never cleans up pick mode on panel switch, and defaults `FixedTemperature` to Point mode instead of Curve mode.
- **Display-unit conversion bugs:** [results_tools.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/results_tools.py#L351), [flow_results.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/flow_results.py#L176-L184), [function_editor.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/property_panels/function_editor.py#L262-L279) — manual contour limits corrupt on unit switch when file units differ from document units; `probe_at`/`FlowResultsWindow`/`ResultPanel` mix document and file units; `FunctionEditor.set_units()` never refreshes `FunctionPreview` and skips min/max validation for `Table` entries.
- **`NewStreamDialog` accepts `flow_area = 0` / `wetted_perimeter = 0`**, and `network.py:parse_number` prints raw SI bounds and rejects decimal commas: [new_stream.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/dialogs/new_stream.py#L120-L133), [network.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/property_panels/network.py#L83-L98).
- **`FlowResultsWindow` stream charts:** [charts.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/charts.py#L248-L277), [flow_results.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/flow_results.py#L224-L234) — dead enabled "Export CSV..." button, dropped save errors, leaked window references, and never marked out-of-date on new results.

---

### 2.3 Low-Severity Issues (Summary)
- **Short-duration time tolerances (`<= 1e-9 s`):** [run.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/run.py#L152-L154), [run.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/run.py#L249) floor tolerance at `1e-9 s` (separate from `M11.16` in `timestep.py`), breaking `OutputSelector` and `read_restart_state` for sub-nanosecond runs.
- **1-ULP rounding mismatch on mandatory times:** [transient.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/transient.py#L413) evaluates at `controller.t + dt` while `accept()` snaps to `next_mandatory`.
- **`InitialCondition(kind="from_results")`:** [initial.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/initial.py#L55-L72) checks only node coordinates (not connectivity/axisymmetry like `M11.11`) and does not guard empty `times`.
- **`calculator.htc` side effects:** [calculator.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/convection/calculator.py#L5-L6) claims *"It never logs"* yet logs `WARNING` and mutates caller `Fluid._clamp_warned`.
- **NumPy scalar rejection:** [functions.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/core/functions.py#L74) rejects `np.int64` / `np.float32`; [forms.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/core/forms.py#L190-L209) `parse_xy_list` accepts `NaN`/`inf`.
- **Minor GUI lifecycle gaps:** `SolveProgressDialog` has no `closeEvent` handler; `SolveController._on_cancelled` misreports steady cancels because `0.0 >= 0.0`; `MeshPanel` quality-colour checkbox desyncs on panel return and `Add refinement` can append an empty selection; `GeometryOpDialog` & `MaterialLibraryDialog` ignore live unit switches.
- **Minor CLI/API gaps:** `api._select` accepts duplicate tags; Windows reserved names (`CON`, `NUL`, etc.) fail in `api.solve` default temp path; `thermalfea solve -o bad_dir/out.h5` solves before failing with raw `OSError`; `thermalfea solve` omits stream summary output; `thermalfea info` omits streams/contacts/enclosures counts.
- **`examples/pump_closure/showcase/` hygiene:** [fluxlib.py](file:///d:/Documents/Projects/thermal-fea/examples/pump_closure/showcase/fluxlib.py#L3-L13) hardcodes conductivities instead of using `Results.element_flux()`; [common.py](file:///d:/Documents/Projects/thermal-fea/examples/pump_closure/showcase/common.py#L74-L80) leaks an open `h5py.File` and hardcodes `reactions/0..4`; [fig03_history.py](file:///d:/Documents/Projects/thermal-fea/examples/pump_closure/showcase/fig03_history.py#L78-L80) contains dead `if False` scratch code and `print()` statements; README cites an absent `AP1000_Closure_Thermal_Sketches.pdf`.

---

## 3. Inconsistencies, Data Fidelity & Architectural Drift

### 3.1 `PLAN.md §7` (Future 3D / Multi-Physics Extensibility) Gaps
Despite strong adherence in the kernel (`V-37`), several modules hardcode 2D or single-field assumptions:
- **Rules 1 & 3 (dimension-agnostic / generic facets):** [timescales.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/physics/timescales.py#L36) assumes facets are 2-node edges (misses 2/6 edges on `TET4` and 6/12 on `HEX8`); [mesher.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/meshing/mesher.py#L29), [mesher.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/meshing/mesher.py#L184-L193) hardcode dims `(2, 1, 0)` and 2-node edge reversal; [export.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/post/export.py#L52-L54) truncates coordinates/fluxes to `[:, :2]`; [functions.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/core/functions.py#L38) & [evaluate.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/physics/evaluate.py#L34-L35) drop `z`; [validate.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/model/validate.py#L39) hardcodes `SURFACE_DIM, CURVE_DIM = 2, 1`.
- **Rules 4, 5 & 9 (named fields, physics-agnostic drivers, generic results):** [nonlinear.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/nonlinear.py#L176) hardcodes `trial.min() > 0.0` across all DOFs (blocks signed fields such as displacement or voltage); [results_writer.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/solver/results_writer.py#L295-L395) hardcodes single-component `"T"` and routes all non-`T_fluid` extras into `/fluid`.
- **Rule 6 (registry-driven BCs):** [validate.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/model/validate.py#L211-L244) hardcodes `isinstance` checks on concrete BC classes instead of reading `selection_dims` / capabilities from the registry.
- **Layer test gaps ([test_layers.py](file:///d:/Documents/Projects/thermal-fea/tests/unit/test_layers.py)):** Does not guard Plan §7 rule 11 (only `solver/linear.py` imports `scipy.sparse.linalg`), no `print()` / `matplotlib.pyplot` in `src/`, or runtime `gmsh` leaks via `gui/` → `geometry.builder`.

### 3.2 Documentation & Material Data Discrepancies
- **Air pressure reference mismatch:** [data-model.md](file:///d:/Documents/Projects/thermal-fea/docs/data-model.md#L219) labels Air as **"1 atm"** (101.325 kPa), while [fluids.json](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/materials/data/fluids.json#L16-L26) densities (`1.1614 kg/m³` at 300 K) are **1 bar (100 kPa)** (Incropera Table A.4, ~1.3% lower). Water's 5-point `280–360 K` table (20 K steps) yields ~5.4% μ and ~7.4% β linear-interpolation error at 290 K and omits `273.15–280 K` and `360–373.15 K`.
- **Geometry Transform units contradiction:** [getting-started.md](file:///d:/Documents/Projects/thermal-fea/guide/getting-started.md#L66-L67), [limitations.md](file:///d:/Documents/Projects/thermal-fea/guide/limitations.md#L115), and `guide/units.md` state that Transform parameters are always SI, whereas the creation dialogs ([geometry_defs.py](file:///d:/Documents/Projects/thermal-fea/src/thermalfea/gui/geometry_defs.py#L73-L79)) **do** convert lengths and angles to display units (only the property panel is SI-only).
- **Heat-flow sign contradiction in the published guide:** [theory.md](file:///d:/Documents/Projects/thermal-fea/docs/theory.md#L187-L191) (copied verbatim into `guide/theory.md`) defines boundary-set heat flows as positive *out*, contradicting [index.md](file:///d:/Documents/Projects/thermal-fea/guide/index.md#L76), [getting-started.md](file:///d:/Documents/Projects/thermal-fea/guide/getting-started.md#L103), and the code (positive *in*, `Q11`).
- **Stale specs:** [data-model.md](file:///d:/Documents/Projects/thermal-fea/docs/data-model.md#L341-L342) documents `/fluid/<stream>` and `/reactions/<bc>` (code uses numeric `/fluid/<i>`, `/reactions/<i>` with `name` attrs) and omits `CorrelationConvection.params` and `Stream.h_override`; [PLAN.md](file:///d:/Documents/Projects/thermal-fea/PLAN.md#L106) lists `thermalfea export` (unimplemented); [theory.md](file:///d:/Documents/Projects/thermal-fea/docs/theory.md#L174) states the GUI displays suggested $\Delta t_0$ (not implemented); [getting-started.md](file:///d:/Documents/Projects/thermal-fea/guide/getting-started.md#L109) says right-click `Flow` to add a stream (actually `Flow > Streams`).

---

## 4. Opportunities for Enhancement & Expansion

### A. Near-Term Hardening & Quick Wins (Highest ROI)
1. **Fix the 19 high-severity bugs above** alongside open tasks `M11.12`–`M11.16`—especially `F_ref` scaling, colorbar axes restoration, `FlowNetwork` restart + line-search decoupling, DXF major arcs, `validate()` gaps, and `Mesh.validate()` on curved elements.
2. **Persist `Term.results()` generically in HDF5 (`/term_results` or `/contacts/<i>` and `/convection/<i>`):** Surfaces `contact_heat` (needed by the pump-closure showcase so it can stop poking private `ContactTerm._sides`) and `CorrelationConvection` `h_mean(t)` in the GUI, summary, and exports.
3. **Clean up packaging & CLI:** Declare `Pillow` explicitly, move `pandas` out of core dependencies (replace with stdlib `csv` in `showcase/`), add a `thermalfea-gui` console/gui script, default CLI logging to `WARNING` (with `-q`/`-v`), and add `thermalfea validate`, `thermalfea summary`, and `thermalfea export`.
4. **Harden `test_layers.py` & add regression tests** for viewport axes geometry stability, document reset cleanup, async build races, uniform-field manual range, and multi-scale linear solves.

### B. Performance Optimization (Targeting `PLAN.md §6` Criterion 6: 100k nodes, 100 steps < 60 s)
1. **Split constant vs. time-dependent assembly in `transient.py`:** Currently *any* time-dependent load forces full re-assembly of constant `ConductionTerm` `K` on every step (and 3× per step when $\theta < 1$ due to `_jumps()`), plus an $O(\mathrm{nnz})$ sparse matrix diff. Pre-assembling constant terms once cuts linear transient assembly cost dramatically.
2. **Eliminate redundant per-step work:** Cache `A_fp = A[free][:, fixed]` alongside the SuperLU factorization; eliminate double `coefficient()` evaluation in `ConvectionTerm` (`conductance()` + `load()`); cache COO-to-CSR index permutations in `Assembler` across nonlinear iterations; open HDF5 once and slice only requested nodes in `_selected_temperatures` / `field_range`.
3. **Iterative / modern sparse solvers behind `solver/linear.py`:** Add optional `pypardiso` (Intel MKL PARDISO) or preconditioned BiCGSTAB/CG with AMG (`pyamg`) / ILU and diagonal equilibration—essential both for 100k-node 2D speed and future 3D scaling.

### C. Physics & Modeling Expansions
1. **Complete deferred core physics (`M9` & `M10.2`):** Surface-to-surface enclosure radiation (hemicube / crossed-strings view factors with shadowing) and enthalpy/apparent-heat-capacity phase change (latent heat, fixing `Material.depends_on_T` to include `phase_change`).
2. **Richer thermal contact & convection/flow:**
   - Temperature-dependent contact conductance $h_c(\bar{T})$ (mean interface temperature) and gap-radiation + gas-conduction contact models.
   - Cell-wise $c_p(T)$ for large gas temperature rises, automatic flow-reversal upwinding in `StreamTerm`, junction thermal mixing (downstream `T_inlet` from upstream network branch outlets), and unheated/header/pump network branches.
   - User-defined fluids wired end-to-end (embedded in `.tfea` for model portability), denser fluid tables (10 K Water steps `273–373 K`, `700/900 K` Air points, plus glycol-water, thermal oil, N₂, He), orthotropic FR-4, and `T`-dependent solid tables.
   - Additional correlations: developing duct entry length (Hausen/Sieder-Tate), concentric annuli, mixed convection, impinging jets, external sphere (Whitaker).
3. **Geometry & Meshing upgrades:**
   - Two-pass constraint propagation for `structured_surfaces` + single-wire topology check.
   - Boundary-layer / inflation meshing (`gmsh` `BoundaryLayer` field) for steep thermal boundary layers.
   - DXF `INSERT`/blocks, `ELLIPSE`, 2D `POLYLINE`, `$INSUNITS` auto-scale option, and layer-to-Selection auto-grouping.
   - 2D CAD ops: corner fillet/chamfer, linear/circular pattern arrays, and offset curves.
   - `Fingerprint.bbox` + 1-to-1 matching in `selections.resolve()` to eliminate ambiguous entity re-identification.

### D. GUI, Post-Processing & Path to 3D
1. **Instant results re-attachment on `File > Open`:** Load the embedded `/mesh` directly from `<model>.tfea.h5` when `results_match()` succeeds, avoiding forced remeshing and gmsh mesh-order drift.
2. **Unified `ViewportToolManager`:** Centralize exclusive activation of `SelectionEditor`, `StreamPanel` path picking, `Probe`, `ChartController` path picking, and `GeometryOpDialog` placement, keeping toolbar buttons synchronized.
3. **Richer post-processing:** Area-weighted cell-based `wall_temperature()` in `post/flow.py`, 1D stream polylines/fluid temperature exported into `.vtu`, `Results.reload()` / mtime cache invalidation, `SolutionPanel` display of suggested $\Delta t_0$, and `api` exposure of missing headless post helpers (`validate`, `mesh_quality`, `sample_path`, `probe`, `plot_stream`, `stream_summary`, `solve_network`).
4. **Clean path to headless 3D (`M12`):** Fixing the small set of `PLAN.md §7` violations identified in §3.1 (`timescales.py`, `mesher.py`, `functions.py`/`evaluate.py` `z`-coord, `results_writer.py`, `export.py`, `nonlinear.py` positivity hook) directly unlocks headless 3D thermal FEA with `TET4`/`TET10`/`HEX8` + ParaView VTU viewing before needing a PyVista/VTK 3D viewport.
