# What the agents need from the owner

State on 2026-11-23, after your answers of 2026-11-22 and 2026-11-23. Every answer is recorded in
`docs/OPEN_QUESTIONS.md` Q29 (items 1–15) and Q30, and turned into tasks in `docs/tasks.md`;
N = 100 for D1. Two items remain. The interactive version is
[`docs/owner-review.html`](docs/owner-review.html).

| # | Item | Your time | Blocks |
|---|---|---|---|
| 1 | M8.G: build V-10 and V-17 in the window | 60–120 min | Release review M11.6 |
| 2 | Visualisation testing, and the pump example (optional) | 30–60 min | Nothing |

---

## 1. M8.G human gate: build V-10 and V-17 in the window — 60–120 min

You reviewed V-10 on 2026-11-24 and asked for the GUI identity changes (decisions D1–D8),
tasks M11.49–M11.64. They are built. You will now review **V-10 and V-17 again** on the
updated window.

On 2026-11-24 a script followed the rewritten walkthrough with the real widgets and
reproduced every number in it:
- V-10: 18.206 °C at (0.6, 0.2) on 1210 nodes;
- V-17: worst relative error 1.4e-3 on 82 nodes.

The 24 screenshots of that run are in the walkthrough and on the session page
https://claude.ai/artifact/AVKWHDY1Pa6YZ22go6weAH (private to you). The page also has a
friction log that is saved as you type.

The steps:
1. Start the program with `.venv\Scripts\python.exe -m thermalfea.gui.app`.
   `dist\ThermalFEA` predates these changes.
2. Follow `docs/gui-walkthrough.md` to build V-10 and V-17 from an empty model, and
   solve both. Name every selection yourself in the "New name" box.
3. Work through "What to check in this review" for each case (walkthrough §1.8 and §2.9).
4. Fill in walkthrough §5 (or the page's log):
   - the friction log: step, what you did, what happened, severity (blocker / slows me
     down / cosmetic), and a suggested change;
   - minutes per case;
   - the answer for each case and whether it is inside tolerance: V-10 within 0.15 °C,
     V-17 within 2e-3.
5. Confirm or dismiss the 13 known frictions in walkthrough §4:
   - item 2 is the "Pick in viewport" start mode, which you asked to check here (Q29.12);
   - items 9–13 were seen in the screenshot run.

**What changed for this review (M11.49–M11.64):**
- **Toolbar:** it reads Point · Boundary · Part.
- **Tree:**
  - the sections are Parts and Selections, with summaries in a second column;
  - the empty Contacts, Flow and Enclosures fold into one line;
  - a material shows its library source.
- **Selections:** you name each one at Apply and can rename it later; everything that
  uses it follows.
- **Results:** a result has a header and lists the changes since the solve.
- **Viewport:** hover and click identify an entity.

The decisions made while building, for you to confirm, are listed in `docs/CONTINUE.md` §6.

The release review M11.6 waits for this session.

**Files.**
- `docs/gui-walkthrough.md` and its screenshots in `docs/img/gui-walkthrough/`;
- `docs/gui-identity-plan.md`;
- `docs/verification.md`.

## 2. Visualisation testing, and the pump example — 30–60 min, optional

1. **Visualisation.** You planned to test it over more kinds of boundary condition, once
   the build is complete. You chose GIF only, so there is no MP4 to test.
2. **Pump example.** All its inputs are marked illustrative. It stays that way unless you
   supply real values: dimensions, materials, six contact conductances, heat-up history,
   and fluid temperatures (indexed in `examples/pump_closure/README.md`).

---

## Decided on 2026-11-22 and 2026-11-23 (for reference)

Full text: `docs/OPEN_QUESTIONS.md` Q29 and Q30.

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
| Air (2026-11-23) | Labelled 1 bar; every row of Table A.4 | M11.37 |
| Water (2026-11-23) | NIST rows every 5 K; β from NIST | M11.37 |
| Solids (2026-11-23) | Only the book's materials; all complete entries added; 6061-T6, Ti-6Al-4V, FR-4 removed | M11.37 |
| Correlations (2026-11-23) | The book's, plus useful ones not yet applied | M11.38–M11.42 |
| Tutorial bound (2026-11-23) | Cold-plate Re within 3 % of the inlet values | M11.37 |
| Oxygen at 1300 K (2026-11-23) | μ·10⁷ = 588.4 kept as printed | — |
| Q30.4 (2026-11-23) | The correlations are adequate; no enclosures, mixed convection or Table 8.1 f·Re | — |
| M11.1 (2026-11-23) | Closed | M11.1 |
