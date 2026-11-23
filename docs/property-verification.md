# Property verification and property libraries (2026-11-23)

> **Decided and built on 2026-11-23 (OPEN_QUESTIONS Q30; tasks M11.37–M11.42).**
> - **Air:** labelled 1 bar; all of Table A.4's rows are used.
> - **Water:** NIST rows every 5 K, 280–370 K, with β from NIST.
> - **Solids:** only materials from the book; every complete entry of Tables A.1–A.3 is
>   added. 6061-T6, Ti-6Al-4V and FR-4 are removed.
> - **Other fluids:** the gases of A.4 and the liquids of A.5 are added.
> - **Correlations:** taken from the book (Theory §8).
> - **CoolProp:** used only for these checks.
>
> The text below is the analysis as it stood before those decisions.

Preparation for the owner's task M11.1. It checks the property tables in Data §6 against reference
data, and it assesses three libraries as property sources. **Nothing in the code or the data has
been changed.** Each choice below is the owner's to make, and none is yet in `docs/tasks.md`.

The references used:
- **Incropera 7th ed.** is Bergman, Lavine, Incropera and DeWitt, *Fundamentals of Heat and Mass
  Transfer*, 7th ed., Wiley, 2011 (ISBN 978-0-470-50197-9). The owner supplied a PDF of it. The
  page numbers below are the book's own.
- **NIST** is the NIST Chemistry WebBook, *Thermophysical Properties of Fluid Systems*, SRD 69,
  read on 2026-11-23. Water was taken at 0.101325 MPa. The WebBook has no air.
- **CoolProp** is CoolProp 8.1.0 (Bell et al. 2014, doi:10.1021/ie4033999). Air is the pseudo-pure
  fluid of Lemmon et al. (2000); viscosity and conductivity follow Lemmon and Jacobsen (2004). For
  water it agrees with NIST to 0.0001 % at 300 K, so here it serves as the reference for air.

The scripts and the raw downloads are outside the repository. They can be rerun on request.

## 1. Where the values come from

| Table | Source found | Match |
|---|---|---|
| Air, 250–1000 K | Incropera 7th ed., Table A.4 (p. 995), "Air" | Every value matches the book exactly |
| Water, 280–360 K | Incropera 7th ed., Table A.6 (p. 1003), saturated liquid. ρ is 1/v_f | Every value matches the book exactly |
| Copper (pure), AISI 1010, AISI 304, Silicon | Incropera 7th ed., Table A.1 (300 K) | Exact |
| Alumina (polycrystalline) | Incropera 7th ed., Table A.2 (300 K) | Exact |
| Soda-lime glass ("Glass, plate (soda lime)"), Concrete (stone mix) | Incropera 7th ed., Table A.3 (300 K) | Exact |
| Aluminium 6061-T6 | **Not in Incropera.** The book has 2024-T6 (177, 2770, 875) and pure Al (237, 2702, 903) | Source not found |
| Ti-6Al-4V | **Not in Incropera.** The book has only pure Ti (21.9, 4500, 522) | Source not found |
| FR-4 | **Not in Incropera** | Source not found |

The three unmatched solids carry values typical of a manufacturer's data sheet. The KittyCAD
library (§4) agrees on two densities: 2713 kg/m³ for 6061, against 2700 here, and 4429 kg/m³ for
Ti-6Al-4V Grade 5, against 4430 here. It has no conductivity or specific heat, so it cannot confirm
the rest. A source for these three is still to be recorded.

## 2. Air against CoolProp

Each figure is the table value minus CoolProp, as a percentage of the CoolProp value, at the table's
own temperatures:

| T [K] | ρ vs 1 atm | ρ vs 1 bar | c_p | μ | k |
|---|---|---|---|---|---|
| 250 | −1.32 | −0.01 | +0.05 | −0.49 | −1.17 |
| 300 | −1.33 | −0.02 | +0.06 | −0.42 | −0.32 |
| 400 | −1.27 | +0.04 | −0.01 | −0.20 | +1.04 |
| 500 | −1.32 | −0.02 | +0.01 | −0.30 | +1.89 |
| 600 | −1.31 | −0.00 | −0.02 | −0.61 | +1.93 |
| 800 | −1.29 | +0.02 | +0.03 | −1.04 | +0.09 |
| 1000 | −1.33 | −0.02 | +0.00 | −1.94 | −1.44 |

- **D11 is settled by the numbers.** The densities are those of air at **1 bar**, within 0.04 %.
  They are 1.3 % below the values at 1 atm. Data §6 and the guide say "1 atm"; the book's heading
  says "atmospheric pressure". The owner must choose between two fixes:
  - **(a)** change the label to "1 bar". No number changes, and the table still matches its source.
  - **(b)** keep "1 atm" and scale ρ by 1.01325. Then ρ no longer matches the book.

  The effect on a result is small either way. Re changes by 1.3 % and Gr by 2.6 %, so h changes
  by about 1 %.
- c_p agrees to 0.1 %. μ agrees within 2 % and k within 2 %, the usual spread between textbook
  and current correlations.
- **Linear interpolation between the rows** stays within 0.1 % for c_p and 2 % for μ and k. ρ is
  the exception: it peaks at **+2.1 % at 700 K**, in the 600–800 K gap, because ρ ∝ 1/T is curved.
  Incropera tabulates air every 50 K. With all of its rows from 250 to 1000 K, 16 in all, ρ stays
  within 0.83 % (the worst point is 275 K), and the source is unchanged. Adding only 550–750 K
  leaves +1.25 % in the 800–1000 K gap.

## 3. Water against NIST (0.101325 MPa)

Percentage differences, table minus NIST, at the table's temperatures. NIST gives no β, so β is
evaluated from its definition, β = −(1/ρ) ∂ρ/∂T, as a central difference of NIST densities 1 K
apart.

| T [K] | ρ | c_p | μ | k | β |
|---|---|---|---|---|---|
| 280 | +0.01 | −0.07 | −0.81 | +1.75 | +5.8 |
| 300 | +0.04 | −0.04 | +0.15 | +0.57 | +0.6 |
| 320 | −0.04 | −0.01 | +0.05 | +0.47 | +0.1 |
| 340 | −0.05 | −0.01 | −0.39 | +0.43 | +0.2 |
| 360 | −0.04 | +0.02 | −0.57 | +0.43 | **+2.7** |

- **β at 360 K looks like a misprint in the book.** Table A.6 gives 697.9 × 10⁻⁶ K⁻¹ there, but
  the rows on either side are 652.3 (355 K) and 707.1 (365 K). NIST gives 679.7 × 10⁻⁶. The steps
  from 355 K are +45.6 and then +9.2; with 679.7 they would be +27.4 and +27.4. The two values
  differ by a swap of the 7 and the 9. Our table copies 697.9.
- β at 280 K is 5.8 % high in relative terms but only 2.5 × 10⁻⁶ K⁻¹ in absolute terms. β passes
  through zero at 277 K, so relative errors there are large by nature.
- k is 1.75 % high at 280 K. The book's conductivities predate the 2011 IAPWS formulation that
  NIST uses.
- Saturated liquid and liquid at 1 atm differ by less than 0.05 % in ρ over this range, so the
  book's saturation table is a fair stand-in for liquid at 1 atm.

**The owner's question: is linear interpolation of 5 points enough?** The largest interpolation
error over 280–360 K, against NIST:

| Table | ρ | c_p | μ | k | β |
|---|---|---|---|---|---|
| Current 5 rows (20 K apart) | 0.08 % | 0.07 % | **+5.1 % at 291 K** | 1.75 % | **−7.7 % at 287 K** |
| All of Incropera's rows, 275–370 K (5 K apart) | 0.05 % | 0.08 % | 1.2 % | 1.75 % | 5.8 % at 280 K (the zero crossing) |
| NIST rows 10 K apart | 0.02 % | 0.03 % | 1.6 % | 0.08 % | 4.6 % at 284 K |
| NIST rows 5 K apart | 0.00 % | 0.01 % | 0.4 % | 0.02 % | 1.6 % at 283 K |

μ is the property that matters. It falls by a factor of 4.4 over the range, and the error of the
current rows between 280 and 300 K is 5 %. Re varies as 1/μ, so h for cold water carries an
error of 2–4 %. Interpolating more of the book's rows removes most of it. For example, the 5 K rows
from 275 to 370 K, with 697.9 corrected to 679.7 if the owner agrees, keep the same source. That
also extends the range down to 275 K and up to 370 K. NIST rows 5 K apart do better again, but
the source becomes NIST.

## 4. The three libraries

| | CoolProp | matproplib | KittyCAD material-properties |
|---|---|---|---|
| What it is | Equation-of-state library for fluids, written in C++ with Python bindings | Library of condition-dependent material properties for fusion-plant analysis | JSON files of mechanical properties for design |
| Licence | MIT | LGPL-2.1-or-later | Apache-2.0 |
| State | 8.1.0, active (last push 2026-11-23), 1.1 k stars | 0.0.1, "Development Status: 3 - Alpha", 4 stars | Last push 2024-10, 7 stars, "a work in progress" |
| Install | Wheel of 11 MB for Windows and Linux, 40 MB installed; needs only numpy | Pulls in CoolProp, pydantic ≥ 2.12, pint, matplotlib, scipy, periodictable, csl_reference and others | Data files only; no package |
| Thermal data | ρ, c_p, μ, k of 136 fluids (air, water, nitrogen and refrigerants) at any T and p, plus incompressible liquids such as 30 % ethylene glycol (`INCOMP::MEG-30%`), propylene glycol and heat-transfer oils | SS316L (Choong 1975), copper alloys, tungsten, beryllium, lithium and superconductors. Concrete has density only. Fluids come from CoolProp | **None.** Density, strength, modulus, Poisson's ratio and thermal expansion only, in US units |
| Covers our tables | Air and water, fully | None of our 10 solids, as far as the library files show | Densities of 6061 and Ti-6Al-4V only |

**Recommendation.**
- **KittyCAD: do not use.** It has no thermal properties.
- **matproplib: do not use.** It is alpha, it is LGPL, and it is heavy. It covers none of the
  built-in solids, and its fluids are CoolProp underneath.
- **CoolProp: worth adopting in one limited way. Do not call it from the solver.**
  - **As a build-time table generator (recommended if a change is wanted).** A script would write
    `fluids.json` from CoolProp on a fine grid: air at the chosen pressure, water at 1 atm, and
    optionally glycol mixtures.
    - The program keeps its table-and-interpolate design and its run-time dependencies.
    - The source becomes a single citable reference, with the D11 pressure stated explicitly.
    - The program would not need CoolProp at run time; only the script would.
    - A 151-row table builds in 0.3 ms. Interpolating 10,000 temperatures takes 50 µs.
  - **As a run-time property source (not recommended for version 1).**
    - It would be slower: about 10 µs for each water value, against under 0.01 µs to interpolate
      a table.
    - It adds an 11 MB compiled dependency.
    - It needs a pressure for every call, which the program does not have.
    - It is dangerous near boiling. Asked for water at 0.5 bar and 360 K, CoolProp returns the
      vapour density 0.30 kg/m³ and gives no warning; boiling at that pressure is at 354 K. A
      table cannot change phase without warning in this way.
  - **As a check in the test suite.** A test could compare `fluids.json` against reference values
    to fixed tolerances. Reference values recorded once in the tests would avoid making CoolProp a
    test dependency.
  - **For user fluids (M11.35).** CoolProp's glycol mixtures and oils would be a source of rows for
    a user's own fluid table. That needs no change to M11.35's design.
- The CASRAI guide to CoolProp the owner linked lists the same pitfalls: inputs must be in SI,
  results near saturation can be wrong, and transport properties are less accurate than
  thermodynamic ones for fluids without their own correlation. For air and water this last point
  does not apply, because both have their own correlations.

## 5. What the owner needs to decide (feeds M11.1)

1. **D11.** Label air as "1 bar" (a), or keep "1 atm" and rescale ρ (b).
2. **Water rows.** Keep the 5 rows, or use more rows. If more: all of Incropera's rows from
   275–370 K, or NIST rows. The 5 K Incropera rows cut the μ error from 5.1 % to 1.2 %, and leave
   ρ, c_p and k as they are.
3. **β at 360 K.** Keep the book's 697.9, or correct it to 679.7 as NIST gives.
4. **Air rows.** Use all of Incropera's rows from 250 to 1000 K, 50 K apart. That brings the ρ
   interpolation error from 2.1 % to 0.83 %.
5. **Sources for 6061-T6, Ti-6Al-4V and FR-4.** Name one, or replace them with materials from
   Incropera.
6. **CoolProp.** As a table generator, as a test reference, or not at all.

Recording the sources is covered by this report: Incropera 7th ed., Tables A.1–A.4 and A.6, for
every row except the three solids in item 5. The correlation check is the other half of M11.1. It
can be done against the same book: Churchill–Bernstein, Churchill–Chu, Gnielinski and
Dittus–Boelter are all in it.
