# Counterflow double-pipe oil cooler

Model creation and documentation brief  
Implement the selected tube-in-tube engine-oil or lube-oil cooler. Treat this brief as a specification for a proposed case. Preserve the oil and water assignments, counterflow orientation, adiabatic shell and oil-inlet step in every model variant.  
[Original cutaway and axial half-section](https://chatgpt.com/api/library/files/libfile_29d23652a3a48191972c0ca6aefb6c0d/download)

## Geometry and streams

Use an axisymmetric solid mesh of the copper tube wall spanning axial positions x \= 0 to L and radii Di/2 to Do/2. Ds is the shell bore. Require 0 \< Di \< Do \< Ds. Confirm the repository’s radial/axial coordinate ordering before assigning curves. Leave the tube ends insulated. Represent the adiabatic shell by the annulus outer diameter. Omit port and fitting geometry.  
Oil stream: mode="in\_plane", positive mass\_flow, circular duct, inner copper face, polyline from x \= 0 to L. Set flow\_area \= π Di²/4 and wetted\_perimeter \= π Di.  
Water stream: mode="in\_plane", positive mass\_flow, outer copper face, polyline from x \= L to 0\. Set flow\_area \= π(Ds² − Do²)/4 and wetted\_perimeter \= π(Ds \+ Do). Check Dh \= Ds − Do. Select the annulus inner-surface correlation and diameter\_ratio \= Do/Ds after confirming the enum and ratio convention in source. Only the inner perimeter π Do exchanges heat. Confirm integrated oil and water wall areas are π Di L and π Do L respectively.  
Use prescribed independent flows. Verify input names and serialization against src/thermalfea/flow/ and the repository’s bcs.py model classes. Keep the stream names and fluid-node layout stable for restart.

## GUI workaround

Open Add stream twice before creating either stream. Configure one dialog for circular oil and the other for annular water, then create both. Opening the second dialog after committing the first copies its cross-section, which the current window cannot change to the annulus. Reopen the saved case and verify each passage, direction and wall selection.

## Inputs to establish

Record L, Di, Do, Ds \[m\], the two mass flows \[kg/s\], water inlet temperature, oil inlet temperatures before/after the step, step time, material identifiers and property sources. Include copper conductivity, density and heat capacity. Verify the oil grade, temperature range and property units in the fluid library. Record mesh, cells per stream, time steps and solver version. Label chosen numerical values as assumptions until sourced or approved.

## Steady verification

For the reference run prescribe constant h\_o and h\_w using h\_override, constant heat capacities and constant copper k. Choose a span with negligible axial wall conduction relative to the exchanged duty. Use the same inlet conditions and flow rates in the reference and numerical models.  
1/(UA) \= 1/(h\_o π Di L) \+ ln(Do/Di)/(2π k L) \+ 1/(h\_w π Do L).  
C\_o \= ṁ\_o cp\_o and C\_w \= ṁ\_w cp\_w. Set Cmin \= min(C\_o,C\_w), Cmax \= max(C\_o,C\_w), Cr \= Cmin/Cmax and NTU \= UA/Cmin.  
For Cr \< 1, set E \= exp\[−NTU(1−Cr)\] and ε \= (1−E)/(1−Cr E). For Cr \= 1, ε \= NTU/(1+NTU). Use a numerically stable evaluation near Cr \= 1\.  
Qref \= ε Cmin (T\_o,in − T\_w,in). T\_o,out \= T\_o,in − Qref/C\_o. T\_w,out \= T\_w,in \+ Qref/C\_w.  
Compare both outlets and both stream duties with the reference. Report temperature errors in K and duty errors in W and percent. Check convergence under axial mesh and stream-cell refinement and document the tolerance used.

## Correlation run and start-up

Remove h\_override to exercise the duct correlations. Report Re, mean h and the selected correlation on each side. The described implementation uses the annulus diameter-ratio table in laminar flow. Select and document a water Re ≤ 2300 to exercise that specific table. Turbulent operation instead exercises the turbulent duct correlation with annular hydraulic diameter.  
Initialize from the pre-step steady solution. Step up oil T\_inlet(t) only. Hold water inlet and both mass flows fixed. Resolve the step in time, compare with a smaller time step and run until the outlets approach the separately computed post-step steady state. Fluid thermal storage is zero. Interpret the response as copper storage coupled to quasi-steady streams.  
Take oil heat release and water heat gain as positive. Check integral(Q\_oil\_release − Q\_water\_gain) dt \= change in copper internal energy. Document sign conversion from the per-stream heat-pickup output. In the temperature-dependent case use the solver’s stream heat-capacity convention for each reported state.

## Required evidence

Deliver the input model, sourced input table, mesh and stream-cell counts, independent NTU calculation, two-outlet comparison, and labelled plots. Use one axial coordinate: x \= s\_oil and x \= L − s\_water. Plot both bulk temperatures and wall-face temperatures at steady state. Plot oil inlet, both outlets and mid-length copper temperature through the step. Separate analytical predictions from solver results and report residuals and refinement changes.

## Decisions of 2026-11-26 (owner)

- **Illustration:** `Cutaway double-pipe lube oil cooler.png` in this folder replaces the
  chatgpt.com links above. The guide uses a 1400 px copy. The drawing's horizontal axis
  is the model's axial coordinate z; the program draws axisymmetric models with the axis
  vertical (x = r, y = z).
- **Coordinates:** the axial coordinate is called **z** in the guide and in every plot,
  z = s_oil = L − s_water (z = 0 at the oil inlet). Read "x" above as z.
- **Oil:** the library entry "Engine Oil (Unused)", Incropera Table A.5 "unused engine
  oil", 273–430 K. It is not a particular SAE grade.
- **Entrance length:** stated plainly as a simplification. The duct correlations are fully
  developed values (Nu = 3.66 for the oil); at Re ≈ 4 and Pr ≈ 400–550 the oil's thermal
  entry length is comparable with the tube, so the correlation run under-predicts the oil
  film coefficient. The verification run prescribes the film coefficients and is not
  affected.
- **Inputs (approved):** L = 2.0 m; ASTM B88 Type K 3/8 in copper tube, D_o = 12.70 mm,
  wall 1.245 mm, D_i = 10.21 mm (slightly thicker than the 1 mm first proposed, and a
  catalogue size for this kind of cooler); shell bore D_s = 20 mm (D_o/D_s = 0.635);
  oil 0.002 kg/s, water 0.003 kg/s; water inlet 290 K; oil inlet 350 K stepped to 370 K.
- **Step:** the oil inlet rises linearly over 1 s (a table against time), not instantly.
- **Zoom:** window screenshots are zoomed as needed to show the thermal behaviour of the
  1.245 mm wall.
- **Combined plot:** both bulk temperatures and both wall-face temperatures against z, as
  described above, drawn by the example's script.
