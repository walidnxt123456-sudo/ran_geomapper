import os
import glob
import logging
import pandas as pd
import csv

def _clean_headers(df):
    """Strips stray whitespace from column names (e.g. ' Site Name ', 'Azimut ')."""
    df.columns = [str(c).strip() for c in df.columns]
    return df

def read_data_file(file_path):
    """
    Reads CSV or Excel files with robust error handling for encodings and delimiters.
    Supports .csv, .xlsx, and .xls files.
    Everything is read as text (dtype=str) so IDs keep their exact form
    ("00123" stays "00123", "12345" never becomes "12345.0"). Numeric
    conversion happens later, only for latitude, longitude and azimuth.
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext in [".xls", ".xlsx"]:
        try:
            return _clean_headers(pd.read_excel(file_path, dtype=str))
        except Exception as e:
            logging.error(f"Erreur de lecture du fichier Excel '{file_path}': {e}")
            return None

    if ext == ".csv":
        encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252", "iso-8859-1"]
        separators = [",", ";", "\t", "|"]
        
        for enc in encodings:
            for sep in separators:
                try:
                    df = pd.read_csv(file_path, encoding=enc, sep=sep, dtype=str)
                    # Check if read was successful and didn't lump all columns together
                    if len(df.columns) > 1:
                        logging.info(f"Fichier CSV '{os.path.basename(file_path)}' lu avec succès (Encodage: {enc}, Séparateur: '{sep}')")
                        return _clean_headers(df)
                except Exception:
                    continue
        
        # Fallback attempt with python engine
        for enc in encodings:
            try:
                df = pd.read_csv(file_path, encoding=enc, engine="python", dtype=str)
                logging.info(f"Fichier CSV '{os.path.basename(file_path)}' lu via fallback python engine (Encodage: {enc})")
                return _clean_headers(df)
            except Exception:
                continue

        logging.error(f"Impossible de lire le fichier CSV '{file_path}' avec les encodages usuels.")
        return None

    logging.error(f"Format de fichier non supporté pour : {file_path}")
    return None

def auto_detect_columns(df_cols):
    """
    Auto-detects mapping between target RAN parameters and dataframe columns.
    Excludes non-technology attributes like frequencies from matching 'tech'.
    """
    mapping = {}
    cols = list(df_cols)

    candidates = {
        "tech": ["Technology", "Tech", "RAT", "System", "Network_Tech", "Generation"],
        "band": ["Band", "ssbFrequency", "earfcndl", "UARFCNDL", "BCCH", "Frequency"],
        "site_id": ["Site Name", "GNodeB Id", "ERBS Id", "RBS Name 2", "Site_Name", "SITE_ID"],
        "site_name": ["Site Name", "RBS Name 2", "Site_Name", "GNodeB Id", "ERBS Id"],
        "cell_id": ["EUtranCell Id", "NRCELLDU", "UtranCell", "CI", "CELL_ID"],
        "cell_name": ["EUtranCell Id", "NRCELLDU", "UtranCell", "CELL_Name", "Cell Name"],
        "latitude": ["Latitude", "LAT_DD", "LATITUDE", "Lat"],
        "longitude": ["Longitude", "Long_DD", "LONGITUDE", "Lon", "Long"],
        "azimuth": ["Azimut", "Azimuth", "AZIMUTH", "AZI"]
    }

    for key, possible_names in candidates.items():
        for candidate in possible_names:
            matched = [c for c in cols if c.strip().lower() == candidate.lower()]
            if matched:
                mapping[key] = matched[0]
                break

    required = ["latitude", "longitude", "cell_id"]
    if all(req in mapping for req in required):
        return mapping
    return None

def display_preview(df, file_name, mapping=None):
    """
    Displays a structured preview of dataset columns and current column mappings in CLI.
    """
    print("\n" + "=" * 80)
    print(f" APERÇU DU FICHIER : {file_name}")
    print("=" * 80)
    print(f" Lignes détectées   : {len(df)}")
    print(f" Colonnes trouvées  : {len(df.columns)}")
    print("-" * 80)

    for idx, col in enumerate(df.columns):
        sample = str(df[col].dropna().iloc[0]) if not df[col].dropna().empty else "N/A"
        sample_str = (sample[:32] + "...") if len(sample) > 35 else sample
        print(f" {idx + 1:<4} | {col:<30} | {sample_str:<35}")

    print("-" * 80)

    if mapping:
        print(" CARTOGRAPHIE ACTUELLE DES COLONNES :")
        for field, col_name in mapping.items():
            print(f"   • {field:<12} -> {col_name}")
        print("=" * 80 + "\n")

def user_customize_mapping(df, current_mapping=None):
    """
    Prompts the user interactively to confirm or adjust mapped dataframe columns.
    """
    cols = list(df.columns)
    mapping = current_mapping.copy() if current_mapping else {}

    fields_to_map = [
        ("tech", "Technologie (2G/3G/4G/5G)", "TECH"),
        ("band", "Bande / Fréquence", "BAND"),
        ("site_id", "ID du Site", "SITE"),
        ("site_name", "Nom du Site", "SITE"),
        ("cell_id", "ID de la Cellule", "CELL"),
        ("cell_name", "Nom de la Cellule", "CELL"),
        ("latitude", "Latitude", "LAT"),
        ("longitude", "Longitude", "LON"),
        ("azimuth", "Azimut", "AZI"),
    ]

    print("\n--- SELECTION MANUELLE DE LA CARTOGRAPHIE DES COLONNES ---")
    for key, label, search_hint in fields_to_map:
        current_val = mapping.get(key, "")
        default_idx = ""
        if current_val in cols:
            default_idx = str(cols.index(current_val) + 1)
        else:
            for idx, c in enumerate(cols):
                if search_hint.lower() in c.lower():
                    default_idx = str(idx + 1)
                    break

        prompt_msg = f"Sélectionnez l'index ou le nom pour '{label}'"
        if current_val:
            prompt_msg += f" [Actuel : {current_val}]"
        elif default_idx:
            prompt_msg += f" [Suggéré : {default_idx} - {cols[int(default_idx)-1]}]"
        prompt_msg += " : "

        ans = input(prompt_msg).strip()

        if not ans:
            if current_val:
                continue
            elif default_idx:
                mapping[key] = cols[int(default_idx) - 1]
        elif ans.isdigit() and 1 <= int(ans) <= len(cols):
            mapping[key] = cols[int(ans) - 1]
        elif ans in cols:
            mapping[key] = ans

    return mapping

def expand_file_patterns(file_inputs):
    """
    Expands file path patterns and wildcards into a sorted list of valid input files.
    """
    matched_files = []
    for pattern in file_inputs:
        expanded = glob.glob(pattern)
        if not expanded and os.path.exists(pattern):
            expanded = [pattern]
        for f in expanded:
            if os.path.basename(f).startswith("~$"):
                continue  # Excel temporary lock file
            if os.path.isfile(f) and f.lower().endswith((".csv", ".xls", ".xlsx")):
                matched_files.append(f)

    return sorted(list(set(matched_files)))