# Limitations

Each entry says what is not available or not as you might expect, and, where the project
documents give one, what to do instead. Entries come from the plan, the handover notes and
the list of open questions (`docs/OPEN_QUESTIONS.md`) of the project.

## Not in this version

- **Two dimensions only.** There is no 3D analysis and no 3D viewport.
- **No flow simulation.** The flow solver is a one-dimensional stream and pipe-network
  model; it is not CFD (no Navier-Stokes solution).
- **No coupled physics.** No structural or thermal-stress coupling and no other physics.
- **No participating-media radiation.**
- **No parallel or distributed solving.**
- **No packaged Windows installer.** Install from source ([Installation](installation.md)).
  The installer is planned (task M11.5).

## Features on hold

The owner has put these on hold. The theory is written down ([Theory](theory.md), §10 and
§12), but the program does not use it. A model that contains an enclosure, or a region
whose material has a phase change, is refused by the validation and by the solver with a
message that says so; it is never solved with that part left out.

- **Enclosure (surface-to-surface) radiation** (milestone M9). The model has an
  "Enclosures" node and an enclosure class, but no solver module evaluates enclosures, so
  a model with an enclosure is not solved. Use radiation to ambient where the
  surroundings can be treated as a single ambient temperature. When it is built, it will
  come for planar models first; the axisymmetric version (task M9.5) is the hardest task
  of the plan and may come later. The verification cases V-22a to V-24 are not active.
- **Phase change (latent heat)** (task M10.2). A material has a phase-change field in its
  data, but the solver does not use it; a region with such a material is not solved.
  The verification case V-36 is not active.
- **HTML report** (task M10.5). For a record of a solution use the text summary
  (`api.summary`, or the output of `thermalfea solve`), the CSV and ParaView (VTU) exports
  and the plot exports.

## Not yet reviewed or checked

- **The window has not been reviewed by a person.** The human gate M8.G (build two
  verification cases in the window and list every point of friction) is not done. The
  window tests run without a screen; on 2026-11-23 a scripted session on a real screen
  (V-10, V-17, V-27 and the dialogs, with screenshots) found and fixed layout and display
  defects. Expect further findings in usability.
- **Property and correlation sources.** Since 2026-11-23 every built-in property comes from
  Incropera et al., *Fundamentals of Heat and Mass Transfer*, 7th ed. (2011), Appendix A,
  except water, which comes from the NIST Chemistry WebBook. Every correlation cites its
  equation in that book, except the Churchill 1977 friction factor. See
  [Materials](materials.md) and [Correlations](correlations.md). One printed value looks
  like a misprint and is kept as printed: oxygen μ at 1300 K (open question Q30).
- **Not yet done:** the verification report (task M11.2), the performance benchmark
  (M11.3) and the release review (M11.6).
- **Several choices await the owner's confirmation** (open questions Q11, Q14,
  Q18.2, Q20, Q21, Q22, Q23, Q24, Q25). The entries below say which.

## Modelling

- **Free points and curves inside a surface are not part of the mesh.** After the geometry
  is built, points and curves that bound no surface are removed. A point load or a probe
  line cannot be made this way.
- **The selection named "all" is reserved.** Every build recreates it.
- **A mesh node cannot be placed at a given point in the window.** To read a value at a
  point, draw the geometry so that the point is a vertex (the verification cases do this
  with two rectangles) and read the value from the CSV export.
- **The mesh quality report only measures.** It applies no pass or fail threshold.
- **A total heat flow or power, and a fixed temperature, cannot depend on temperature.**
  Use a flux, a convection condition or a time function instead. A total heat flow or
  power cannot depend on position either (it is spread uniformly); use a heat flux or a
  heat generation.
- **Material properties may depend on temperature only.** A property that uses t, x or y
  is refused, and so is one that is not finite (for example `sqrt(T - 400)` below 400 K).
- **An inclined plate is limited to ±90° from vertical.** A larger or non-finite angle is
  refused; use the horizontal-plate correlations for a horizontal face.
- **A steady analysis evaluates time-dependent loads at t = 0.**
- **The nonlinear iteration is a modified Newton method.** Derivatives of properties and of
  coefficients with respect to temperature are deliberately left out of the tangent, so
  strongly nonlinear problems may need more iterations. A solution that does not converge
  raises an error (command line exit code 2); it is never returned silently.

## Thermal contact

- **A temperature-dependent contact conductance is refused.** A function of time and
  position is accepted.
- **Results have duplicated nodes along a contact.** The program splits the mesh along the
  contact when it solves. The original nodes keep their numbers and the new nodes are added
  at the end, so node numbers picked on the mesh stay valid.
- **Heat crossing a contact is not in the energy balance,** because it is internal to the
  body. It is stored in the results file at every stored step, in watts, from the lower to
  the higher region number. Results > Contact-heat history plots it, and from a script it
  is `results.term_result("contact_heat:<contact>")`.
- **The geometry factor (thickness or 2πr) is taken from the side with the lower region
  number.** Two regions of different thickness meeting at a contact are not treated
  specially.
- **Other point loads at the end of a contact curve act on one side only** (the side of the
  lower region number). A fixed temperature on such a point fixes both sides.

## DXF import

- Only LINE, ARC, CIRCLE, LWPOLYLINE (with bulges) and SPLINE entities are used. Other
  entity types (for example ELLIPSE, old-style POLYLINE, HATCH, INSERT, TEXT) are ignored,
  with one warning.
- Chains that do not close are ignored, with a warning. A drawing with no closed outline,
  a point where more than two segment ends meet, and anything outside the plane z = 0 are
  errors.
- Outlines are assumed not to cross each other; crossing outlines are not detected. A
  closed outline inside an even number of other outlines becomes a surface; one inside an
  odd number becomes a hole.
- The units header of the file (`$INSUNITS`) is not read. Give the scale on import, as for
  STEP and BREP files.
- End points closer than 1e-6 of the largest extent of the drawing are treated as one
  point. This tolerance cannot be changed.
- An arc is split into pieces of at most 120 degrees, so a semicircle becomes two curves.
- DXF import needs the optional `ezdxf` package.

## Units

- **Expressions are always evaluated in SI,** whatever the display units. See
  [Units](units.md).
- **These places still show SI only:** the HTC calculator window, the solve-progress dialog and the solver messages, the extra
  parameters of a correlation, the CSV and VTU exports (the chart CSV follows the display
  units) and the `api.summary` text.
- Results are shown in the units of the model stored in the results file until you change
  the units in the session. A model whose file units differ from those its results were
  solved with therefore shows the results in the older units until you use Tools > Units...
  once.

## Convection and flow

- **A correlation outside its validity range is still evaluated.** One warning is logged
  for each boundary condition and solve. Check the range on the
  [Correlations](correlations.md) page.
- **The automatic characteristic length** of a plate or vertical channel is the length of the
  selection. For horizontal plates it is half of that, the book's area/perimeter of a strip
  or ring. Cylinders, spheres and non-circular sections need a length. The jets take theirs
  from the nozzle size. An explicit characteristic length always wins.
- **Internal duct flow is not a convection boundary condition.** Use a stream.
- **The Dittus-Boelter and Sieder-Tate options** replace Gnielinski for turbulent flow.
  Their ranges (Re at least 1e4) are not enforced in the transition region, and a stream
  logs no validity warnings for them; the heat-transfer calculator does.
- **Fluid properties outside the table** keep the end values and log one warning for each
  fluid. For an ideal gas the expansion coefficient is still 1/T.
- **Fluid thermal storage is neglected:** the fluid in a stream is quasi-steady. A stream
  has no initial condition; its starting temperatures follow from the initial wall
  temperatures. In a transient, the fluid temperatures are always stepped fully implicitly
  (θ = 1), whatever θ the solid uses. A continued run first recomputes them for the stored
  wall temperatures and the current mass flow and inlet temperature.
- **One specific heat per stream,** taken at its inlet temperature (open question Q18.2,
  awaiting confirmation).
- **Flow must run along the path.** A stream needs a positive mass flow, and a network
  solution that drives a stream against its path is refused.
- **Every network branch needs a stream,** which supplies its flow area, hydraulic
  diameter, roughness and fluid. Two duct branches may not name one stream.
- **Through-plane streams are refused in axisymmetric models.**

## Time stepping and restart

- **The first step uses backward Euler (theta = 1)** when the start is out of equilibrium
  with the loads or the initial temperature differs from a prescribed value. Later jumps
  are detected only at the start of a step; a jump that falls strictly inside a step is
  not seen.
- **Restart allows changed loads and settings.** The mesh, the region materials,
  thicknesses and material angles, and the streams must be those of the results file, or
  the restart is refused. Loads and settings are not compared, and the model stored in the
  results file is replaced by the current one.
- **Restart with automatic stepping** does not reproduce an uninterrupted run exactly: the
  controller's history is not stored, so the steps differ within the time-stepping
  tolerance. With a fixed step the runs agree to round-off (linear case) or to the
  iteration tolerance (nonlinear).
- **A restart is refused** for a steady solution, for a last step that did not converge and
  for an end time the file already reached.

## Known defects from the code review

A code review on 2026-11-20 (`REVIEW.md` in the repository) found nine defects. All nine
are fixed: three in restart (see [Time stepping and restart](#time-stepping-and-restart))
and six by tasks M11.12–M11.16 on 2026-11-22. A second review, of 2026-11-21
(`REVIEW-2.md`), is being worked through as tasks M11.17–M11.36. The property tables and correlations were
rebuilt from the reference text on 2026-11-23 (tasks M11.37–M11.42).

## The window

- **Animation export to GIF blocks the window** while a long animation is written.
- **Animation export to MP4 needs ffmpeg** on the PATH (for example
  `winget install Gyan.FFmpeg`); without it, write a GIF.
- **Probe, chart path pick and the stream "pick path points" toggle all listen to
  viewport clicks.** The probe and the chart path pick exclude each other, but the stream
  toggle does not switch the others off, and it leaves the selection mode at "None" when
  turned off.
- **Probe reads the pixel you click,** not a coordinate. For exact values use the CSV
  export.
- **Selections are named after the field that created them** ("Convection 1 selection"),
  and the tree does not offer to rename a selection.
- **Open charts are not redrawn** when new results arrive. They are marked "(out of date)".
