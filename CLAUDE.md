Read `PLAN.md` first, then only the documents the task in `docs/tasks.md` names. Rules (Plan §4):
1. One task per session: the first unchecked task in `docs/tasks.md` whose dependencies are checked. Do nothing else.
2. Never derive an equation. Formulas are in `docs/theory.md`; if one is missing or wrong, write it in `docs/OPEN_QUESTIONS.md` and stop.
3. Never invent a material property, correlation constant, or benchmark target; a missing number goes in `OPEN_QUESTIONS.md`.
4. A task is done only when its acceptance tests exist and pass, the whole suite passes, and its box is ticked.
5. Never weaken a test to make it pass. Tolerances are specification; a failing verification test means the code is wrong.
6. Do not change public signatures in `docs/data-model.md` or the task text; if one cannot work, record why and stop.
Plan §7 (no literal space dimension, registered elements, facets, `DofMap`, `Term`s) binds every task.
Check command (lint + all tests, project venv only): `.\scripts\check.ps1`
Commit each task as `M<n>.<k>: <task title>` and push to `origin`; never force-push.
