# Material library

!!! info "Generated page"
    This page is generated from `src/thermalfea/materials/data/solids.json` and `fluids.json` by `scripts/build_guide.py`.
    Do not edit it here: change the source and run the script again.

The built-in library holds solids (conductivity, density and specific heat) and fluids (temperature tables of the properties the convection correlations need). Open it in the program with Tools > Material library.... You can add your own solids and fluids; they are stored in `%APPDATA%/ThermalFEA/materials.json`.

The project documents say the values are "from standard heat-transfer textbook tables". The specific reference text and edition: source not yet recorded; to be confirmed in the release check, task M11.1. Check a value against your own source before relying on it.

## Solids

Every built-in solid is isotropic and has constant properties, quoted near 300 K. A material you create yourself may instead use a table against temperature, or an orthotropic conductivity.

| Name | k [W/(m K)] | ρ [kg/m³] | c_p [J/(kg K)] |
|---|---|---|---|
| Aluminium 6061-T6 | 167 (constant) | 2700 (constant) | 896 (constant) |
| Copper (pure) | 401 (constant) | 8933 (constant) | 385 (constant) |
| Carbon steel AISI 1010 | 63.9 (constant) | 7832 (constant) | 434 (constant) |
| Stainless steel 304 | 14.9 (constant) | 7900 (constant) | 477 (constant) |
| Titanium Ti-6Al-4V | 6.7 (constant) | 4430 (constant) | 526 (constant) |
| Silicon | 148 (constant) | 2330 (constant) | 712 (constant) |
| Alumina (polycrystalline) | 36 (constant) | 3970 (constant) | 765 (constant) |
| Soda-lime glass | 1.4 (constant) | 2500 (constant) | 750 (constant) |
| Concrete (stone mix) | 1.4 (constant) | 2300 (constant) | 880 (constant) |
| FR-4 (through-thickness) | 0.3 (constant) | 1850 (constant) | 1100 (constant) |

## Fluids

Fluid properties are tables against temperature, interpolated linearly. Outside the table the end values are used and a warning is logged. For an ideal gas the expansion coefficient is β = 1/T_film; for a liquid it comes from the β column.

### Air

- Ideal gas: yes
- Temperature range of the tables: 250 K to 1000 K (9 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)] (β is not tabulated; 1/T_film is used)

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] |
|---|---|---|---|---|
| 250 | 1.3947 | 1006 | 1.596e-05 | 0.0223 |
| 300 | 1.1614 | 1007 | 1.846e-05 | 0.0263 |
| 350 | 0.995 | 1009 | 2.082e-05 | 0.03 |
| 400 | 0.8711 | 1014 | 2.301e-05 | 0.0338 |
| 450 | 0.774 | 1021 | 2.507e-05 | 0.0373 |
| 500 | 0.6964 | 1030 | 2.701e-05 | 0.0407 |
| 600 | 0.5804 | 1051 | 3.058e-05 | 0.0469 |
| 800 | 0.4354 | 1099 | 3.698e-05 | 0.0573 |
| 1000 | 0.3482 | 1141 | 4.244e-05 | 0.0667 |

### Water

- Ideal gas: no
- Temperature range of the tables: 280 K to 360 K (5 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)], β [1/K]

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] | β [1/K] |
|---|---|---|---|---|---|
| 280 | 1000 | 4198 | 0.001422 | 0.582 | 4.604e-05 |
| 300 | 997 | 4179 | 0.000855 | 0.613 | 0.0002761 |
| 320 | 989 | 4180 | 0.000577 | 0.64 | 0.0004367 |
| 340 | 979 | 4188 | 0.00042 | 0.66 | 0.000566 |
| 360 | 967 | 4203 | 0.000324 | 0.674 | 0.0006979 |
