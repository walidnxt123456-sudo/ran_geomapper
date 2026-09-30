import os
import sys
import json
import copy
import shutil
import logging
import argparse
import hashlib
from datetime import datetime

from file_reader import (
    expand_file_patterns,
    read_data_file,
    auto_detect_columns,
    display_preview,
    user_customize_mapping
)
from data_validator import RANDataAuditor
from kml_generator import KMLGenerator

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
log_filename = os.path.join(LOG_DIR, "ran_geomapper.log")

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

file_handler = logging.FileHandler(log_filename, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])

CONFIG_FILE = "config.json"

# Keep in sync with config.json (used only when config.json is missing).
DEFAULT_CONFIG = {
    "settings": {
        "output_format": "kmz",
        "global_opacity_percent": 45,
        "default_offset_m": 8,
        "default_radius_m": 250,
        "default_beamwidth": 60
    },
    "band_rules": {
        "2G_900": {
            "radius_m": 500,
            "beamwidth": 65,
            "offset_m": 5,
            "color_kml": "7f0000ff"
        },
        "2G_1800": {
            "radius_m": 350,
            "beamwidth": 60,
            "offset_m": 7,
            "color_kml": "7f00a5ff"
        },
        "3G_900": {
            "radius_m": 450,
            "beamwidth": 65,
            "offset_m": 6,
            "color_kml": "7f00ff55"
        },
        "3G_2100": {
            "radius_m": 350,
            "beamwidth": 60,
            "offset_m": 8,
            "color_kml": "7f00ff00"
        },
        "4G_800": {
            "radius_m": 450,
            "beamwidth": 65,
            "offset_m": 7,
            "color_kml": "7f00ffff"
        },
        "4G_1800": {
            "radius_m": 300,
            "beamwidth": 60,
            "offset_m": 10,
            "color_kml": "7fffaa00"
        },
        "4G_2100": {
            "radius_m": 300,
            "beamwidth": 60,
            "offset_m": 10,
            "color_kml": "7fff8000"
        },
        "4G_2600": {
            "radius_m": 200,
            "beamwidth": 55,
            "offset_m": 12,
            "color_kml": "7f00d7ff"
        },
        "5G_1800": {
            "radius_m": 250,
            "beamwidth": 50,
            "offset_m": 10,
            "color_kml": "7ff000ff"
        },
        "5G_3500": {
            "radius_m": 120,
            "beamwidth": 45,
            "offset_m": 15,
            "color_kml": "7f800080"
        }
    },
    "band_mapping": {
        "2G": {
            "900": [[1, 124], [975, 1023]],
            "1800": [[512, 885]]
        },
        "3G": {
            "900": [[2937, 3088]],
            "2100": [[10562, 10838]]
        },
        "4G": {
            "800": [[6150, 6449]],
            "1800": [[1200, 1949]],
            "2100": [[0, 599]],
            "2600": [[2750, 3449]]
        },
        "5G": {
            "1800": [[361000, 376000]],
            "3500": [[620000, 653333]]
        }
    },
    "column_mappings": {},
    "sources": {}
}

class RANGeoMapper:
    """
    Main Orchestrator for loading configurations, running ingestion, and validating rows.
    """
    def __init__(self, config_path=CONFIG_FILE):
        self.config_path = config_path
        self.config = self.load_or_create_config()
        # Pass the band_mapping config to the auditor
        self.auditor = RANDataAuditor(self.config.get("band_mapping", {}))

    def load_or_create_config(self):
        """
        Loads the config, creating it from DEFAULT_CONFIG if missing.
        A corrupt config is backed up (never silently overwritten) and defaults are used.
        Missing top-level keys are filled in from DEFAULT_CONFIG.
        """
        if not os.path.exists(self.config_path):
            config = copy.deepcopy(DEFAULT_CONFIG)
            self._write_config(config)
            logging.info(f"Fichier de configuration créé : '{self.config_path}'")
            return config

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            if not isinstance(config, dict):
                raise ValueError("la racine du JSON doit être un objet")
        except Exception as e:
            backup = f"{self.config_path}.corrupt-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                shutil.copy2(self.config_path, backup)
            except OSError as copy_err:
                logging.error(f"Configuration illisible ({e}) et sauvegarde impossible ({copy_err}). Arrêt pour ne rien écraser.")
                sys.exit(1)
            logging.error(f"Erreur de lecture de la configuration : {e}. Copie conservée dans '{backup}', valeurs par défaut utilisées.")
            return copy.deepcopy(DEFAULT_CONFIG)

        for key, default in DEFAULT_CONFIG.items():
            if not isinstance(config.get(key), dict):
                if key in config:
                    logging.warning(f"Clé de configuration '{key}' invalide, valeurs par défaut utilisées.")
                config[key] = copy.deepcopy(default)
        return config

    def _write_config(self, config):
        """Atomic write: a crash mid-write cannot truncate the existing config."""
        tmp_path = f"{self.config_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.config_path)

    def save_config(self):
        self._write_config(self.config)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def file_signature(df):
        """
        Stable id of a file layout: hash of its (stripped, lower-cased) column names.
        Survives monthly renames ("Septembre" -> "Octobre") as long as the layout is unchanged.
        """
        cols = "|".join(sorted(str(c).strip().lower() for c in df.columns))
        return hashlib.sha1(cols.encode("utf-8")).hexdigest()[:10]

    def new_run(self):
        """Fresh audit counters and a re-read config.json (so edits made between runs apply)."""
        self.config = self.load_or_create_config()
        self.auditor = RANDataAuditor(self.config.get("band_mapping", {}))

    def suggest_mapping(self, df, file_name):
        """Returns (mapping, known_source): saved layout if known, else legacy/auto-detected."""
        known = self.config["sources"].get(self.file_signature(df))
        if known:
            mapping = known.get("mapping")
        else:
            mapping = self.config["column_mappings"].get(file_name) or auto_detect_columns(df.columns)
        return self._strip_mapping(mapping), known

    def save_source(self, df, file_name, mapping, tech):
        """Stores mapping + technology for this file layout. Returns its signature."""
        sig = self.file_signature(df)
        self.config["sources"][sig] = {"example_file": file_name, "tech": tech, "mapping": self._strip_mapping(mapping)}
        self.save_config()
        logging.info(f"Mise en page enregistrée : signature {sig} | {tech} | {file_name}")
        return sig

    def _load(self, file_path):
        if not os.path.exists(file_path):
            logging.error(f"Fichier non trouvé : {file_path}")
            return None
        df = read_data_file(file_path)
        if df is None or df.empty:
            logging.error(f"Fichier vide ou illisible : {file_path}")
            return None
        return df

    @staticmethod
    def _strip_mapping(mapping):
        return {k: str(v).strip() for k, v in mapping.items()} if mapping else mapping

    def validate_df(self, df, file_name, mapping, tech):
        valid_rows = []
        for idx, row in df.iterrows():
            record = self.auditor.validate_row(row, idx + 2, file_name, mapping, tech)
            if record:
                valid_rows.append(record)
        return valid_rows

    # ------------------------------------------------------- MODE 1: DISCOVERY
    def discover_file(self, file_path):
        """
        Interactive. Reads a file, proposes/confirms the column mapping and the
        technology, saves both in config["sources"], and runs a dry validation
        (no KMZ). Returns the number of valid cells, or None if the file is unusable.
        """
        df = self._load(file_path)
        if df is None:
            return None
        file_name = os.path.basename(file_path)
        sig = self.file_signature(df)

        mapping, known = self.suggest_mapping(df, file_name)
        if known:
            logging.info(f"Mise en page déjà connue (signature {sig}, ex: '{known.get('example_file')}').")

        display_preview(df, file_name, mapping)
        if mapping:
            choice = input("Voulez-vous valider cette cartographie ? [O/n] : ").strip().lower()
            if choice in ["n", "no", "non"]:
                mapping = user_customize_mapping(df, mapping)
        else:
            mapping = user_customize_mapping(df)
        mapping = self._strip_mapping(mapping)

        missing = [f"{k} -> '{v}'" for k, v in mapping.items() if v and v not in df.columns]
        if missing:
            logging.error(f"Colonnes introuvables dans '{file_name}' : {', '.join(missing)}")
            return None

        tech = self.auditor.resolve_file_tech(df, file_name, mapping)
        if tech not in ("2G", "3G", "4G", "5G"):
            logging.error(f"Technologie non déterminée pour '{file_name}' : fichier ignoré.")
            return None

        self.save_source(df, file_name, mapping, tech)

        return len(self.validate_df(df, file_name, mapping, tech))

    # ---------------------------------------------------- MODE 2: GENERATION
    def generate_file(self, file_path):
        """
        Non-interactive. Uses only what discovery saved. Returns (cells, error):
        error is a short reason string when the file cannot be processed.
        """
        df = self._load(file_path)
        if df is None:
            return None, "illisible ou vide"
        file_name = os.path.basename(file_path)
        sig = self.file_signature(df)

        source = self.config["sources"].get(sig)
        if not source:
            return None, f"mise en page inconnue (signature {sig}) : lancez le mode discover"

        mapping = self._strip_mapping(source["mapping"])
        missing = [v for v in mapping.values() if v and v not in df.columns]
        if missing:
            return None, f"colonnes introuvables {missing} : relancez discover"

        logging.info(f"'{file_name}' : signature {sig}, technologie {source['tech']}")
        return self.validate_df(df, file_name, mapping, source["tech"]), None


def parse_arguments():
    parser = argparse.ArgumentParser(description="RAN-GeoMapper - Cartographie RAN & génération KMZ / KML")
    sub = parser.add_subparsers(dest="mode", required=True)

    d = sub.add_parser("discover", help="Mode découverte : lit les fichiers, configure colonnes/techno, valide à blanc (aucun KMZ)")
    d.add_argument("-f", "--files", nargs="+", required=True, help="Fichier(s) cellref ou pattern (ex: -f .\\base\\*)")

    g = sub.add_parser("generate", help="Mode génération : non interactif, utilise la config enregistrée, produit le KMZ/KML")
    g.add_argument("-f", "--files", nargs="+", required=True, help="Fichier(s) cellref ou pattern")
    g.add_argument("-o", "--output", default=None, help="Sortie .kmz ou .kml (défaut: ran_network_<date>.<settings.output_format>)")
    g.add_argument("--skip-unknown", action="store_true", help="Ignorer les fichiers non configurés au lieu d'arrêter")
    return parser.parse_args()


def run_discover(mapper, target_files):
    ok = 0
    for file_path in target_files:
        count = mapper.discover_file(file_path)
        if count is not None:
            ok += 1
    mapper.auditor.print_summary()
    mapper.auditor.print_band_summary(mapper.config.get("band_rules", {}))
    mapper.auditor.export_csv_report("ran_audit_report.csv")
    print(f" Découverte terminée : {ok}/{len(target_files)} fichier(s) configuré(s). Aucun KMZ généré.")
    print(" Corrigez band_mapping / band_rules dans config.json si le récapitulatif signale des canaux non reconnus,")
    print(" puis lancez le mode 'generate'.\n")
    return 0 if ok == len(target_files) else 1


def run_generate(mapper, target_files, output, skip_unknown):
    all_cells, failures = [], []
    for file_path in target_files:
        cells, error = mapper.generate_file(file_path)
        if error:
            failures.append((os.path.basename(file_path), error))
        elif cells:
            all_cells.extend(cells)

    if failures:
        for name, error in failures:
            logging.error(f"{name} : {error}")
        if not skip_unknown:
            logging.error("Arrêt : fichiers non traités (utilisez --skip-unknown pour continuer sans eux).")
            return 2

    mapper.auditor.print_summary()
    mapper.auditor.print_band_summary(mapper.config.get("band_rules", {}))
    mapper.auditor.export_csv_report("ran_audit_report.csv")

    if not all_cells:
        logging.warning("Aucune donnée valide à exporter.")
        return 1

    if not output:
        fmt = str(mapper.config["settings"].get("output_format", "kmz")).lower().lstrip(".")
        if fmt not in ("kmz", "kml"):
            logging.warning(f"output_format '{fmt}' inconnu, 'kmz' utilisé.")
            fmt = "kmz"
        output = f"ran_network_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}"
    KMLGenerator(mapper.config).export(all_cells, output)
    return 0


if __name__ == "__main__":
    args = parse_arguments()
    target_files = expand_file_patterns(args.files)
    if not target_files:
        logging.error("Aucun fichier CSV ou Excel valide n'a été trouvé.")
        sys.exit(1)

    mapper = RANGeoMapper()
    if args.mode == "discover":
        sys.exit(run_discover(mapper, target_files))
    sys.exit(run_generate(mapper, target_files, args.output, args.skip_unknown))