# Subagent log

The owner asked (2026-11-27) to record every task given to a subagent: which model, what
kind of task, and what the review of its result found. The aim is to learn which model
suits which kind of task, to guide later assignments (the standing rule is cheaper models
for work that does not need advanced reasoning; see the tiers [A], [B], [C] in
`docs/tasks.md`).

How to fill it in (owner, 2026-11-27):

- **Outcome** is one of: *accepted* (used as delivered), *accepted after fixes* (the main
  model corrected it), *redone* (the main model did the task itself), *failed* (nothing
  usable). **Instructions** says whether the agent kept to its brief.
- **A failure is described in detail**: what went wrong, the mechanism (which command,
  which wrong assumption), how it was noticed, what the damage was and how it was
  repaired. The detail is what makes the next brief better.
- **A lesson is added whenever a clear rule can be drawn**, in the entry and, once it is
  general, in the list below. Read the list before writing a brief.

## Lessons for briefing agents

1. **Bulk file rewrites (any model, especially Haiku):** do not let an agent write its own
   rewrite script unsupervised. Either give the exact script, or keep the rewrite on the
   main model. The script must check that each new content is non-empty and plausible
   (for a replacement: the length changes only by the expected amount) before writing,
   and should do a dry run that lists the files and counts first. *From M11.66.*
2. **Prohibitions on editing methods are not reliably kept (Sonnet):** "edit only with
   the Edit/Write tools, no heredoc or sed" was ignored once. Give the reason with the
   rule (line endings, quoting failures on this machine), and always review the diff and
   watch for LF/CRLF warnings rather than trusting the report. *From M11.67.*
3. **Read-only surveys work well with a numbered checklist (Sonnet, Explore):** asking for
   facts with file:line references, in numbered sections, gave a complete inventory that
   held up when checked. Ask for facts, not opinions, and say how the result will be
   used. *From the GUI inventory.*
4. **Every brief names what to do when something goes wrong:** "if something unexpected
   happens to files, stop and report" made the Haiku agent stop after its mistake instead
   of improvising a restore. Keep that sentence in every brief that edits files.
   *From M11.66.*
5. **Test migrations go well with an explicit old-to-new API map and a "never weaken"
   rule (Sonnet):** listing each old call with its replacement and the behaviors that
   changed by design, and asking for a report of every replaced assertion, gave a
   migration that kept or tightened every check. Let it also report suite-wide problems it
   notices. *From M11.70.*
6. **A [B] build task goes well when the brief gives the exact layout (titles, field
   order, texts) and points at a finished reference panel to copy (Sonnet):** the agent
   then only applies patterns; design choices stay with the main model. Check the result
   visually (offscreen render), since tests do not show clipping or spacing. *From M11.72.*
7. **Ask documentation agents to verify against the running program and report
   deviations (Sonnet):** a driver that prints what the window shows, plus "list every
   place where the window did not behave as the conventions say", turned two doc tasks
   into a useful acceptance test of the whole redesign (one bug, three gaps found).
   Two agents on disjoint files can run in parallel; tell each which files are the
   other's. *From M11.79.*

## Entries

| Date | Model | Agent type | Task | Kind of task | Outcome | Instructions | Review notes |
|---|---|---|---|---|---|---|---|
| 2026-11-27 | Sonnet | Explore (read-only) | GUI inventory for the consistency pass: every panel, field, pick mode, dialog, icon, tree behavior and result window | Broad code survey, facts with file:line references | accepted | kept | Thorough (11 sections, 57 KB, 70 tool calls, about 6 min). The facts used in the consistency report held up where checked (e.g. the Material library confirm button, the Refinements table applying per cell, no Esc handling). Good value for a sweep the main model would have spent much context on. Lesson 3. |
| 2026-11-27 | Haiku | general-purpose | M11.66 [A]: replace "colour" with "color" in 37 files, rename private identifiers, add a spelling test, run the check | Mechanical bulk edit across many files | failed, redone | partly | **Failure:** its PowerShell replacement script called `[regex]::Replace` with an overload that does not exist for the arguments it passed, so every call threw; the script did not stop on the error and wrote the (null) result back, **emptying all 37 target files** (`git diff --numstat` showed 0 added / all lines deleted). A second script then found nothing to change and reported "Changed 0 files", so the agent noticed only from the diff. Its `git checkout -- .` to restore was refused by the permission settings; it then stopped and reported honestly instead of working around it, and asked the main model to restore (refused as permission laundering; surfaced to the owner, who approved `git restore`). Nothing was committed. The main model redid the task with a Python script that decodes each file, replaces case-preservingly, asserts the result is non-empty and of the expected length, and writes only changed files (158 lines in 37 files, check passed). Lessons 1 and 4. |
| 2026-11-27 | Sonnet | general-purpose | M11.67 [B]: guard against a solve overwriting the results file its initial condition reads (function, Validate issue, three GUI tests) | Small, fully specified feature with tests | accepted | partly | Correct on first review: exact message, right issue kind (found the existing mapping in `issues.py` instead of adding one), good tests including a relative path. Check passed (2890). **Deviation:** it appended the tests and changed imports with a Bash heredoc and `sed` although told not to; it said so in its report. The result was correct; git warned that the file had LF line endings. Lesson 2. |
| 2026-11-28 | Sonnet | general-purpose | M11.70 [C, part]: migrate 24 older GUI tests to the redesigned selection field (new API, owner's decisions: no default names, Update before applying, Edit instead of retyping a name) | Test migration against a given API map | accepted | kept | All 24 migrated; the check passed (2918). Every changed assertion checks the same behavior in its new form; several got stricter (model JSON unchanged on refusal, confirm disabled until a valid name). It listed each assertion replaced by design (default names, replace-by-retyping, no message for an empty name). It also **found a real suite problem**: a test that leaves a pick running leaves the application-wide Esc/Enter filter installed, making the suite order-dependent; the main model fixed it at the root (`end_all_picks` and an autouse fixture). Minor: it silenced F811 in a test file with a file-level `noqa` instead of per line. About 14 min, 79 tool calls. Lesson 5. |
| 2026-11-28 | Sonnet | general-purpose | M11.71 [C, part]: migrate 5 Mesh-panel and units tests to the new value-per-selection table | Test migration against a given API map | accepted | kept | All 5 migrated; every removed assertion has a stricter or equal replacement (exact error messages instead of "non-empty", unchanged undo counts added, new coverage of the Update path and of the distance rule). The only assertion dropped without a direct equivalent was a red cell background, which the new widget shows differently. It found that its fake view lacked `highlight` and added it. It reported honestly that the check stopped at lint on *my* files (import order, F811, a long docstring line) instead of fixing files it was told not to touch. About 5 min, 32 tool calls. The brief gave the reason for the editing rule this time (Lesson 2) and it followed it. |
| 2026-11-28 | Sonnet | general-purpose | M11.72 [B]: panel layouts — boxes and "More" for the Mesh, Correlation, Stream and network panels, material angle visibility, a new Initial Condition panel with kinds and a browse icon, hint texts, the k2 label, disabled typing in empty mode; with 22 acceptance tests | Applying shared controls to several panels from a detailed spec | accepted | kept | Correct on review and visually (panels rendered offscreen): boxes, More lines, named empty modes ("From network", "Not used"), browse icon in the results-file row. No existing test needed changing. Sensible small additions it reported (a path pick is cancelled when the stream becomes through-plane; the Path box hides as a whole). It flagged what it left (the Mesh module docstring, no hint for the Initial Condition value) instead of guessing. About 7 min, 78 tool calls. Lesson 6. |
| 2026-11-28 | Sonnet | general-purpose | M11.73 [B]: names and words — readable choice texts in panels and dialogs, Part/Boundary/Point wording in tooltips, summaries, validation and Issues, symbols (T∞, ε) in labels, view labels and summaries; 18 acceptance tests; migration of tests in 14 files | Broad wording change across many files from an exact text table | accepted | kept | Check passed (2965). Thorough: readable texts keep the ids as item data everywhere (dialogs read back `currentData`), one shared symbol table and shared text helpers instead of copies. All migrated assertions are wording changes with the same behavior checked; several got stricter (texts must equal the correlation titles). Honest list of its own wording choices ("the area N" for an unassigned surface) and of what it left (validation messages still say "boundary condition"; geometry dialogs covered only by unit assertions). About 17 min, 223 tool calls — the slowest so far, because wording touches many tests. |
| 2026-11-28 | Sonnet | general-purpose | M11.78 [B]: warning marks in the tree from a debounced validation; a "warning" icon; 11 tests | Small feature from a precise spec, with a design decision left to it (how to validate without a build) | accepted | kept | Good judgment: found the existing `validate_model` for the no-build case instead of inventing one, saved and restored each item's own icon and tooltip, blocked tree signals while marking (it noticed `setIcon` would trigger the rename handler and rebuild in a loop), and added a `rebuilt` signal so marks survive every kind of rebuild. Stated its own choices (an unaddressed model issue marks the Loads section). It reported that it had not read ruff's output itself; the main model's own check passed (3002). About 5 min, 34 tool calls. |
| 2026-11-28 | Sonnet | general-purpose | M11.79 part A: rewrite the GUI walkthrough for the redesigned window, write a committed screenshot driver, regenerate 40 screenshots | Documentation with a script that drives the real app; checking text against the window | accepted | kept | Strong: the driver prints trees, panel texts and numbers so the text was checked against the real window, and it read every PNG it produced. It **found a real bug** (a closed chart window was touched by the next edit: `RuntimeError: ChartWindow already deleted`), fixed by the main model in history_tools and path_tools with a test. Honest list of what was carried over unverified (CSV export, Save/Open steps). Numbers unchanged except a corrected "about 5e-15". About 25 min, 160 tool calls. Lesson 7. |
| 2026-11-28 | Sonnet | general-purpose | M11.79 part B: update the guide (getting started, three tutorials, limitations), the oil-cooler window steps, data-model §13 and CONTINUE | Documentation checked against the source for exact labels | accepted | kept | Thorough and accurate wording; it **found three gaps between the window and the conventions** (the probe had no strip — fixed by the main model; a new stream's mass flow still starts in "From network"; contours never say "unavailable") and listed the out-of-date oil-cooler screenshots instead of faking them. It stayed out of the other agent's files even when they broke the lint. About 10 min, 164 tool calls. Lesson 7. |
