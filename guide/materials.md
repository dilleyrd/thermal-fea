# Material library

!!! info "Generated page"
    This page is generated from `src/thermalfea/materials/data/solids.json` and `fluids.json` by `scripts/build_guide.py`.
    Do not edit it here: change the source and run the script again.

The built-in library holds solids (conductivity, density and specific heat) and fluids (temperature tables of the properties the convection correlations need). Open it in the program with Tools > Material library.... You can add your own solids and fluids; they are stored in `%APPDATA%/ThermalFEA/materials.json`.

Every value comes from Bergman, Lavine, Incropera and DeWitt, *Fundamentals of Heat and Mass Transfer*, 7th ed., Wiley, 2011, Appendix A, or from the NIST Chemistry WebBook (water). The source of each entry is listed with it.

## Solids

Every built-in solid has constant properties, quoted at 300 K. Most are isotropic; four are orthotropic and list a second conductivity k2 across the material axis. A material you create yourself may instead use a table against temperature.

| Name | k [W/(m K)] | ρ [kg/m³] | c_p [J/(kg K)] | Source | Note |
|---|---|---|---|---|---|
| Aluminum, Pure | 237 (constant) | 2702 (constant) | 903 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K |  |
| Aluminum, Alloy 2024-T6 | 177 (constant) | 2770 (constant) | 875 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K | 4.5% Cu, 1.5% Mg, 0.6% Mn |
| Aluminum, Alloy 195, Cast | 168 (constant) | 2790 (constant) | 883 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K | 4.5% Cu |
| Beryllium | 200 (constant) | 1850 (constant) | 1825 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K |  |
| Bismuth | 7.86 (constant) | 9780 (constant) | 122 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K |  |
| Boron, Table A.1 | 27 (constant) | 2500 (constant) | 1107 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K |  |
| Cadmium | 96.8 (constant) | 8650 (constant) | 231 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K |  |
| Chromium | 93.7 (constant) | 7160 (constant) | 449 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K |  |
| Cobalt | 99.2 (constant) | 8862 (constant) | 421 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K |  |
| Copper (pure) | 401 (constant) | 8933 (constant) | 385 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K |  |
| Copper, Commercial bronze | 52 (constant) | 8800 (constant) | 420 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K | 90% Cu, 10% Al |
| Copper, Phosphor gear bronze | 54 (constant) | 8780 (constant) | 355 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K | 89% Cu, 11% Sn |
| Copper, Cartridge brass | 110 (constant) | 8530 (constant) | 380 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K | 70% Cu, 30% Zn |
| Copper, Constantan | 23 (constant) | 8920 (constant) | 384 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K | 55% Cu, 45% Ni |
| Germanium | 59.9 (constant) | 5360 (constant) | 322 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 983, 300 K |  |
| Gold | 317 (constant) | 19300 (constant) | 129 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 984, 300 K |  |
| Iridium | 147 (constant) | 22500 (constant) | 130 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 984, 300 K |  |
| Iron, Pure | 80.2 (constant) | 7870 (constant) | 447 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 984, 300 K |  |
| Iron, Armco | 72.7 (constant) | 7870 (constant) | 447 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 984, 300 K | 99.75% pure |
| Carbon steels, Plain carbon | 60.5 (constant) | 7854 (constant) | 434 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 984, 300 K | Mn ≤ 1%, Si ≤ 0.1% |
| Carbon steel AISI 1010 | 63.9 (constant) | 7832 (constant) | 434 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 984, 300 K |  |
| Carbon steels, Carbon–silicon | 51.9 (constant) | 7817 (constant) | 446 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 984, 300 K | Mn ≤ 1%, 0.1% &lt; Si ≤ 0.6% |
| Carbon steels, Carbon–manganese–silicon | 41 (constant) | 8131 (constant) | 434 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 984, 300 K | 1% &lt; Mn ≤ 1.65%, 0.1% &lt; Si ≤ 0.6% |
| Chromium (low) steels, 1/2Cr–1/4Mo–Si | 37.7 (constant) | 7822 (constant) | 444 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 984, 300 K | 0.18% C, 0.65% Cr, 0.23% Mo, 0.6% Si |
| Chromium (low) steels, 1 Cr–1/2Mo | 42.3 (constant) | 7858 (constant) | 442 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 984, 300 K | 0.16% C, 1% Cr, 0.54% Mo, 0.39% Si |
| Chromium (low) steels, 1 Cr–V | 48.9 (constant) | 7836 (constant) | 443 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 984, 300 K | 0.2% C, 1.02% Cr, 0.15% V |
| Stainless steels, AISI 302 | 15.1 (constant) | 8055 (constant) | 480 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Stainless steel 304 | 14.9 (constant) | 7900 (constant) | 477 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Stainless steels, AISI 316 | 13.4 (constant) | 8238 (constant) | 468 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Stainless steels, AISI 347 | 14.2 (constant) | 7978 (constant) | 480 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Lead | 35.3 (constant) | 11340 (constant) | 129 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Magnesium | 156 (constant) | 1740 (constant) | 1024 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Molybdenum | 138 (constant) | 10240 (constant) | 251 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Nickel, Pure | 90.7 (constant) | 8900 (constant) | 444 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Nickel, Nichrome | 12 (constant) | 8400 (constant) | 420 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K | 80% Ni, 20% Cr |
| Nickel, Inconel X-750 | 11.7 (constant) | 8510 (constant) | 439 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K | 73% Ni, 15% Cr, 6.7% Fe |
| Niobium | 53.7 (constant) | 8570 (constant) | 265 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Palladium | 71.8 (constant) | 12020 (constant) | 244 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Platinum, Pure | 71.6 (constant) | 21450 (constant) | 133 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Platinum, Alloy 60Pt–40Rh | 47 (constant) | 16630 (constant) | 162 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K | 60% Pt, 40% Rh |
| Rhenium | 47.9 (constant) | 21100 (constant) | 136 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Rhodium | 150 (constant) | 12450 (constant) | 243 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Silicon | 148 (constant) | 2330 (constant) | 712 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Silver | 429 (constant) | 10500 (constant) | 235 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Tantalum | 57.5 (constant) | 16600 (constant) | 140 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Thorium | 54 (constant) | 11700 (constant) | 118 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Tin | 66.6 (constant) | 7310 (constant) | 227 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 985, 300 K |  |
| Titanium | 21.9 (constant) | 4500 (constant) | 522 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 986, 300 K |  |
| Tungsten | 174 (constant) | 19300 (constant) | 132 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 986, 300 K |  |
| Uranium | 27.6 (constant) | 19070 (constant) | 116 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 986, 300 K |  |
| Vanadium | 30.7 (constant) | 6100 (constant) | 489 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 986, 300 K |  |
| Zinc | 116 (constant) | 7140 (constant) | 389 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 986, 300 K |  |
| Zirconium | 22.7 (constant) | 6570 (constant) | 278 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.1, p. 986, 300 K |  |
| Aluminum oxide, sapphire | 46 (constant) | 3970 (constant) | 765 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 987, 300 K |  |
| Alumina (polycrystalline) | 36 (constant) | 3970 (constant) | 765 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 987, 300 K |  |
| Beryllium oxide | 272 (constant) | 3000 (constant) | 1030 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 987, 300 K |  |
| Boron, Table A.2 | 27.6 (constant) | 2500 (constant) | 1105 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 987, 300 K |  |
| Carbon, Diamond, type IIa insulator | 2300 (constant) | 3500 (constant) | 509 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 987, 300 K |  |
| Pyroceram, Corning 9606 | 3.98 (constant) | 2600 (constant) | 808 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 987, 300 K |  |
| Silicon carbide | 490 (constant) | 3160 (constant) | 675 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 988, 300 K |  |
| Silicon dioxide, polycrystalline (fused silica) | 1.38 (constant) | 2220 (constant) | 745 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 988, 300 K |  |
| Silicon nitride | 16 (constant) | 2400 (constant) | 691 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 988, 300 K |  |
| Sulfur | 0.206 (constant) | 2070 (constant) | 708 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 988, 300 K |  |
| Thorium dioxide | 13 (constant) | 9110 (constant) | 235 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 988, 300 K |  |
| Titanium dioxide, polycrystalline | 8.4 (constant) | 4157 (constant) | 710 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 988, 300 K |  |
| Plywood | 0.12 (constant) | 545 (constant) | 1215 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 989, 300 K |  |
| Sheathing, regular density | 0.055 (constant) | 290 (constant) | 1300 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 989, 300 K |  |
| Acoustic tile | 0.058 (constant) | 290 (constant) | 1340 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 989, 300 K |  |
| Hardboard, siding | 0.094 (constant) | 640 (constant) | 1170 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 989, 300 K |  |
| Hardboard, high density | 0.15 (constant) | 1010 (constant) | 1380 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 989, 300 K |  |
| Particle board, low density | 0.078 (constant) | 590 (constant) | 1300 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 989, 300 K |  |
| Particle board, high density | 0.17 (constant) | 1000 (constant) | 1300 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 989, 300 K |  |
| Woods, Hardwoods (oak, maple) | 0.16 (constant) | 720 (constant) | 1255 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 989, 300 K |  |
| Woods, Softwoods (fir, pine) | 0.12 (constant) | 510 (constant) | 1380 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 989, 300 K |  |
| Cement mortar | 0.72 (constant) | 1860 (constant) | 780 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 989, 300 K |  |
| Brick, common | 0.72 (constant) | 1920 (constant) | 835 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 989, 300 K |  |
| Gypsum plaster, sand aggregate | 0.22 (constant) | 1680 (constant) | 1085 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 989, 300 K |  |
| Glass fiber, coated; duct liner | 0.038 (constant) | 32 (constant) | 835 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 990, 300 K |  |
| Cellular glass | 0.058 (constant) | 145 (constant) | 1000 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 990, 300 K |  |
| Glass fiber, organic bonded | 0.036 (constant) | 105 (constant) | 795 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 990, 300 K |  |
| Polystyrene, expanded, Extruded (R-12) | 0.027 (constant) | 55 (constant) | 1210 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 990, 300 K |  |
| Polystyrene, expanded, Molded beads | 0.04 (constant) | 16 (constant) | 1210 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 990, 300 K |  |
| Wood, shredded/cemented | 0.087 (constant) | 350 (constant) | 1590 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 990, 300 K |  |
| Cork | 0.039 (constant) | 120 (constant) | 1800 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 990, 300 K |  |
| Glass fiber, poured or blown | 0.043 (constant) | 16 (constant) | 835 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 990, 300 K |  |
| Vermiculite, flakes (80 kg/m3) | 0.068 (constant) | 80 (constant) | 835 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 990, 300 K |  |
| Vermiculite, flakes (160 kg/m3) | 0.063 (constant) | 160 (constant) | 1000 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 990, 300 K |  |
| Urethane, two-part mixture; rigid foam | 0.026 (constant) | 70 (constant) | 1045 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 990, 300 K |  |
| Asphalt | 0.062 (constant) | 2115 (constant) | 920 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 993, 300 K |  |
| Bakelite | 1.4 (constant) | 1300 (constant) | 1465 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 993, 300 K |  |
| Clay | 1.3 (constant) | 1460 (constant) | 880 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 993, 300 K |  |
| Coal, anthracite | 0.26 (constant) | 1350 (constant) | 1260 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 993, 300 K |  |
| Concrete (stone mix) | 1.4 (constant) | 2300 (constant) | 880 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 993, 300 K |  |
| Cotton | 0.06 (constant) | 80 (constant) | 1300 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 993, 300 K |  |
| Foodstuffs, Banana | 0.481 (constant) | 980 (constant) | 3350 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 993, 300 K | 75.7% water content |
| Foodstuffs, Apple, red | 0.513 (constant) | 840 (constant) | 3600 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 993, 300 K | 75% water content |
| Soda-lime glass | 1.4 (constant) | 2500 (constant) | 750 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 993, 300 K |  |
| Glass, Pyrex | 1.4 (constant) | 2225 (constant) | 835 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 993, 300 K |  |
| Paper | 0.18 (constant) | 930 (constant) | 1340 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Paraffin | 0.24 (constant) | 900 (constant) | 2890 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Rock, Granite, Barre | 2.79 (constant) | 2630 (constant) | 775 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Rock, Limestone, Salem | 2.15 (constant) | 2320 (constant) | 810 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Rock, Marble, Halston | 2.8 (constant) | 2680 (constant) | 830 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Rock, Quartzite, Sioux | 5.38 (constant) | 2640 (constant) | 1105 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Rock, Sandstone, Berea | 2.9 (constant) | 2150 (constant) | 745 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Rubber, vulcanized, Soft | 0.13 (constant) | 1100 (constant) | 2010 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Sand | 0.27 (constant) | 1515 (constant) | 800 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Soil | 0.52 (constant) | 2050 (constant) | 1840 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Wood, cross grain, Fir | 0.11 (constant) | 415 (constant) | 2720 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Wood, cross grain, Oak | 0.17 (constant) | 545 (constant) | 2385 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Wood, cross grain, Yellow pine | 0.15 (constant) | 640 (constant) | 2805 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Wood, radial, Oak | 0.19 (constant) | 545 (constant) | 2385 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Wood, radial, Fir | 0.14 (constant) | 420 (constant) | 2720 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.3, p. 994, 300 K |  |
| Boron fiber epoxy (30% vol) composite | 2.29 (constant), k2 = 0.59 (constant) | 2080 (constant) | 1122 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 987, 300 K | Orthotropic: k along the material axis (parallel to the fibers), k2 across it. |
| Graphite, pyrolytic | 1950 (constant), k2 = 5.7 (constant) | 2210 (constant) | 709 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 987, 300 K | Orthotropic: k along the material axis (parallel to the layers), k2 across it. |
| Graphite fiber epoxy (25% vol) composite | 11.1 (constant), k2 = 0.87 (constant) | 1400 (constant) | 935 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 987, 300 K | Orthotropic: k along the material axis (parallel to the fibers), k2 across it. |
| Silicon dioxide, crystalline (quartz) | 10.4 (constant), k2 = 6.21 (constant) | 2650 (constant) | 745 (constant) | Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.2, p. 988, 300 K | Orthotropic: k along the material axis (parallel to the c axis), k2 across it. |

## Fluids

Fluid properties are tables against temperature, interpolated linearly. Outside the table the end values are used and a warning is logged. For an ideal gas the expansion coefficient is β = 1/T_film; for a liquid it comes from the β column.

### Air

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.4, p. 995
- Note: Gas at atmospheric pressure; the densities are those of 1 bar.
- Ideal gas: yes
- Temperature range of the tables: 100 K to 3000 K (35 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)] (β is not tabulated; 1/T_film is used)

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] |
|---|---|---|---|---|
| 100 | 3.5562 | 1032 | 7.11e-06 | 0.00934 |
| 150 | 2.3364 | 1012 | 1.034e-05 | 0.0138 |
| 200 | 1.7458 | 1007 | 1.325e-05 | 0.0181 |
| 250 | 1.3947 | 1006 | 1.596e-05 | 0.0223 |
| 300 | 1.1614 | 1007 | 1.846e-05 | 0.0263 |
| 350 | 0.995 | 1009 | 2.082e-05 | 0.03 |
| 400 | 0.8711 | 1014 | 2.301e-05 | 0.0338 |
| 450 | 0.774 | 1021 | 2.507e-05 | 0.0373 |
| 500 | 0.6964 | 1030 | 2.701e-05 | 0.0407 |
| 550 | 0.6329 | 1040 | 2.884e-05 | 0.0439 |
| 600 | 0.5804 | 1051 | 3.058e-05 | 0.0469 |
| 650 | 0.5356 | 1063 | 3.225e-05 | 0.0497 |
| 700 | 0.4975 | 1075 | 3.388e-05 | 0.0524 |
| 750 | 0.4643 | 1087 | 3.546e-05 | 0.0549 |
| 800 | 0.4354 | 1099 | 3.698e-05 | 0.0573 |
| 850 | 0.4097 | 1110 | 3.843e-05 | 0.0596 |
| 900 | 0.3868 | 1121 | 3.981e-05 | 0.062 |
| 950 | 0.3666 | 1131 | 4.113e-05 | 0.0643 |
| 1000 | 0.3482 | 1141 | 4.244e-05 | 0.0667 |
| 1100 | 0.3166 | 1159 | 4.49e-05 | 0.0715 |
| 1200 | 0.2902 | 1175 | 4.73e-05 | 0.0763 |
| 1300 | 0.2679 | 1189 | 4.96e-05 | 0.082 |
| 1400 | 0.2488 | 1207 | 5.3e-05 | 0.091 |
| 1500 | 0.2322 | 1230 | 5.57e-05 | 0.1 |
| 1600 | 0.2177 | 1248 | 5.84e-05 | 0.106 |
| 1700 | 0.2049 | 1267 | 6.11e-05 | 0.113 |
| 1800 | 0.1935 | 1286 | 6.37e-05 | 0.12 |
| 1900 | 0.1833 | 1307 | 6.63e-05 | 0.128 |
| 2000 | 0.1741 | 1337 | 6.89e-05 | 0.137 |
| 2100 | 0.1658 | 1372 | 7.15e-05 | 0.147 |
| 2200 | 0.1582 | 1417 | 7.4e-05 | 0.16 |
| 2300 | 0.1513 | 1478 | 7.66e-05 | 0.175 |
| 2400 | 0.1448 | 1558 | 7.92e-05 | 0.196 |
| 2500 | 0.1389 | 1665 | 8.18e-05 | 0.222 |
| 3000 | 0.1135 | 2726 | 9.55e-05 | 0.486 |

### Water

- Source: NIST Chemistry WebBook, SRD 69, Thermophysical Properties of Fluid Systems, water at 0.1 MPa, read 2026-11-23
- Note: Liquid water at 1 bar, rounded to 6 significant figures. beta = -(1/rho) d(rho)/dT from NIST densities 1 K apart (central difference).
- Ideal gas: no
- Temperature range of the tables: 280 K to 370 K (19 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)], β [1/K]

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] | β [1/K] |
|---|---|---|---|---|---|
| 280 | 999.91 | 4200.94 | 0.00143357 | 0.57198 | 4.38284e-05 |
| 285 | 999.517 | 4192.37 | 0.00123921 | 0.582589 | 0.000112117 |
| 290 | 998.803 | 4186.6 | 0.00108397 | 0.592297 | 0.000172258 |
| 295 | 997.807 | 4182.87 | 0.000957811 | 0.601236 | 0.000226049 |
| 300 | 996.556 | 4180.64 | 0.000853743 | 0.609499 | 0.000274797 |
| 305 | 995.075 | 4179.52 | 0.000766792 | 0.617159 | 0.00031948 |
| 310 | 993.383 | 4179.24 | 0.000693329 | 0.624269 | 0.000360847 |
| 315 | 991.496 | 4179.63 | 0.000630656 | 0.63087 | 0.000399483 |
| 320 | 989.426 | 4180.54 | 0.000576726 | 0.636995 | 0.000435851 |
| 325 | 987.187 | 4181.9 | 0.000529966 | 0.642668 | 0.000470329 |
| 330 | 984.786 | 4183.65 | 0.000489147 | 0.647911 | 0.000503223 |
| 335 | 982.233 | 4185.79 | 0.000453296 | 0.652739 | 0.000534791 |
| 340 | 979.535 | 4188.3 | 0.000421633 | 0.657167 | 0.00056525 |
| 345 | 976.699 | 4191.18 | 0.000393529 | 0.661208 | 0.000594787 |
| 350 | 973.728 | 4194.47 | 0.000368469 | 0.664873 | 0.000623562 |
| 355 | 970.628 | 4198.18 | 0.000346029 | 0.668172 | 0.000651719 |
| 360 | 967.403 | 4202.34 | 0.000325855 | 0.671114 | 0.000679384 |
| 365 | 964.057 | 4206.99 | 0.000307653 | 0.673707 | 0.000706673 |
| 370 | 960.591 | 4212.15 | 0.000291175 | 0.675961 | 0.000733693 |

### Ammonia

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.4, p. 995-996
- Note: Gas at atmospheric pressure; the densities are those of 1 bar.
- Ideal gas: yes
- Temperature range of the tables: 300 K to 580 K (15 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)] (β is not tabulated; 1/T_film is used)

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] |
|---|---|---|---|---|
| 300 | 0.6894 | 2158 | 1.015e-05 | 0.0247 |
| 320 | 0.6448 | 2170 | 1.09e-05 | 0.0272 |
| 340 | 0.6059 | 2192 | 1.165e-05 | 0.0293 |
| 360 | 0.5716 | 2221 | 1.24e-05 | 0.0316 |
| 380 | 0.541 | 2254 | 1.31e-05 | 0.034 |
| 400 | 0.5136 | 2287 | 1.38e-05 | 0.037 |
| 420 | 0.4888 | 2322 | 1.45e-05 | 0.0404 |
| 440 | 0.4664 | 2357 | 1.525e-05 | 0.0435 |
| 460 | 0.446 | 2393 | 1.59e-05 | 0.0463 |
| 480 | 0.4273 | 2430 | 1.665e-05 | 0.0492 |
| 500 | 0.4101 | 2467 | 1.73e-05 | 0.0525 |
| 520 | 0.3942 | 2504 | 1.8e-05 | 0.0545 |
| 540 | 0.3795 | 2540 | 1.865e-05 | 0.0575 |
| 560 | 0.3708 | 2577 | 1.93e-05 | 0.0606 |
| 580 | 0.3533 | 2613 | 1.995e-05 | 0.0638 |

### Carbon Dioxide

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.4, p. 996
- Note: Gas at atmospheric pressure; the densities are those of 1 bar.
- Ideal gas: yes
- Temperature range of the tables: 280 K to 800 K (15 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)] (β is not tabulated; 1/T_film is used)

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] |
|---|---|---|---|---|
| 280 | 1.9022 | 830 | 1.4e-05 | 0.0152 |
| 300 | 1.773 | 851 | 1.49e-05 | 0.01655 |
| 320 | 1.6609 | 872 | 1.56e-05 | 0.01805 |
| 340 | 1.5618 | 891 | 1.65e-05 | 0.0197 |
| 360 | 1.4743 | 908 | 1.73e-05 | 0.0212 |
| 380 | 1.3961 | 926 | 1.81e-05 | 0.02275 |
| 400 | 1.3257 | 942 | 1.9e-05 | 0.0243 |
| 450 | 1.1782 | 981 | 2.1e-05 | 0.0283 |
| 500 | 1.0594 | 1020 | 2.31e-05 | 0.0325 |
| 550 | 0.9625 | 1050 | 2.51e-05 | 0.0366 |
| 600 | 0.8826 | 1080 | 2.7e-05 | 0.0407 |
| 650 | 0.8143 | 1100 | 2.88e-05 | 0.0445 |
| 700 | 0.7564 | 1130 | 3.05e-05 | 0.0481 |
| 750 | 0.7057 | 1150 | 3.21e-05 | 0.0517 |
| 800 | 0.6614 | 1170 | 3.37e-05 | 0.0551 |

### Carbon Monoxide

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.4, p. 996-997
- Note: Gas at atmospheric pressure; the densities are those of 1 bar.
- Ideal gas: yes
- Temperature range of the tables: 200 K to 800 K (19 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)] (β is not tabulated; 1/T_film is used)

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] |
|---|---|---|---|---|
| 200 | 1.6888 | 1045 | 1.27e-05 | 0.017 |
| 220 | 1.5341 | 1044 | 1.37e-05 | 0.019 |
| 240 | 1.4055 | 1043 | 1.47e-05 | 0.0206 |
| 260 | 1.2967 | 1043 | 1.57e-05 | 0.0221 |
| 280 | 1.2038 | 1042 | 1.66e-05 | 0.0236 |
| 300 | 1.1233 | 1043 | 1.75e-05 | 0.025 |
| 320 | 1.0529 | 1043 | 1.84e-05 | 0.0263 |
| 340 | 0.9909 | 1044 | 1.93e-05 | 0.0278 |
| 360 | 0.9357 | 1045 | 2.02e-05 | 0.0291 |
| 380 | 0.8864 | 1047 | 2.1e-05 | 0.0305 |
| 400 | 0.8421 | 1049 | 2.18e-05 | 0.0318 |
| 450 | 0.7483 | 1055 | 2.37e-05 | 0.035 |
| 500 | 0.67352 | 1065 | 2.54e-05 | 0.0381 |
| 550 | 0.61226 | 1076 | 2.71e-05 | 0.0411 |
| 600 | 0.56126 | 1088 | 2.86e-05 | 0.044 |
| 650 | 0.51806 | 1101 | 3.01e-05 | 0.047 |
| 700 | 0.48102 | 1114 | 3.15e-05 | 0.05 |
| 750 | 0.44899 | 1127 | 3.29e-05 | 0.0528 |
| 800 | 0.42095 | 1140 | 3.43e-05 | 0.0555 |

### Helium

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.4, p. 997
- Note: Gas at atmospheric pressure; the densities are those of 1 atm.
- Ideal gas: yes
- Temperature range of the tables: 100 K to 1000 K (11 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)] (β is not tabulated; 1/T_film is used)

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] |
|---|---|---|---|---|
| 100 | 0.4871 | 5193 | 9.63e-06 | 0.073 |
| 120 | 0.406 | 5193 | 1.07e-05 | 0.0819 |
| 140 | 0.3481 | 5193 | 1.18e-05 | 0.0907 |
| 180 | 0.2708 | 5193 | 1.39e-05 | 0.1072 |
| 220 | 0.2216 | 5193 | 1.6e-05 | 0.1231 |
| 260 | 0.1875 | 5193 | 1.8e-05 | 0.137 |
| 300 | 0.1625 | 5193 | 1.99e-05 | 0.152 |
| 400 | 0.1219 | 5193 | 2.43e-05 | 0.187 |
| 500 | 0.09754 | 5193 | 2.83e-05 | 0.22 |
| 700 | 0.06969 | 5193 | 3.5e-05 | 0.278 |
| 1000 | 0.04879 | 5193 | 4.46e-05 | 0.354 |

### Hydrogen

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.4, p. 997-998
- Note: Gas at atmospheric pressure; the densities are those of 1 bar.
- Ideal gas: yes
- Temperature range of the tables: 100 K to 2000 K (25 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)] (β is not tabulated; 1/T_film is used)

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] |
|---|---|---|---|---|
| 100 | 0.24255 | 11230 | 4.21e-06 | 0.067 |
| 150 | 0.16156 | 12600 | 5.6e-06 | 0.101 |
| 200 | 0.12115 | 13540 | 6.81e-06 | 0.131 |
| 250 | 0.09693 | 14060 | 7.89e-06 | 0.157 |
| 300 | 0.08078 | 14310 | 8.96e-06 | 0.183 |
| 350 | 0.06924 | 14430 | 9.88e-06 | 0.204 |
| 400 | 0.06059 | 14480 | 1.082e-05 | 0.226 |
| 450 | 0.05386 | 14500 | 1.172e-05 | 0.247 |
| 500 | 0.04848 | 14520 | 1.264e-05 | 0.266 |
| 550 | 0.04407 | 14530 | 1.343e-05 | 0.285 |
| 600 | 0.0404 | 14550 | 1.424e-05 | 0.305 |
| 700 | 0.03463 | 14610 | 1.578e-05 | 0.342 |
| 800 | 0.0303 | 14700 | 1.724e-05 | 0.378 |
| 900 | 0.02694 | 14830 | 1.865e-05 | 0.412 |
| 1000 | 0.02424 | 14990 | 2.013e-05 | 0.448 |
| 1100 | 0.02204 | 15170 | 2.13e-05 | 0.488 |
| 1200 | 0.0202 | 15370 | 2.262e-05 | 0.528 |
| 1300 | 0.01865 | 15590 | 2.385e-05 | 0.568 |
| 1400 | 0.01732 | 15810 | 2.507e-05 | 0.61 |
| 1500 | 0.01616 | 16020 | 2.627e-05 | 0.655 |
| 1600 | 0.0152 | 16280 | 2.737e-05 | 0.697 |
| 1700 | 0.0143 | 16580 | 2.849e-05 | 0.742 |
| 1800 | 0.0135 | 16960 | 2.961e-05 | 0.786 |
| 1900 | 0.0128 | 17490 | 3.072e-05 | 0.835 |
| 2000 | 0.0121 | 18250 | 3.182e-05 | 0.878 |

### Nitrogen

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.4, p. 998
- Note: Gas at atmospheric pressure; the densities are those of 1 bar.
- Ideal gas: yes
- Temperature range of the tables: 100 K to 1300 K (18 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)] (β is not tabulated; 1/T_film is used)

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] |
|---|---|---|---|---|
| 100 | 3.4388 | 1070 | 6.88e-06 | 0.00958 |
| 150 | 2.2594 | 1050 | 1.006e-05 | 0.0139 |
| 200 | 1.6883 | 1043 | 1.292e-05 | 0.0183 |
| 250 | 1.3488 | 1042 | 1.549e-05 | 0.0222 |
| 300 | 1.1233 | 1041 | 1.782e-05 | 0.0259 |
| 350 | 0.9625 | 1042 | 2e-05 | 0.0293 |
| 400 | 0.8425 | 1045 | 2.204e-05 | 0.0327 |
| 450 | 0.7485 | 1050 | 2.396e-05 | 0.0358 |
| 500 | 0.6739 | 1056 | 2.577e-05 | 0.0389 |
| 550 | 0.6124 | 1065 | 2.747e-05 | 0.0417 |
| 600 | 0.5615 | 1075 | 2.908e-05 | 0.0446 |
| 700 | 0.4812 | 1098 | 3.21e-05 | 0.0499 |
| 800 | 0.4211 | 1122 | 3.491e-05 | 0.0548 |
| 900 | 0.3743 | 1146 | 3.753e-05 | 0.0597 |
| 1000 | 0.3368 | 1167 | 3.999e-05 | 0.0647 |
| 1100 | 0.3062 | 1187 | 4.232e-05 | 0.07 |
| 1200 | 0.2807 | 1204 | 4.453e-05 | 0.0758 |
| 1300 | 0.2591 | 1219 | 4.662e-05 | 0.081 |

### Oxygen

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.4, p. 998-999
- Note: Gas at atmospheric pressure; the densities are those of 1 bar.
- Ideal gas: yes
- Temperature range of the tables: 100 K to 1300 K (18 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)] (β is not tabulated; 1/T_film is used)

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] |
|---|---|---|---|---|
| 100 | 3.945 | 962 | 7.64e-06 | 0.00925 |
| 150 | 2.585 | 921 | 1.148e-05 | 0.0138 |
| 200 | 1.93 | 915 | 1.475e-05 | 0.0183 |
| 250 | 1.542 | 915 | 1.786e-05 | 0.0226 |
| 300 | 1.284 | 920 | 2.072e-05 | 0.0268 |
| 350 | 1.1 | 929 | 2.335e-05 | 0.0296 |
| 400 | 0.962 | 942 | 2.582e-05 | 0.033 |
| 450 | 0.8554 | 956 | 2.814e-05 | 0.0363 |
| 500 | 0.7698 | 972 | 3.033e-05 | 0.0412 |
| 550 | 0.6998 | 988 | 3.24e-05 | 0.0441 |
| 600 | 0.6414 | 1003 | 3.437e-05 | 0.0473 |
| 700 | 0.5498 | 1031 | 3.808e-05 | 0.0528 |
| 800 | 0.481 | 1054 | 4.152e-05 | 0.0589 |
| 900 | 0.4275 | 1074 | 4.472e-05 | 0.0649 |
| 1000 | 0.3848 | 1090 | 4.77e-05 | 0.071 |
| 1100 | 0.3498 | 1103 | 5.055e-05 | 0.0758 |
| 1200 | 0.3206 | 1115 | 5.325e-05 | 0.0819 |
| 1300 | 0.296 | 1125 | 5.884e-05 | 0.0871 |

### Water Vapor (Steam)

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.4, p. 999
- Note: Gas at atmospheric pressure; the densities are those of 1 atm.
- Ideal gas: yes
- Temperature range of the tables: 380 K to 850 K (11 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)] (β is not tabulated; 1/T_film is used)

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] |
|---|---|---|---|---|
| 380 | 0.5863 | 2060 | 1.271e-05 | 0.0246 |
| 400 | 0.5542 | 2014 | 1.344e-05 | 0.0261 |
| 450 | 0.4902 | 1980 | 1.525e-05 | 0.0299 |
| 500 | 0.4405 | 1985 | 1.704e-05 | 0.0339 |
| 550 | 0.4005 | 1997 | 1.884e-05 | 0.0379 |
| 600 | 0.3652 | 2026 | 2.067e-05 | 0.0422 |
| 650 | 0.338 | 2056 | 2.247e-05 | 0.0464 |
| 700 | 0.314 | 2085 | 2.426e-05 | 0.0505 |
| 750 | 0.2931 | 2119 | 2.604e-05 | 0.0549 |
| 800 | 0.2739 | 2152 | 2.786e-05 | 0.0592 |
| 850 | 0.2579 | 2186 | 2.969e-05 | 0.0637 |

### Engine Oil (Unused)

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.5 (saturated liquids), p. 1000
- Note: Saturated liquid.
- Ideal gas: no
- Temperature range of the tables: 273 K to 430 K (17 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)], β [1/K]

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] | β [1/K] |
|---|---|---|---|---|---|
| 273 | 899.1 | 1796 | 3.85 | 0.147 | 0.0007 |
| 280 | 895.3 | 1827 | 2.17 | 0.144 | 0.0007 |
| 290 | 890 | 1868 | 0.999 | 0.145 | 0.0007 |
| 300 | 884.1 | 1909 | 0.486 | 0.145 | 0.0007 |
| 310 | 877.9 | 1951 | 0.253 | 0.145 | 0.0007 |
| 320 | 871.8 | 1993 | 0.141 | 0.143 | 0.0007 |
| 330 | 865.8 | 2035 | 0.0836 | 0.141 | 0.0007 |
| 340 | 859.9 | 2076 | 0.0531 | 0.139 | 0.0007 |
| 350 | 853.9 | 2118 | 0.0356 | 0.138 | 0.0007 |
| 360 | 847.8 | 2161 | 0.0252 | 0.138 | 0.0007 |
| 370 | 841.8 | 2206 | 0.0186 | 0.137 | 0.0007 |
| 380 | 836 | 2250 | 0.0141 | 0.136 | 0.0007 |
| 390 | 830.6 | 2294 | 0.011 | 0.135 | 0.0007 |
| 400 | 825.1 | 2337 | 0.00874 | 0.134 | 0.0007 |
| 410 | 818.9 | 2381 | 0.00698 | 0.133 | 0.0007 |
| 420 | 812.1 | 2427 | 0.00564 | 0.133 | 0.0007 |
| 430 | 806.5 | 2471 | 0.0047 | 0.132 | 0.0007 |

### Ethylene Glycol

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.5 (saturated liquids), p. 1000
- Note: Saturated liquid.
- Ideal gas: no
- Temperature range of the tables: 273 K to 373 K (12 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)], β [1/K]

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] | β [1/K] |
|---|---|---|---|---|---|
| 273 | 1130.8 | 2294 | 0.0651 | 0.242 | 0.00065 |
| 280 | 1125.8 | 2323 | 0.042 | 0.244 | 0.00065 |
| 290 | 1118.8 | 2368 | 0.0247 | 0.248 | 0.00065 |
| 300 | 1114.4 | 2415 | 0.0157 | 0.252 | 0.00065 |
| 310 | 1103.7 | 2460 | 0.0107 | 0.255 | 0.00065 |
| 320 | 1096.2 | 2505 | 0.00757 | 0.258 | 0.00065 |
| 330 | 1089.5 | 2549 | 0.00561 | 0.26 | 0.00065 |
| 340 | 1083.8 | 2592 | 0.00431 | 0.261 | 0.00065 |
| 350 | 1079 | 2637 | 0.00342 | 0.261 | 0.00065 |
| 360 | 1074 | 2682 | 0.00278 | 0.261 | 0.00065 |
| 370 | 1066.7 | 2728 | 0.00228 | 0.262 | 0.00065 |
| 373 | 1058.5 | 2742 | 0.00215 | 0.263 | 0.00065 |

### Glycerin

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.5 (saturated liquids), p. 1000
- Note: Saturated liquid.
- Ideal gas: no
- Temperature range of the tables: 273 K to 320 K (6 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)], β [1/K]

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] | β [1/K] |
|---|---|---|---|---|---|
| 273 | 1276 | 2261 | 10.6 | 0.282 | 0.00047 |
| 280 | 1271.9 | 2298 | 5.34 | 0.284 | 0.00047 |
| 290 | 1265.8 | 2367 | 1.85 | 0.286 | 0.00048 |
| 300 | 1259.9 | 2427 | 0.799 | 0.286 | 0.00048 |
| 310 | 1253.9 | 2490 | 0.352 | 0.286 | 0.00049 |
| 320 | 1247.2 | 2564 | 0.21 | 0.287 | 0.0005 |

### Refrigerant-134a

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.5 (saturated liquids), p. 1001
- Note: Saturated liquid.
- Ideal gas: no
- Temperature range of the tables: 230 K to 370 K (15 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)], β [1/K]

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] | β [1/K] |
|---|---|---|---|---|---|
| 230 | 1426.8 | 1249 | 0.0004912 | 0.1121 | 0.00202 |
| 240 | 1397.7 | 1267 | 0.0004202 | 0.1073 | 0.00211 |
| 250 | 1367.9 | 1287 | 0.0003633 | 0.1025 | 0.00223 |
| 260 | 1337.1 | 1308 | 0.0003166 | 0.0979 | 0.00236 |
| 270 | 1305.1 | 1333 | 0.0002775 | 0.0934 | 0.00253 |
| 280 | 1271.8 | 1361 | 0.0002443 | 0.089 | 0.00273 |
| 290 | 1236.8 | 1393 | 0.0002156 | 0.0846 | 0.00298 |
| 300 | 1199.7 | 1432 | 0.0001905 | 0.0803 | 0.0033 |
| 310 | 1159.9 | 1481 | 0.000168 | 0.0761 | 0.00373 |
| 320 | 1116.8 | 1543 | 0.0001478 | 0.0718 | 0.00433 |
| 330 | 1069.1 | 1627 | 0.0001292 | 0.0675 | 0.00519 |
| 340 | 1015 | 1751 | 0.0001118 | 0.0631 | 0.00657 |
| 350 | 951.3 | 1961 | 9.51e-05 | 0.0586 | 0.0091 |
| 360 | 870.1 | 2437 | 7.81e-05 | 0.0541 | 0.01539 |
| 370 | 740.3 | 5105 | 5.8e-05 | 0.0518 | 0.05524 |

### Refrigerant-22

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.5 (saturated liquids), p. 1001
- Note: Saturated liquid.
- Ideal gas: no
- Temperature range of the tables: 230 K to 360 K (14 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)], β [1/K]

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] | β [1/K] |
|---|---|---|---|---|---|
| 230 | 1416 | 1087 | 0.0003558 | 0.1145 | 0.00205 |
| 240 | 1386.6 | 1100 | 0.0003145 | 0.1098 | 0.00216 |
| 250 | 1356.3 | 1117 | 0.0002796 | 0.1052 | 0.00229 |
| 260 | 1324.9 | 1137 | 0.0002497 | 0.1007 | 0.00245 |
| 270 | 1292.1 | 1161 | 0.0002235 | 0.0962 | 0.00263 |
| 280 | 1257.9 | 1189 | 0.0002005 | 0.0917 | 0.00286 |
| 290 | 1221.7 | 1223 | 0.0001798 | 0.0872 | 0.00315 |
| 300 | 1183.4 | 1265 | 0.000161 | 0.0826 | 0.00351 |
| 310 | 1142.2 | 1319 | 0.0001438 | 0.0781 | 0.004 |
| 320 | 1097.4 | 1391 | 0.0001278 | 0.0734 | 0.00469 |
| 330 | 1047.5 | 1495 | 0.0001127 | 0.0686 | 0.00575 |
| 340 | 990.1 | 1665 | 9.8e-05 | 0.0636 | 0.00756 |
| 350 | 920.1 | 1997 | 8.31e-05 | 0.0583 | 0.01135 |
| 360 | 823.4 | 3001 | 6.68e-05 | 0.0531 | 0.02388 |

### Mercury

- Source: Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., 2011, Table A.5 (saturated liquids), p. 1001
- Note: Saturated liquid.
- Ideal gas: no
- Temperature range of the tables: 273 K to 600 K (8 points)
- Tabulated properties: ρ [kg/m³], c_p [J/(kg K)], μ [Pa s], k [W/(m K)], β [1/K]

| T [K] | ρ [kg/m³] | c_p [J/(kg K)] | μ [Pa s] | k [W/(m K)] | β [1/K] |
|---|---|---|---|---|---|
| 273 | 13595 | 140.4 | 0.001688 | 8.18 | 0.000181 |
| 300 | 13529 | 139.3 | 0.001523 | 8.54 | 0.000181 |
| 350 | 13407 | 137.7 | 0.001309 | 9.18 | 0.000181 |
| 400 | 13287 | 136.5 | 0.001171 | 9.8 | 0.000181 |
| 450 | 13167 | 135.7 | 0.001075 | 10.4 | 0.000181 |
| 500 | 13048 | 135.3 | 0.001007 | 10.95 | 0.000182 |
| 550 | 12929 | 135.2 | 0.000953 | 11.45 | 0.000184 |
| 600 | 12809 | 135.5 | 0.000911 | 11.95 | 0.000187 |
