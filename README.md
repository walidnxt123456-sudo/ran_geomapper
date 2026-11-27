# RAN-GeoMapper Studio (`CellFileToKml`)

Desktop (Tkinter) and CLI utility for validating mobile Radio Access Network (RAN) cell datasets (`2G`, `3G`, `4G`, `5G`, and `MSAN`), translating channel/frequency numbers into standardized bands, auditing data anomalies, and generating Google Earth `KMZ` / `KML` sector maps.

## Key Features

- **Two-Phase Workflow**:
  1. **Discovery (`discover`)**: Reads `.xlsx`, `.xls`, and `.csv` files, computes a column-layout signature, maps required fields (`latitude`, `longitude`, `cell_id`, `site_id`, `azimuth`, `band`, etc.) and technology, and runs a dry validation without generating map files.
  2. **Generation (`generate`)**: Non-interactively processes known file layouts using saved signatures and rules in `config.json` to produce `KMZ` or `KML` outputs.
- **Data Validation & Audit**:
  - Validates coordinates, filters null/out-of-bounds points, and resets invalid azimuths to `0°` with warnings.
  - Translates raw frequencies/channels (`BCCH`, `UARFCNDL`, `earfcndl`, `ssbFrequency`) into configured bands (`2G_900`, `2G_1800`, `3G_900`, `3G_2100`, `4G_800`, `4G_1800`, `4G_2100`, `4G_2600`, `5G_1800`, `5G_3500`, `MSAN`).
  - Logs execution details to `logs/ran_geomapper.log` and exports dropped/warned rows to `ran_audit_report.csv`.
- **Customizable KML/KMZ Styling & Labels**:
  - Organizes output folders by technology (`2G`, `3G`, `4G`, `5G`, `MSAN`), site placemarks (`01 - <Tech> Sites`), and band layers ordered by radius.
  - Supports configurable sector radius, beamwidth, apex offset, opacity, and KML (`aabbggrr`) colors per band.
  - Optional map labels placed either near the site (`near_site`) or at the sector tip (`cell_tip`), with optional grouping into per-band label folders.

## Project Structure

- `gui_app.py` — Tkinter desktop GUI (`RAN-GeoMapper Studio`) with Discovery, Generation, Configuration, and Label Display tabs.
- `main.py` — CLI entry point and `RANGeoMapper` orchestrator (`discover` and `generate` subcommands).
- `file_reader.py` — Robust `.csv` (multi-encoding/delimiter) and `.xls`/`.xlsx` reader with header auto-detection.
- `data_validator.py` — `RANDataAuditor` for coordinate/azimuth validation, frequency-to-band mapping, and CSV audit export.
- `kml_generator.py` — `KMLGenerator` for wedge polygon geometry, HTML popups, label placemarks, and KML/KMZ export.
- `config.json` — Runtime settings, band rules, channel ranges, and saved file layout signatures (auto-created with defaults if missing).
- `CellFileToKml.spec` — PyInstaller build specification for the standalone Windows executable.

## Setup & Run (PowerShell)

```powershell
cd ran_geomapper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pandas openpyxl xlrd
python .\gui_app.py

## CLI Usage

python .\main.py discover -f .\base\*

python .\main.py generate -f .\base\* -o ran_network.kmz
python .\main.py generate -f .\base\* --skip-unknown

## Build Standalone Executable
pyinstaller --noconfirm .\CellFileToKml.spec
pyinstaller --noconfirm --onefile --windowed --name CellFileToKml --collect-all openpyxl --collect-all pandas .\gui_app.py


