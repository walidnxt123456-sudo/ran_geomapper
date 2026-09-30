import logging
from collections import Counter
import pandas as pd

VALID_TECHS = ["2G", "3G", "4G", "5G"]

def _to_float(value):
    """Parses a number from text; accepts comma decimals ('36,84'). Raises ValueError if invalid."""
    if value is None:
        raise ValueError("valeur manquante")
    text = str(value).strip().replace(",", ".")
    if not text or text.lower() == "nan":
        raise ValueError("valeur vide")
    return float(text)

class RANDataAuditor:
    """
    Tracks, logs, and exports data validation anomalies for mobile RAN datasets.
    Now includes dynamic frequency-to-band translation based on config.
    """
    def __init__(self, band_mapping=None):
        self.audit_records = []
        self.total_processed = 0
        self.total_valid = 0
        self.total_dropped = 0
        self.total_warnings = 0
        # (tech, band) -> number of valid cells, and unmatched raw channels
        self.band_counts = Counter()
        self.unmatched_channels = Counter()
        # Store the translation rules from config.json
        self.band_mapping = band_mapping or {}

    def log_issue(self, row_idx, file_name, site_id, cell_id, status, reason, details=""):
        record = {
            "Row_Index": row_idx,
            "File": file_name,
            "Site_ID": str(site_id),
            "Cell_ID": str(cell_id),
            "Status": status,
            "Issue_Reason": reason,
            "Details": details
        }
        self.audit_records.append(record)
        if status == "DROPPED":
            self.total_dropped += 1
            logging.warning(f"Ligne {row_idx:4d} | Fichier: {file_name} | Site: {site_id} | Cellule: {cell_id} -> REJETÉE: {reason}")
        else:
            self.total_warnings += 1
            logging.info(f"Ligne {row_idx:4d} | Fichier: {file_name} | Site: {site_id} | Cellule: {cell_id} -> AVERTISSEMENT: {reason}")

    @staticmethod
    def _tech_from_text(text):
        """Returns '2G'..'5G' if the text contains one, else None."""
        text = str(text).strip().upper()
        if text in VALID_TECHS:
            return text
        for t in ["5G", "4G", "3G", "2G"]:
            if t in text:
                return t
        return None

    def _translate_band(self, tech, raw_band):
        """
        Translates raw frequency/channel numbers to standardized band names using config ranges.
        Example: EARFCN 1300 -> '1800'. If already a string like 'B3', returns 'B3'.
        Returns (band, matched): matched is False when the value is missing or
        numeric but falls in no configured range.
        """
        if raw_band is None or (isinstance(raw_band, float) and pd.isna(raw_band)):
            return "UNKNOWN", False
        
        raw_str = str(raw_band).strip()
        if not raw_str or raw_str.lower() == "nan":
            return "UNKNOWN", False

        # Try to parse as a number to check against configured ranges
        try:
            val = float(raw_str)
        except ValueError:
            # If it's not a number (e.g., "B3", "n78"), return it as-is (cleaned)
            return raw_str.upper(), True

        # Check against configured ranges for this specific technology
        tech_mapping = self.band_mapping.get(tech, {})
        for target_band, ranges in tech_mapping.items():
            for r in ranges:
                if isinstance(r, list) and len(r) == 2:
                    if r[0] <= val <= r[1]:
                        return target_band, True
        
        # Fallback: if no range matched, return the numeric value as a string
        # (e.g., EARFCN 9999 will just become "9999", which will fall back to default rules)
        return (str(int(val)) if val.is_integer() else str(val)), False

    def detect_file_tech(self, df, file_name, mapping):
        """
        Detects the technology of a file from its tech column, then its file name.
        Never prompts. Returns '2G'..'5G' or None.
        """
        tech_col = mapping.get("tech", "") if mapping else ""
        if tech_col and tech_col in df.columns:
            counts = Counter(
                t for t in (self._tech_from_text(v) for v in df[tech_col].dropna()) if t
            )
            if counts:
                tech = counts.most_common(1)[0][0]
                logging.info(f"Technologie de '{file_name}' déduite de la colonne '{tech_col}' : {tech}")
                return tech
        
        fname_upper = file_name.upper()
        for tech, hints in [
            ("5G", ("5G", "NR")),
            ("4G", ("4G", "LTE")),
            ("3G", ("3G", "UMTS", "UTRAN")),
            ("2G", ("2G", "GSM")),
        ]:
            if any(h in fname_upper for h in hints):
                logging.info(f"Technologie de '{file_name}' déduite du nom de fichier : {tech}")
                return tech
                
        return None

    def resolve_file_tech(self, df, file_name, mapping):
        """CLI: detects the technology, otherwise asks on the console."""
        tech = self.detect_file_tech(df, file_name, mapping)
        if tech:
            return tech
        print(f"\n[!] Impossible de déterminer la technologie de '{file_name}' (colonne ou nom de fichier).")
        while True:
            try:
                user_tech = input(f"Veuillez spécifier la technologie pour '{file_name}' (2G, 3G, 4G, 5G) : ").strip().upper()
            except EOFError:
                logging.warning(f"Aucune saisie possible pour '{file_name}' : technologie = DEFAULT")
                return "DEFAULT"
            if user_tech in VALID_TECHS:
                return user_tech
            print("Saisie invalide. Choisissez parmi : 2G, 3G, 4G, 5G.")

    def validate_row(self, row, row_idx, file_name, mapping, default_tech=None):
        """
        Validates individual data rows: coordinates, azimuth, site/cell IDs, RAT, and Band translation.
        """
        self.total_processed += 1
        site_id = row.get(mapping.get("site_id", ""), "SITE_INCONNU")
        cell_id = row.get(mapping.get("cell_id", ""), "CELL_INCONNUE")
        raw_lat = row.get(mapping.get("latitude", ""))
        raw_lon = row.get(mapping.get("longitude", ""))

        # 1. Geocoordinates validation
        try:
            lat = _to_float(raw_lat)
            lon = _to_float(raw_lon)
            if pd.isna(lat) or pd.isna(lon):
                raise ValueError("Coordonnées NaN")
            if lat == 0.0 and lon == 0.0:
                self.log_issue(row_idx, file_name, site_id, cell_id, "DROPPED", "Coordonnées Nulles (0.0, 0.0)")
                return None
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                self.log_issue(row_idx, file_name, site_id, cell_id, "DROPPED", f"Coordonnées Hors Limites ({lat}, {lon})")
                return None
        except Exception:
            self.log_issue(row_idx, file_name, site_id, cell_id, "DROPPED", f"Coordonnées Invalides/Manquantes ({raw_lat}, {raw_lon})")
            return None

        # 2. Azimuth validation
        raw_az = row.get(mapping.get("azimuth", ""))
        try:
            azimuth = _to_float(raw_az)
            if pd.isna(azimuth) or not (0 <= azimuth <= 360):
                self.log_issue(row_idx, file_name, site_id, cell_id, "WARNING", f"Azimut Invalide ({raw_az}). Réinitialisé à 0°")
                azimuth = 0.0
        except Exception:
            self.log_issue(row_idx, file_name, site_id, cell_id, "WARNING", f"Azimut non numérique ({raw_az}). Réinitialisé à 0°")
            azimuth = 0.0

        # 3. Technology determination
        tech = None
        tech_col = mapping.get("tech", "")
        if tech_col and tech_col in row:
            tech = self._tech_from_text(row.get(tech_col, ""))
        tech = tech or default_tech or "DEFAULT"

        # 4. Band Translation (The new generic logic!)
        raw_band = row.get(mapping.get("band", ""), "")
        band, matched = self._translate_band(tech, raw_band)
        self.band_counts[(tech, band)] += 1
        if not matched:
            self.unmatched_channels[(tech, str(raw_band).strip() or "(vide)")] += 1

        self.total_valid += 1
        attributes = {str(k): ("" if pd.isna(v) else str(v)) for k, v in row.items()}
        
        return {
            "site_id": str(site_id),
            "site_name": str(row.get(mapping.get("site_name", ""), site_id)),
            "cell_id": str(cell_id),
            "cell_name": str(row.get(mapping.get("cell_name", ""), cell_id)),
            "tech": tech,
            "band": band,  # <-- Now uses the translated band!
            "latitude": lat,
            "longitude": lon,
            "azimuth": azimuth,
            "attributes": attributes
        }

    def print_summary(self):
        """Prints audit statistics summary in the console."""
        print("\n" + "=" * 80)
        print(" RÉSUMÉ DU RAPPORT D'AUDIT DE VALIDATION DES DONNÉES")
        print("=" * 80)
        print(f" Total Lignes Traitées   : {self.total_processed}")
        print(f" Cellules Valides        : {self.total_valid}")
        print(f" Cellules Rejetées       : {self.total_dropped}")
        print(f" Avertissements (Azimut) : {self.total_warnings}")
        print("=" * 80 + "\n")

    def band_summary_text(self, band_rules=None, top_unmatched=10):
        """
        Text table: cells per (tech, band), whether each band has a rule (else generic
        default styling), and the channels that fell in no band_mapping range.
        This is the sanity check for band_mapping in config.json.
        """
        band_rules = band_rules or {}
        lines = ["=" * 80, " RÉCAPITULATIF PAR TECHNOLOGIE / BANDE", "=" * 80,
                 f" {'Techno':<8}{'Bande':<12}{'Cellules':>10}   Règle band_rules", "-" * 80]
        for (tech, band), n in sorted(self.band_counts.items()):
            flag = "OK" if f"{tech}_{band}" in band_rules else "PAR DÉFAUT (aucune règle)"
            lines.append(f" {tech:<8}{band:<12}{n:>10}   {flag}")
        lines.append("-" * 80)

        if self.unmatched_channels:
            lines.append(" CANAUX NON RECONNUS (hors de toutes les plages band_mapping) :")
            per_tech = {}
            for (tech, raw), n in self.unmatched_channels.items():
                per_tech.setdefault(tech, []).append((raw, n))
            for tech in sorted(per_tech):
                items = sorted(per_tech[tech], key=lambda x: -x[1])
                shown = ", ".join(f"{raw} (x{n})" for raw, n in items[:top_unmatched])
                extra = f" … +{len(items) - top_unmatched} autres" if len(items) > top_unmatched else ""
                lines.append(f"   {tech}: {shown}{extra}")
        else:
            lines.append(" Tous les canaux ont été associés à une bande.")
        lines.append("=" * 80)
        return "\n".join(lines)

    def print_band_summary(self, band_rules=None, top_unmatched=10):
        print("\n" + self.band_summary_text(band_rules, top_unmatched) + "\n")
        if self.unmatched_channels:
            logging.warning(
                f"{sum(self.unmatched_channels.values())} cellules avec canal hors plages : vérifiez band_mapping dans config.json"
            )

    def export_csv_report(self, output_path="ran_audit_report.csv"):
        """Exports detailed records of dropped/warned lines to CSV."""
        if self.audit_records:
            df_audit = pd.DataFrame(self.audit_records)
            df_audit.to_csv(output_path, index=False, encoding="utf-8-sig")
            logging.info(f"Rapport d'audit d'anomalies enregistré sous : '{output_path}'")