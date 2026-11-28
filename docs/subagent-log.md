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

## Entries

| Date | Model | Agent type | Task | Kind of task | Outcome | Instructions | Review notes |
|---|---|---|---|---|---|---|---|
| 2026-11-27 | Sonnet | Explore (read-only) | GUI inventory for the consistency pass: every panel, field, pick mode, dialog, icon, tree behavior and result window | Broad code survey, facts with file:line references | accepted | kept | Thorough (11 sections, 57 KB, 70 tool calls, about 6 min). The facts used in the consistency report held up where checked (e.g. the Material library confirm button, the Refinements table applying per cell, no Esc handling). Good value for a sweep the main model would have spent much context on. Lesson 3. |
| 2026-11-27 | Haiku | general-purpose | M11.66 [A]: replace "colour" with "color" in 37 files, rename private identifiers, add a spelling test, run the check | Mechanical bulk edit across many files | failed, redone | partly | **Failure:** its PowerShell replacement script called `[regex]::Replace` with an overload that does not exist for the arguments it passed, so every call threw; the script did not stop on the error and wrote the (null) result back, **emptying all 37 target files** (`git diff --numstat` showed 0 added / all lines deleted). A second script then found nothing to change and reported "Changed 0 files", so the agent noticed only from the diff. Its `git checkout -- .` to restore was refused by the permission settings; it then stopped and reported honestly instead of working around it, and asked the main model to restore (refused as permission laundering; surfaced to the owner, who approved `git restore`). Nothing was committed. The main model redid the task with a Python script that decodes each file, replaces case-preservingly, asserts the result is non-empty and of the expected length, and writes only changed files (158 lines in 37 files, check passed). Lessons 1 and 4. |
| 2026-11-27 | Sonnet | general-purpose | M11.67 [B]: guard against a solve overwriting the results file its initial condition reads (function, Validate issue, three GUI tests) | Small, fully specified feature with tests | accepted | partly | Correct on first review: exact message, right issue kind (found the existing mapping in `issues.py` instead of adding one), good tests including a relative path. Check passed (2890). **Deviation:** it appended the tests and changed imports with a Bash heredoc and `sed` although told not to; it said so in its report. The result was correct; git warned that the file had LF line endings. Lesson 2. |
| 2026-11-28 | Sonnet | general-purpose | M11.70 [C, part]: migrate 24 older GUI tests to the redesigned selection field (new API, owner's decisions: no default names, Update before applying, Edit instead of retyping a name) | Test migration against a given API map | accepted | kept | All 24 migrated; the check passed (2918). Every changed assertion checks the same behavior in its new form; several got stricter (model JSON unchanged on refusal, confirm disabled until a valid name). It listed each assertion replaced by design (default names, replace-by-retyping, no message for an empty name). It also **found a real suite problem**: a test that leaves a pick running leaves the application-wide Esc/Enter filter installed, making the suite order-dependent; the main model fixed it at the root (`end_all_picks` and an autouse fixture). Minor: it silenced F811 in a test file with a file-level `noqa` instead of per line. About 14 min, 79 tool calls. Lesson 5. |
