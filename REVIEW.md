# ThermalFEA code review

Reviewed November 20, 2026. Ruff passed and all 2,002 tests passed. Targeted checks reproduced the nine findings below. Checks that wrote model or results files used disposable copies.

## High priority

### 1. The CLI can overwrite its input model

Running `thermalfea solve slab.tfea -o slab.tfea` on a disposable copy exited successfully and replaced the JSON model with HDF5 results. The CLI passes the output path to the writer without checking whether it points to the input file. Reject paths that refer to the same file before starting the solve. [CLI output selection](src/thermalfea/cli.py#L33) · [HDF5 writer](src/thermalfea/solver/results_writer.py#L185)

### 2. Restart accepts an incompatible mesh

The restart check accepted changes to element connectivity and to the axisymmetry flag when node coordinates and temperature counts stayed the same. The solver can then append temperatures computed on the new mesh while post-processing reads the original mesh from the file. Check element types, connectivity, region assignments, and analysis geometry before appending. [Restart mesh check](src/thermalfea/solver/results_writer.py#L119)

### 3. Flux recovery uses the old conductivity after restart

After restarting a transient run with conductivity increased from 50 to 100 W/(m·K), the embedded model reported 100 while the region data used for flux recovery still reported 50. For the same temperature gradient, the reported flux magnitude for the resumed step is half the correct value. Reject incompatible material changes on restart or store the material data applicable to each portion of the history. [Restart metadata update](src/thermalfea/solver/results_writer.py#L258) · [Recovery material lookup](src/thermalfea/post/results.py#L146)

## Medium priority

### 4. Renaming a stream breaks its history on restart

Renaming the stream `lower` to `upper` and continuing the run succeeded. The old stream had a missing outlet temperature at the new step, and the new stream lacked path coordinates and a degree-of-freedom mapping. Restart loads fluid temperatures using the file's numeric indices. Verify stream identities and mappings against the current model before writing any steps. [Fluid state restoration](src/thermalfea/solver/run.py#L228)

### 5. Editing a mesh-control selection can leave the GUI mesh marked current

Changing the entities in a selection used by `structured_surfaces` or `refinements` invalidated only the results. The change detector collects dictionary keys, but these controls store selection names as values. Solve can therefore reuse a mesh generated with the previous selection. Include structured-surface names and each refinement's selection when determining which edits require remeshing. [GUI change classification](src/thermalfea/gui/document.py#L108)

### 6. Path sampling can miss a point inside the mesh

On a valid quadrilateral mesh with small cells beside a large cell, a point just inside the large cell returned element ID `-1`, the value used for points outside the mesh. The locator tries only the eight nearest element centroids, all of which can belong to neighboring cells. Add a containment search for unresolved points so sampled field plots do not acquire gaps inside the domain. [Path point locator](src/thermalfea/post/path.py#L213)

### 7. Radiation validation evaluates a spatial temperature at the origin

A boundary at `x = 1 m` with prescribed temperature `T = 300*x` is at 300 K along its entire length. With radiation enabled, validation called the expression with only the time argument, used the default coordinate `x = 0`, and blocked the solve for a temperature of 0 K. Evaluate spatial temperature expressions on the entities where they apply. [Validation sampling](src/thermalfea/model/validate.py#L89)

### 8. A zero maximum time step causes an uncaught exception

The GUI and model accept `dt_max = 0`. With a positive initial step, the controller still proposed zero and the transient slab solve raised `ZeroDivisionError` during matrix assembly. Validate that a supplied maximum is positive and consistent with the minimum before the run starts. [GUI field](src/thermalfea/model/solution_forms.py#L51) · [Step-size clamp](src/thermalfea/solver/timestep.py#L129)

### 9. A long simulation can skip an early requested output time

With an end time of `1e8 s`, a requested output at `1e-5 s`, and an initial step of `1 s`, the controller proposed the full second. Its tolerance scales with the overall run duration, so it discarded the requested time before the first step. Preserve distinct representable output times and compare against the local time when deciding whether a step has reached one. [Mandatory-time filtering](src/thermalfea/solver/timestep.py#L117) · [Next mandatory time](src/thermalfea/solver/timestep.py#L140)
