# Subagent log

The owner asked (2026-11-27) to record every task given to a subagent: which model, what
kind of task, and what the review of its result found. The aim is to learn which model
suits which kind of task, to guide later assignments (the standing rule is cheaper models
for work that does not need advanced reasoning; see the tiers [A], [B], [C] in
`docs/tasks.md`).

**Outcome** is one of: *accepted* (used as delivered), *accepted after fixes* (the main
model corrected it), *redone* (the main model did the task itself), *failed* (nothing
usable). **Instructions** says whether the agent kept to its brief.

| Date | Model | Agent type | Task | Kind of task | Outcome | Instructions | Review notes |
|---|---|---|---|---|---|---|---|
| 2026-11-27 | Sonnet | Explore (read-only) | GUI inventory for the consistency pass: every panel, field, pick mode, dialog, icon, tree behavior and result window | Broad code survey, facts with file:line references | accepted | kept | Thorough (11 sections, 57 KB, 70 tool calls, about 6 min). The facts used in the consistency report held up where checked (e.g. the Material library confirm button, the Refinements table applying per cell, no Esc handling). Good value for a sweep the main model would have spent much context on. |
| 2026-11-27 | Haiku | general-purpose | M11.66 [A]: replace "colour" with "color" in 37 files, rename private identifiers, add a spelling test, run the check | Mechanical bulk edit across many files | failed, redone | partly | Its PowerShell replacement script used a wrong `Regex.Replace` overload, did not stop on the error and wrote empty results, **emptying all 37 files**. A `git checkout` to restore was refused by the permission settings; it then stopped and reported honestly instead of working around it. The owner approved `git restore`; the main model redid the task with a Python script that checks each file before writing (158 lines changed, check passed). Lesson: for bulk file rewrites, give the exact script or do it in the main model; ask for a dry run and a non-empty check before writing. |
| 2026-11-27 | Sonnet | general-purpose | M11.67 [B]: guard against a solve overwriting the results file its initial condition reads (function, Validate issue, three GUI tests) | Small, fully specified feature with tests | accepted | partly | Correct on first review: exact message, right issue kind (found the existing mapping in `issues.py` instead of adding one), good tests including a relative path. Check passed (2890). Deviation: it edited the test file with a shell heredoc and `sed` although told not to; the result was correct. |
