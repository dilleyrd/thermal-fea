# Pump main closure: axisymmetric demonstration

An r-z model of the main closure of a canned-motor pump, built from the sketches in
`AP1000_Closure_Thermal_Sketches.pdf`. **All dimensions and inputs are illustrative.**

It keeps the two parallel heat paths from the casing into the stator main flange:

1. **Across the seated joint faces:** seal land, main seat and barrier foot at z = 0, plus the vertical barrier/casing fit.
2. **Down the studs:** from the casing lip through the stud anchor, down the stud ring D into the flange band G. The nut ring N hangs below the flange on its bearing face.

Changing the main-seat conductance shifts heat between the two paths.

## Files

| File | What it is |
|---|---|
| `closure.json` | Every input from sheets 2–5: vertices and dimensions (mm), film coefficients and fluid temperatures (W/(m² K), °C), contact conductances, materials, initial temperature. It also holds the run controls and element sizes chosen for the exercise. Edit this file to change the case. |
| `closure_model.py` | Builds the model from `closure.json`: geometry, named selections, materials (including the composite band G), films, contacts, mesh and solution settings. Also post-processes the results. |
| `run_closure.py` | Builds, saves, meshes and solves the heat-up (default) or the steady hot case (`--steady`). Writes the model, results, a per-step CSV and plots. |
| `animate_closure.py` | Solves the heat-up again with a frame every 60 s for the first hour and every 300 s after that, and writes `out/closure_heatup.gif` (°C, mm, minutes, one colour scale for all frames). |
| `seat_study.py` | Runs the steady hot case for each main-seat factor in `closure.json` and writes `seat_study.csv` and `seat_study.png`. With `--mesh-check`, it runs the hot case with element sizes as given and halved, and checks the changes against sheet 5's criteria (< 1 K, < 2 % duty). |

## Running

From the project folder:

```
.venv\Scripts\python.exe examples\pump_closure\run_closure.py
.venv\Scripts\python.exe examples\pump_closure\run_closure.py --steady
.venv\Scripts\python.exe examples\pump_closure\animate_closure.py
.venv\Scripts\python.exe examples\pump_closure\seat_study.py
.venv\Scripts\python.exe examples\pump_closure\seat_study.py --mesh-check
```

Results go to `examples/pump_closure/out/`, which git ignores. Each run takes a few seconds.

To look at a case in the GUI:
1. Use File > Open... to open `out/closure_transient.tfea`.
2. Press **Generate mesh**; the saved results are then attached.

## How the sketches map onto the model

- **Axisymmetric:** x = r, y = z, and the solver integrates 2πr. Heat values are for the whole ring.
- **Bodies (one region each):**
  - casing, thermal barrier (with the Ø16 mm cooling passage cut out), stud ring D, nut ring N;
  - flange in three parts (inner, band G 720–760 mm, outer);
  - stator shell S and liner L.
- **Materials:** Stainless steel 304 everywhere except D and N, which are AISI 1010. All are built-in constant-property records.
- **Ring widths** come from 2πR w = Nπd²/4: D is 6.486 mm and N is 18.746 mm.
- **Band G** follows the sheet 4 mix with f = 6.486/40:
  - k_axial = (1−f) k_304 + f k_1010;
  - k_radial = (1−f) k_304;
  - density and ρc mixed separately.

  It is orthotropic with the material axis along r.
- **Films** (constant h, sheet 3 sets):
  - H: ramps 40 → 180 °C over 1800 s in the heat-up; constant 180 °C in the steady case.
  - M, Cw, J, A: per `closure.json`.
- **Insulated:** the truncation planes X, the stud shank sides, and the nut sides and base.
- **Contacts:** main seat, seal land, barrier foot, vertical fit, stud anchor, nut bearing. All other touching faces are bonded.
- **Heat across a contact** isn't stored in the results file. `closure_model.ContactHeats` evaluates it from the stored temperatures with the solver's own contact terms. The sign is from the first to the second body named in `closure_model.CONTACT_SIDES`.
- **Buried stud:** inside the flange, the stud is part of band G (sheet 4), so the stud path runs anchor → shank → G. The nut only exchanges heat while it warms up; at steady state its bearing heat is zero.

## Limits

These are the sheet 1 limits:
- The model gives ring-average (circumferential mean) temperatures only.
- Individual bolt holes, thread roots, nozzle effects and azimuthal variation of the cooling need a sector or 3D model.
