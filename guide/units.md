# Unit systems

!!! info "Generated page"
    This page is generated from `src/thermalfea/core/units.py` by `scripts/build_guide.py`.
    Do not edit it here: change the source and run the script again.

## What the units setting does

Choose the units numbers are shown and typed in with Tools > Units.... The dialog has a "Preset" box and one box per quantity. A preset only fills the boxes in; any one of them can be changed afterwards, and the preset box then reads "Custom". The change is one undo step.

Units are display units only:

- The model file (`.tfea`) and the results file store every value in SI, with temperature in kelvin. Changing units changes neither the model nor its results, and makes nothing out of date.
- Results (plots, read-outs) are shown in the units of the model stored in the results file until you change the units in the session; after that they follow the model.
- Temperature differences follow the temperature unit (K for K and °C, °F degrees for °F).
- All conversion factors follow from the exact definitions of the inch, foot, pound, International Table BTU and pound-force.

## Expressions are always SI

A function given as an expression is evaluated with t in s, x and y in m and T in K, and it returns the SI unit of the quantity, whatever the display units are. The function editor says so when a display unit is not SI. Constants and tables are converted.

## Places that still show SI only

- the parameters of a geometry transform (the label says so);
- the HTC calculator window (Tools > HTC calculator...);
- the solve-progress dialog and the solver messages;
- the extra parameters of a correlation;
- CSV and VTU export (the chart CSV, however, follows the display units);
- the text of `thermalfea.api.summary`.

## Presets

| Quantity | SI (m) | SI (mm) | US customary |
|---|---|---|---|
| Temperature | K | K | °F |
| Length | m | mm | in |
| Area | m^2 | mm^2 | in^2 |
| Angle | rad | deg | deg |
| Time | s | s | s |
| Velocity | m/s | mm/s | ft/s |
| Thermal conductivity | W/(m K) | W/(mm K) | BTU/(h ft °F) |
| Heat-transfer coefficient | W/(m^2 K) | W/(mm^2 K) | BTU/(h ft^2 °F) |
| Heat flux | W/m^2 | W/mm^2 | BTU/(h ft^2) |
| Volumetric heat generation | W/m^3 | W/mm^3 | BTU/(h ft^3) |
| Heat flow / power | W | W | BTU/h |
| Density | kg/m^3 | kg/mm^3 | lbm/ft^3 |
| Specific heat | J/(kg K) | J/(kg K) | BTU/(lbm °F) |
| Mass flow | kg/s | kg/s | lbm/s |
| Pressure | Pa | MPa | psi |

The SI presets keep K or °C as it is when you choose them (a model in °F goes to °C); "US customary" always sets °F. In "US customary" lengths are in inches but the heat-transfer units use feet.

## Units you can choose

The first unit listed for each quantity is the SI unit.

| Quantity | Units offered |
|---|---|
| Temperature | K, °C, °F |
| Length | m, mm, in |
| Area | m^2, mm^2, in^2 |
| Angle | rad, deg |
| Time | s, min, h |
| Velocity | m/s, mm/s, ft/s |
| Thermal conductivity | W/(m K), W/(mm K), BTU/(h ft °F) |
| Heat-transfer coefficient | W/(m^2 K), W/(mm^2 K), BTU/(h ft^2 °F) |
| Heat flux | W/m^2, W/mm^2, BTU/(h ft^2) |
| Volumetric heat generation | W/m^3, W/mm^3, BTU/(h ft^3) |
| Heat flow / power | W, kW, BTU/h |
| Density | kg/m^3, kg/mm^3, lbm/ft^3 |
| Specific heat | J/(kg K), kJ/(kg K), BTU/(lbm °F) |
| Mass flow | kg/s, lbm/s, lbm/h |
| Pressure | Pa, kPa, MPa, bar, psi |
