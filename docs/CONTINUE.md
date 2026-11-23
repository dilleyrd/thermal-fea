# Continuing the work: state on 2026-11-21

This file is for an agent that starts with a clean context. It records what was done in
the sessions of 2026-11-17 to 2026-11-21, the owner's standing instructions, and exactly
where to pick up. It adds to the project documents and does not replace them.

Read in this order:
1. `CLAUDE.md`, which holds the rules.
2. `PLAN.md`.
3. `docs/handover.md`: the working method, the pitfalls, and the state in §3.
4. This file.
5. Only the documents that your task in `docs/tasks.md` names.

## 1. Where things stand

- **Repository:** branch `main`, remote `origin` = https://github.com/dilleyrd/thermal-fea.
  The last commits are 3fb2ba1 (the review status in the documentation) and 4f5e751 (this
  note). The working tree was clean and `main` matched `origin/main` when it was
  written.
- **Checks:** `.\scripts\check.ps1` runs ruff and then the whole pytest suite. It last
  passed with 2011 tests in about 90 s.
- **Tasks:** 81 are ticked in `docs/tasks.md`. The latest are M10.6 (restart), M11.4
  (user guide) and M11.11 (restart compatibility).
- **User guide:** an MkDocs site with its sources in `guide/`, published at
  https://dilleyrd.github.io/thermal-fea/. Section 4 of this file explains how to publish
  it.

## 2. The owner's standing instructions

These hold until the owner withdraws them.

- **Remote session.** The owner manages the machine remotely. Run nothing that could
  drop the connection:
  - no network, power or session commands;
  - never kill a process by name;
  - never open a GUI window. Set `QT_QPA_PLATFORM=offscreen`, use the Agg backend, and
    never run `mkdocs serve`.

  Give long commands a timeout, for example `timeout 600 ... pytest`.
- **Use cheaper subagents** for work that needs no advanced reasoning:
  - [A] tasks go to haiku, [B] tasks to sonnet;
  - [C] tasks, human gates and the review of a subagent's diff stay on the main model;
  - always review a subagent's diff and run `check.ps1` yourself before you commit.
- **On hold; do not start until the owner says so:**
  - M9 (enclosure radiation);
  - M10.2 (phase change).

  M10.5 and M11.7–M11.10 were released on 2026-11-22 (Q29.15). Version 1 excludes M9 and
  M10.2 and their verification cases.
- **No scripting features.** Do not build anything associated with scripting: export of
  a model as a script, `api.add_*` wrappers, sweep helpers, public access to the matrices.
- **Order of work.** The owner directs the order. On 2026-11-20 they asked for the review
  fixes to be done as tasks M11.11–M11.16, starting with M11.11. They are therefore
  taking precedence over the first unchecked task in the list.
- **Commits:** one task per commit, titled `M<n>.<k>: <task title>`. Push to `origin` and
  never force-push. End every message with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Privacy:** never put the owner's name, email or other personal details into
  anything sent to an outside service.
- **`.claude/settings.json`** is the owner's local Claude Code settings. It is in
  `.gitignore`; never commit it.

## 3. What was done in these sessions

In order:

1. **Pump main-closure example**, `examples/pump_closure/`: an axisymmetric assembly
   with six contacts, a 6 h heat-up, the steady hot case and a study of the seat
   conductance.
   - Its results files `out/*.h5` are committed; `.gitignore` excludes `*.h5` except
     `examples/pump_closure/out/*.h5`.
   - Its post-processed figures are in `showcase/` (scripts `fig01`–`fig07`, `common.py`,
     `fluxlib.py`). They need pandas, which was added to the dependencies in
     `pyproject.toml`.
   - The showcase scripts were cleaned up to pass ruff, and they use `np.trapezoid`
     because NumPy 2 removed `np.trapz`.
2. **User guide on GitHub Pages.** `mkdocs.yml` has `site_url`, `repo_url` and
   `edit_uri: ""`. `guide/installation.md` has a "Get the source" section.
   `tests/unit/test_guide.py` checks the navigation and a strict build.
3. **A guide page for the pump example**, `guide/examples/pump-closure.md`, with its
   images in `guide/examples/img/`. It covers the model, the boundary conditions, the
   contacts, the run settings, the results and the checks. All its inputs are marked
   illustrative.
4. **Code review**, `REVIEW.md`, with nine findings. They are recorded as Q28 in
   `docs/OPEN_QUESTIONS.md` and as tasks M11.11–M11.16.
   - **The owner's decision (Q28.1):** a restart is refused when any region's material,
     thickness or material angle has changed. Loads and solver settings may still change.
     This also settled Q25.4.
5. **M11.11, restart compatibility** (commit f0ba6ca, fixing findings 2, 3 and 4).
   - In `solver/results_writer.py`, `check_restart_compatible` replaces
     `check_same_mesh`. It opens the file read-only and runs before any write, and both
     `run.read_restart_state` and `ResultsWriter._reopen` call it.
   - It compares:
     - the mesh: nodes, element types, connectivity, element regions, element ids,
       facet blocks, and the axisymmetric flag;
     - the region data, through the helper `region_data`, which `open()` also uses;
     - the streams: the `static()` data of each provider against `/fluid`.
   - Tests are in `tests/unit/test_restart.py`
     (`test_incompatible_restart_is_refused_and_leaves_the_file_alone`, with 7 cases,
     and `test_changed_load_still_continues`) and in
     `tests/verification/test_restart_api.py` (`test_renamed_stream_refuses_the_restart`).
6. **Documentation brought up to date** (commit 3fb2ba1):
   - `REVIEW.md` has a status table and a note under each finding, saying fixed or
     planned;
   - `guide/limitations.md` has a section "Known defects from the code review", with a
     workaround for each open finding;
   - `docs/handover.md` §3 is brought up to 2026-11-20;
   - the site was republished.
7. **Questions answered with no change to the code:**
   - the file types (`.tfea` is a JSON model; `<model>.tfea.h5` is the HDF5 results);
   - the effort to build HTML documentation, and what GitHub Pages is;
   - the effort to extend the program to 3D (section 7).

## 4. How to work on this machine

- **Python:** the project venv only, `.venv\Scripts\python.exe`. Windows, with
  PowerShell 5.1 as the main shell and Git Bash also available.
- **Writing files:** use the Write and Edit tools. Shell heredocs fail here.
- **Commit messages:**
  - write the message to a file in the scratchpad and run `git commit -F <file>`;
  - in PowerShell 5.1, double quotes inside a here-string message break the argument
    passing;
  - in Git Bash, `printf '...' > file` works.
- **Line-ending warnings:** "LF will be replaced by CRLF" is harmless.
- **The GUI** is tested offscreen only. It has never been opened on a real screen; that
  is human gate M8.G.
- **The guide:**
  - `scripts/build_guide.py` writes the generated pages theory, correlations, materials,
    verification and units; `--check` reports whether they are current;
  - build with `.venv\Scripts\python.exe -m mkdocs build --strict`, which writes to
    `site/` (gitignored);
  - after a change in `guide/`, publish with:

    ```
    .venv\Scripts\python.exe -m mkdocs gh-deploy --strict --remote-name origin --remote-branch gh-pages -m "Deploy the user guide from {sha} with MkDocs {version}"
    ```

    The site is live about 40 s later. Check it with
    `curl -s https://dilleyrd.github.io/thermal-fea/<page>/`.
  - Publishing cannot be automated: the git credential lacks the `workflow` scope, so
    a file in `.github/workflows/` is refused on push, and `gh` is not signed in.
- **When a review finding is fixed:**
  - remove its entry from "Known defects from the code review" in `guide/limitations.md`;
  - update its status in the table and the note in `REVIEW.md`;
  - republish the guide.

## 4a. Update of 2026-11-22: the external review

- `REVIEW-2.md` is an external review of 353a3ca. `docs/review-2026-11-21-evaluation.md`
  checks each claim and proposes tasks M11.17–M11.30; the open decisions D1–D13 are Q29.
- At the owner's request ("fix the clear-cut bugs where no decision is needed") these
  were built and pushed, one commit each: M11.20 (hydraulics once per iteration), M11.21
  (stream heating flag), M11.22 (DXF arcs and loops), M11.24 (viewport colour bar),
  M11.18 (restart, second part, without 2.1-3) and M11.25 (GUI state on New, Open and
  remesh). The suite then passed with 2045 tests.
- M11.25 changed one M8.10 test assertion: result objects no longer survive a new model,
  which was the defect the review reported.
- Still open: M11.12–M11.16 (below), M11.23, M11.26, M11.27, M11.29, M11.30, and the tasks
  that wait for the owner's decisions: M11.17 (D1), M11.19 (D3), M11.28 (D6), and 2.1-3
  in M11.18 (D2).
- **The owner answered `TODO.md` on 2026-11-22**; every answer is recorded in Q29 (items
  1–15).
  - **Order of work:** M11.12–M11.16, M11.23, M11.26, M11.27, M11.29, M11.30, then the
    newly unblocked tasks:
    - M11.19, M11.28 and M11.31–M11.36;
    - the released M10.5 and M11.7–M11.10;
    - M11.17 (the owner gave N = 100).
  - **3D:** not yet.
  - **What still waits on the owner:** `TODO.md`.
- **Built on 2026-11-22, after the answers:** M11.12–M11.16, which fixed findings 1 and
  5–9 of `REVIEW.md`. All nine findings of that review are now fixed. The suite passed
  with 2082 tests.
  - **Next:** M11.23, then M11.26, M11.27, M11.29 and M11.30, then the newly unblocked
    tasks.
  - **Section 5 below is now history.**
- **Built on 2026-11-23:** M11.23 (validation coverage) and M11.26 (meshing: facet
  orientation by the parent's registered side, order-independent structured counts,
  holes refused, curve ends after a copy) and M11.27 (inputs and outputs). The suite
  passed with 2484 tests.
  - M11.27 left one review claim as it is: an expression that overflows while it is
    evaluated (`10**400`) gives inf, as `test_expression_huge_power_does_not_hang`
    specifies; validation refuses a material property that is not finite. A literal that is
    not finite (`1e309`) is now refused.
- **M11.29 (GUI flow and selection fixes)** followed; the suite passed with 2504 tests.
  - One M8.8 test assertion changed: the correlation list of a convection load no longer
    offers `duct_internal`, which was the defect the review reported (as in M11.25).
  - The stream chart's CSV button is disabled (its two curves have different s values);
    leaving the mesh panel ends the quality colouring; an empty refinement row stays
    possible (add, then type the selection, as M8.7 tests) and meshing says it has no
    selection; the unit mixing between file and document units stays a documented
    limitation.
- **M11.30 (packaging and documentation)** followed: MIT `LICENSE`, root `README.md`,
  pandas in the `examples` extra, Pillow declared, `thermalfea-gui`, two layer guards;
  the suite passed with 2508 tests. An existing installation needs `pip install -e .`
  again to get `thermalfea-gui` (not run here: no network).
  - **Next, in the agreed order:** M11.17, M11.19, M11.28, M11.31–M11.36, M10.5,
    M11.7–M11.10, M11.2, M11.3, M11.5, then M11.6.

## 5. Next work: tasks M11.12–M11.16

Each task's text is in `docs/tasks.md` and the decisions are in Q28. Start each task with
a test that reproduces the finding and fails. The code locations below were confirmed on
2026-11-20.

| Task | Tier | Finding | Where the defect is |
|---|---|---|---|
| **M11.12 Input guards** | A | 1, 8 | `cli.py: _solve` (`path = args.output or api.results_path(args.model)`) never compares the output with `args.model`; use `Path.resolve()` or `os.path.samefile` before solving. `model/settings.py: SolutionSettings.__post_init__` (about line 143) and `model/validate.py` do not check `dt_max > 0`, `dt_max >= dt_min`, or `initial_dt > 0` when it is set. Report these as validation errors so the window shows them. `solution_forms.py` has `minimum=0.0` on the fields. |
| **M11.13 Mesh out of date** | A | 5 | `gui/document.py: classify_change` collects selection names with `_dict_keys(mesh_settings)`. It misses the names stored as values in `structured_surfaces` (a list of str) and `refinements[*].selection`. |
| **M11.14 Path locator** | B | 6 | `post/path.py`: the locate loop tries only the `N_CANDIDATES = 8` nearest centroids (a KD-tree). Add a fallback for the points still pending: a bounding-box filter, then the existing `_newton` and `_inside_polygon`. |
| **M11.15 Spatial temperatures** | B | 7 | `model/validate.py: _sample` calls `fn(t=0.0)`, so x = y = 0. Sample at the points of the entities the load applies to, or return `None` (unknown) when the function depends on position. A constant 0 K must still be refused. |
| **M11.16 Early output times** | B | 9 | `solver/timestep.py`: the filter in `__init__` uses `_TIME_EPS * span`, and `next_mandatory` uses `_TIME_EPS * max(abs(end), 1)`. Make both relative to the local time. The `finished` property uses the end-time scale, which is acceptable. Theory §6.1 does not specify the tolerance, so no change to the theory is needed. |

After all of them: M11.6, the release review, which depends on M11.7–M11.16.

## 6. Waiting on the owner

- **M8.G**, human gate: build V-10 and V-17 in the window following
  `docs/gui-walkthrough.md`.
- ~~**M11.1**~~, human task: closed on 2026-11-23 after M11.37–M11.42 (Q30); the owner
  kept the printed oxygen row and declined the Q30.4 additions.
- **Confirm the Theory §6.1 sentence in Q27.3** before M11.10 is built.
- **Confirmations that block nothing:** Q11, Q14, Q17.2, Q18.2 and Q20–Q26.
- **Known gap with no task yet:** the solver computes the heat across a contact
  (`contact_heat`), but it is not written to the results file or shown in the program.
  The pump showcase recovers it by post-processing. Ask the owner before adding a task.
- **Not started and not on hold:** M11.2 (verification report), M11.3 (performance),
  M11.5 (Windows build).

## 7. Future direction discussed: 3D (not planned, no task)

The owner asked how much work 3D would be. The answer given was about 35–55 tasks:
- Small: elements and kernel. V-37 already runs a 3D tetrahedron patch test through the
  unchanged kernel, and the PLAN §7 rules keep the code free of a fixed dimension.
- Medium: the linear solver (an iterative solver or `pypardiso` behind
  `solver/linear.py`, so M11.3 becomes essential), geometry and meshing (3D operations,
  STEP solids), contact over surfaces, a redesign of streams, and post-processing
  (section cuts, iso-surfaces).
- Largest: a PyVista/VTK `SceneView` with 3D picking.

The suggested phasing:
1. Headless 3D through the API and the command line, with ParaView for viewing.
2. The 3D window.
3. Later, streams and enclosure radiation in 3D.

The owner has not decided. Write a milestone M12 only if they ask for it.
