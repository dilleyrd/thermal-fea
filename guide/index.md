# ThermalFEA

ThermalFEA is a desktop program for two-dimensional steady-state and transient heat
conduction by the finite-element method. You draw or import a geometry, mesh it, apply
loads and boundary conditions, solve, and look at the results. Everything the program does
in the window can also be done from a Python script or the command line.

This guide is for an engineer who has used a finite-element program before but has not
seen this one.

## What the program does

- **Analysis:** steady-state and transient, linear and nonlinear (temperature-dependent
  properties, radiation, convection correlations).
- **Models:** planar models (with a thickness per region) and axisymmetric models
  (x is the radius, y is the axis).
- **Elements:** 3-node and 6-node triangles, 4-node and 8-node quadrilaterals.
- **Materials:** isotropic or orthotropic conductivity, density and specific heat, each
  constant or a table against temperature. A built-in library of solids and fluids is
  included ([Materials](materials.md)).
- **Geometry:** points, lines, arcs, circles, rectangles, polygons and splines; union,
  cut and intersect; translate, rotate, mirror and scale; import of STEP, BREP and DXF
  files.
- **Meshing:** free meshing with triangles or quad-dominant meshes, structured meshing,
  size control, linear or quadratic elements and a quality report. Meshing uses gmsh.
- **Loads and boundary conditions:** fixed temperature, heat flux, heat flow in watts,
  volumetric heat generation, convection (a given coefficient, or a coefficient from a
  correlation), radiation to the ambient, thermal contact resistance and initial
  conditions. A load value may be a constant, a table against time, or an expression of
  time, position and temperature.
- **Convection library:** forced and natural convection correlations for plates,
  cylinders and ducts, with temperature-dependent fluid properties
  ([Correlations](correlations.md)).
- **Flow solver:** one-dimensional streams and pipe networks. From a given flow rate the
  program computes velocity, Reynolds number, heat-transfer coefficient, pressure drop and
  the rise of the fluid temperature along the wall, coupled to the solid.
- **Post-processing:** contour and vector plots, nodal temperature against time, plots
  along a path, probes, minimum and maximum, reaction heat flows, the energy balance,
  animation, and export to CSV, VTK (ParaView) and PNG.
- **Files:** the model is a JSON file (`.tfea`); results are stored beside it in an HDF5
  file (`<model>.tfea.h5`).

## What the program does not do

- No three-dimensional analysis, no flow simulation (CFD), no structural or thermal-stress
  coupling, no other physics, no radiation through participating media, no parallel
  solving.
- Enclosure (surface-to-surface) radiation, phase change (latent heat) and the HTML report
  are not available in this version; they are on hold.
- There is no packaged Windows installer yet.

[Limitations](limitations.md) lists these and the smaller known gaps in one place.

## Map of the guide

| Page | What it holds |
|---|---|
| [Installation](installation.md) | Requirements, installing, starting the program, the command line |
| [Getting started](getting-started.md) | The workflow in the window and from the command line |
| Tutorials | [NAFEMS T4 steady plate](tutorials/t4-plate.md), [transient quench of a fin](tutorials/fin-quench.md), [cold plate with a water stream](tutorials/cold-plate.md) |
| Examples | [Main closure of a canned-motor pump](examples/pump-closure.md): an axisymmetric assembly with contacts, heat-up, steady state and a parameter study |
| [Units](units.md) | The unit systems and what they change |
| [Materials](materials.md) | The built-in material library |
| [Correlations](correlations.md) | Every convection correlation, with its validity range |
| [Theory](theory.md) | Every equation the program implements |
| [Verification](verification.md) | The benchmark cases the program is checked against and their tolerances |
| [Limitations](limitations.md) | What is not available or not yet reviewed |

The pages Units, Materials, Correlations, Theory and Verification are generated from the
project's own documents and code, so they cannot drift from what the program does.

## Conventions in this guide

- Values are SI (metres, seconds, kelvin, watts) unless a page says otherwise. The program
  can show other units; see [Units](units.md). Files always store SI.
- A heat flow is reported as positive when heat enters the body.
- Menu entries are written as in the program, for example File > Examples.
