# ThermalFEA code review

Reviewed November 20, 2026. Ruff passed and all 2,002 tests passed. Targeted checks reproduced the nine findings below. Checks that wrote model or results files used disposable copies.

## Status of the findings

*Updated November 20, 2026.*

The cause named in each finding was confirmed in the code. All nine are code defects; none needs a new equation, material property or benchmark target. `docs/OPEN_QUESTIONS.md` Q28 records the findings and the owner's decisions, and each fix is a task in `docs/tasks.md`. Until a finding is fixed, the user guide lists it with a workaround (Limitations, "Known defects from the code review").

| # | Finding | Task | Status |
|---|---|---|---|
| 1 | The CLI can overwrite its input model | M11.12 | Open |
| 2 | Restart accepts an incompatible mesh | M11.11 | **Fixed** in commit f0ba6ca |
| 3 | Flux recovery uses the old conductivity after restart | M11.11 | **Fixed** in commit f0ba6ca |
| 4 | Renaming a stream breaks its history on restart | M11.11 | **Fixed** in commit f0ba6ca |
| 5 | Editing a mesh-control selection can leave the GUI mesh marked current | M11.13 | Open |
| 6 | Path sampling can miss a point inside the mesh | M11.14 | Open |
| 7 | Radiation validation evaluates a spatial temperature at the origin | M11.15 | Open |
| 8 | A zero maximum time step causes an uncaught exception | M11.12 | Open |
| 9 | A long simulation can skip an early requested output time | M11.16 | Open |

After M11.11 the full suite has 2,011 tests, and it and Ruff pass.

## High priority

### 1. The CLI can overwrite its input model

Running `thermalfea solve slab.tfea -o slab.tfea` on a disposable copy exited successfully and replaced the JSON model with HDF5 results. The CLI passes the output path to the writer without checking whether it points to the input file. Reject paths that refer to the same file before starting the solve. [CLI output selection](src/thermalfea/cli.py#L33) · [HDF5 writer](src/thermalfea/solver/results_writer.py#L185)

> **Status: open; task M11.12.** Planned fix: `thermalfea solve` exits with an error, before anything is solved or written, when the output path is the model file, and the model file is left unchanged. Until then, omit `-o` (the default is `<model>.tfea.h5`) or give another name.

### 2. Restart accepts an incompatible mesh

The restart check accepted changes to element connectivity and to the axisymmetry flag when node coordinates and temperature counts stayed the same. The solver can then append temperatures computed on the new mesh while post-processing reads the original mesh from the file. Check element types, connectivity, region assignments, and analysis geometry before appending. [Restart mesh check](src/thermalfea/solver/results_writer.py#L119)

> **Status: fixed by task M11.11 (commit f0ba6ca).** `check_same_mesh` is replaced by `check_restart_compatible` in `solver/results_writer.py`. Both `read_restart_state` and the writer's append mode use it. It opens the file read-only and runs before anything is written. Besides the node coordinates, it now compares the planar or axisymmetric flag and each element block's type, connectivity, regions and element ids. It also compares each boundary facet block's type, connectivity, entity and parent element. A difference refuses the restart with "it was computed on a different mesh (…)" and names what differs. Tests: `test_incompatible_restart_is_refused_and_leaves_the_file_alone` in `tests/unit/test_restart.py` covers connectivity, element region, the axisymmetric flag and a facet change. Each case also checks that the results file is byte-for-byte unchanged.

### 3. Flux recovery uses the old conductivity after restart

After restarting a transient run with conductivity increased from 50 to 100 W/(m·K), the embedded model reported 100 while the region data used for flux recovery still reported 50. For the same temperature gradient, the reported flux magnitude for the resumed step is half the correct value. Reject incompatible material changes on restart or store the material data applicable to each portion of the history. [Restart metadata update](src/thermalfea/solver/results_writer.py#L258) · [Recovery material lookup](src/thermalfea/post/results.py#L146)

> **Status: fixed by task M11.11 (commit f0ba6ca).**
>
> **Decision:** the owner chose the first option, to reject incompatible changes (Q28.1). This also settled the question Q25.4 had left open. A restart is refused when any region's material, thickness or material angle differs from the region data stored in the file. Loads and solver settings may still change, so the region data in the file always matches every stored step, and the results-file layout is unchanged.
>
> **Code:** the region data written when the file is created and the data compared on restart come from one helper, `region_data`, so the two cannot drift apart.
>
> **Tests:** the conductivity change from 50 to 100 W/(m·K), a changed thickness and a changed material angle are each refused and leave the file unchanged. `test_changed_load_still_continues` checks that a changed load is still accepted.

## Medium priority

### 4. Renaming a stream breaks its history on restart

Renaming the stream `lower` to `upper` and continuing the run succeeded. The old stream had a missing outlet temperature at the new step, and the new stream lacked path coordinates and a degree-of-freedom mapping. Restart loads fluid temperatures using the file's numeric indices. Verify stream identities and mappings against the current model before writing any steps. [Fluid state restoration](src/thermalfea/solver/run.py#L228)

> **Status: fixed by task M11.11 (commit f0ba6ca).** `check_restart_compatible` compares the streams of the model with the `/fluid` groups of the file. It uses the step-independent data of each stream, which is the same data the writer stores when the file is created. Names must match, and for each stream the mode, the degree-of-freedom numbers and the path coordinates must match. Otherwise the restart is refused before anything is written, with "the streams of the model are not those of the results file (…)". The existing checks in `read_restart_state` remain as a second line of defence. Test: `test_renamed_stream_refuses_the_restart` in `tests/verification/test_restart_api.py` renames `lower` to `upper`. The restart is refused and the file is unchanged.

### 5. Editing a mesh-control selection can leave the GUI mesh marked current

Changing the entities in a selection used by `structured_surfaces` or `refinements` invalidated only the results. The change detector collects dictionary keys, but these controls store selection names as values. Solve can therefore reuse a mesh generated with the previous selection. Include structured-surface names and each refinement's selection when determining which edits require remeshing. [GUI change classification](src/thermalfea/gui/document.py#L108)

> **Status: open; task M11.13.** Planned fix: `classify_change` also counts the selection names listed in `structured_surfaces` and in each refinement's `selection`. Editing such a selection then returns `"mesh"`, and editing an unused selection still returns `"results"`. Until then, generate the mesh again after editing such a selection.

### 6. Path sampling can miss a point inside the mesh

On a valid quadrilateral mesh with small cells beside a large cell, a point just inside the large cell returned element ID `-1`, the value used for points outside the mesh. The locator tries only the eight nearest element centroids, all of which can belong to neighboring cells. Add a containment search for unresolved points so sampled field plots do not acquire gaps inside the domain. [Path point locator](src/thermalfea/post/path.py#L213)

> **Status: open; task M11.14.** Planned fix: a point that is not inside any of the nearest candidates is tested against every element whose bounding box holds it, before it is reported as outside the mesh. The test uses the reviewer's case, a point just inside a large quadrilateral next to small ones.

### 7. Radiation validation evaluates a spatial temperature at the origin

A boundary at `x = 1 m` with prescribed temperature `T = 300*x` is at 300 K along its entire length. With radiation enabled, validation called the expression with only the time argument, used the default coordinate `x = 0`, and blocked the solve for a temperature of 0 K. Evaluate spatial temperature expressions on the entities where they apply. [Validation sampling](src/thermalfea/model/validate.py#L89)

> **Status: open; task M11.15.** Planned fix: a position-dependent temperature is evaluated at the points of the entities it applies to. When that is not possible, it is treated as unknown, as a temperature-dependent value already is, so it can never block a solve wrongly. A constant 0 K is still refused.

### 8. A zero maximum time step causes an uncaught exception

The GUI and model accept `dt_max = 0`. With a positive initial step, the controller still proposed zero and the transient slab solve raised `ZeroDivisionError` during matrix assembly. Validate that a supplied maximum is positive and consistent with the minimum before the run starts. [GUI field](src/thermalfea/model/solution_forms.py#L51) · [Step-size clamp](src/thermalfea/solver/timestep.py#L129)

> **Status: open; task M11.12.** Planned fix: validation reports an error for `dt_max <= 0`, for `dt_max < dt_min`, and for `initial_dt <= 0` when it is set. The error is shown in the window and blocks the solve before it starts. Until then, leave the largest time step empty or set it positive and no smaller than the smallest step.

### 9. A long simulation can skip an early requested output time

With an end time of `1e8 s`, a requested output at `1e-5 s`, and an initial step of `1 s`, the controller proposed the full second. Its tolerance scales with the overall run duration, so it discarded the requested time before the first step. Preserve distinct representable output times and compare against the local time when deciding whether a step has reached one. [Mandatory-time filtering](src/thermalfea/solver/timestep.py#L117) · [Next mandatory time](src/thermalfea/solver/timestep.py#L140)

> **Status: open; task M11.16.** Planned fix: the step controller filters and finds mandatory times with a tolerance relative to the local time, not the length of the run. The test uses the reviewer's case: end 1e8 s, output at 1e-5 s, first step 1 s. The first step must land on 1e-5 s and that time must be stored. Until then, set the initial time step no larger than the first output time.
