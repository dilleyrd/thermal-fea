# What the agents need from the owner

State on 2026-11-22, after your answers of the same day. Every answer is recorded in
`docs/OPEN_QUESTIONS.md` Q29 (items 1–15) and turned into tasks in `docs/tasks.md`; N = 100
for D1. Three items remain. The interactive version is [`docs/owner-review.html`](docs/owner-review.html).

| # | Item | Your time | Blocks |
|---|---|---|---|
| 1 | M8.G: build V-10 and V-17 in the window | 60–120 min | Release review M11.6 |
| 2 | M11.1: decide on the property findings, then check the correlations | 1–2 h | Release review M11.6 |
| 3 | Visualisation testing, and the pump example (optional) | 30–60 min | Nothing |

---

## 1. M8.G human gate: build V-10 and V-17 in the window — 60–120 min

No person has used the program on a real screen; every GUI test runs offscreen. The
steps:
1. Start the program with `.venv\Scripts\python.exe -m thermalfea.gui.app`.
2. Follow `docs/gui-walkthrough.md` to build V-10 and V-17 from an empty model, and
   solve both.
3. Fill in walkthrough §5:
   - the friction log: step, what you did, what happened, severity (blocker / slows me
     down / cosmetic), and a suggested change;
   - minutes per case;
   - the answer for each case and whether it is inside tolerance: V-10 within 0.15 °C,
     V-17 within 2e-3.
4. Confirm or dismiss the eight known frictions in walkthrough §4. Item 2 there is the
   "Pick in viewport" start mode, which you asked to check here (Q29.12).

Changed since the walkthrough was written: M10 (contacts, DXF, units, restart), M11.24
(colour bar) and M11.25 (New, Open, remesh, closing the solve dialog). If you would rather
test after the released GUI tasks are built, wait for M11.7–M11.9: the axisymmetric
choice, the display fixes and the dialog for new loads.

**Files.**
- `docs/gui-walkthrough.md`;
- `docs/verification.md`;
- `guide/getting-started.md`;
- `guide/limitations.md`.

## 2. M11.1 human task: property decisions, then the correlations — 1–2 h

**The properties have been checked** (2026-11-23) against Incropera 7th ed., the NIST WebBook and
CoolProp. See `docs/property-verification.md`. Air and water are copied exactly from Incropera,
Tables A.4 and A.6. Seven of the ten solids are copied exactly from Tables A.1–A.3. Choose:
1. **D11, air.** The densities are those of 1 bar, within 0.04 %. Either label the table "1 bar",
   or keep "1 atm" and rescale ρ.
2. **Water rows.** With 5 rows, μ is off by up to 5.1 % between rows. Keep them, use all of
   Incropera's rows from 275 to 370 K (1.2 %), or use NIST rows every 5 K (0.4 %).
3. **Water β at 360 K.** The book gives 697.9e-6 and NIST gives 679.7e-6. This looks like a
   misprint. Correct it, or keep it?
4. **Air rows.** ρ is off by up to 2.1 % between rows. All of Incropera's rows, 50 K apart, bring
   that to 0.83 %.
5. **6061-T6, Ti-6Al-4V and FR-4** are not in Incropera. Name a source, replace them, or keep them
   marked unsourced.
6. **CoolProp**: use it as a build-time table generator, as test reference values only, or not
   at all. KittyCAD and matproplib are not suitable (report §4).

Then:
- **Correlations.** Check every correlation and its validity range against the same book.
  Citations recorded so far: Churchill–Bernstein, Churchill–Chu, Gnielinski, Dittus–Boelter
  and Churchill 1977.
- **Q17.2, horizontal plates.** Is the characteristic length the selection length (as now),
  or area/perimeter?

The inclined-plate range is settled: one-sided, θ ≤ 60° (Q29.5).

**Files.**
- `docs/property-verification.md`;
- `docs/data-model.md` §6;
- `docs/theory.md` §8, §8.1;
- `src/thermalfea/materials/data/solids.json` and `fluids.json`;
- `src/thermalfea/convection/correlations.py`;
- `src/thermalfea/convection/fluid_props.py`;
- `docs/OPEN_QUESTIONS.md` Q17, Q26.2.

## 3. Visualisation testing, and the pump example — 30–60 min, optional

1. **Visualisation.** You planned to test it over more kinds of boundary condition, once
   the build is complete. You chose GIF only, so there is no MP4 to test.
2. **Pump example.** All its inputs are marked illustrative. It stays that way unless you
   supply real values: dimensions, materials, six contact conductances, heat-up history,
   and fluid temperatures (indexed in `examples/pump_closure/README.md`).

---

## Decided on 2026-11-22 (for reference)

Full text: `docs/OPEN_QUESTIONS.md` Q29.

| Item | Decision | Task |
|---|---|---|
| D1 convergence | (c) round-off floor N · ε with N = 100 | M11.17 |
| D2 fluid rows | θ = 1 for rows without capacitance; re-solve the fluid on a restart | M11.31 |
| D3 step estimate | Free DOFs only; restart the predictor after a physical breakpoint; first-step limit; fix `_jumps` | M11.19 |
| D4 network | A clear error with diagnostics | M11.32 |
| D5 inclined plate | Refuse \|θ\| > 90°; range stays one-sided | M11.23 |
| D6 term results | New groups, schema step, shown in the window, used by the pump example | M11.28 |
| D7, D8 | `depends_on_position`; model-only checks in `api.solve` | M11.23 |
| D9 documents | Theory §7 "positive into"; Data §8/§9; Δt₀ wording; Q20.1 | M11.33 |
| D10 packaging | MIT licence; pandas as an extra `examples`; README; keep both image copies | M11.30 |
| D12 design | Transforms of points and curves; user fluids; fixed temperature at a contact end fixes both sides. The rest stays as now | M11.34–M11.36 |
| D13 scope | Excluded; drop `thermalfea export` from PLAN | M11.33 |
| Q27.3 | "Checked once, for the first step, and not logged when that step is the suggested Δt₀" | M11.10 |
| Release | Version 1 excludes M9 and M10.2 and their cases | M11.6 |
| Holds | Released: M10.5, M11.7–M11.10. On hold: M9, M10.2, scripting | — |
| Order | Default order, then the newly unblocked tasks | — |
| 3D | Not yet | — |
| Confirmations | Q1, Q14, Q18.2, Q20, Q21, Q22 (except 22.5), Q23, Q24, Q25, Q26 and all earlier entries | — |
| Access | Publish by hand; GIF only | — |
