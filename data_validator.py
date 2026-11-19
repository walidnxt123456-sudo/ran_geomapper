import math
import logging
from collections import Counter
import pandas as pd

VALID_TECHS = ["2G", "3G", "4G", "5G"]
NON_RADIO_TECHS = ["MSAN"]
ALL_TECHS = VALID_TECHS + NON_RADIO_TECHS

def _to_float(value):
    """Parses a number from text; accepts comma decimals ('36,84'). Raises ValueError if invalid."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise ValueError("valeur manquante")
    text = str(value).strip().replace(",", ".")
    if not text or text.lower() in {"nan", "none", "null"}:
        raise ValueError("valeur vide")
    num = float(text)
    if not math.isfinite(num):
        raise ValueError("valeur non finie")
    return num


def _clean_text(value, fallback=""):
    """Converts a cell value to clean text, treating None, NaN, and 'nan'/'none' as empty."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text


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
            "Site_ID": _clean_text(site_id, "SITE_INCONNU"),
            "Cell_ID": _clean_text(cell_id, "CELL_INCONNUE"),
            "Status": status,
            "Issue_Reason": reason,
            "Details": details
        }
        self.audit_records.append(record)
        if status == "DROPPED":
            self.total_dropped += 1
            logging.warning(f"Ligne {row_idx:4d} | Fichier: {file_name} | Site: {record['Site_ID']} | Cellule: {record['Cell_ID']} -> REJETÉE: {reason}")
        else:
            self.total_warnings += 1
            logging.info(f"Ligne {row_idx:4d} | Fichier: {file_name} | Site: {record['Site_ID']} | Cellule: {record['Cell_ID']} -> AVERTISSEMENT: {reason}")

    @staticmethod
    def _tech_from_text(text):
        """Returns '2G'..'5G' if the text contains one, else None."""
        cleaned = _clean_text(text).upper()
        if not cleaned:
            return None
        if cleaned in ALL_TECHS:
            return cleaned
        for t in ["5G", "4G", "3G", "2G", "MSAN"]:
            if t in cleaned:
                return t
        return None

    def _translate_band(self, tech, raw_band):
        """
        Translates raw frequency/channel numbers to standardized band names using config ranges.
        Example: EARFCN 1300 -> '1800'. If already a non-numeric label like 'B3', returns 'B3'.
        Returns (band, matched): matched is True when a configured range matches (or a non-empty
        non-numeric band label is provided), and False when missing or outside configured ranges.
        """
        raw_str = _clean_text(raw_band)
        if not raw_str:
            return "UNKNOWN", False

        # Try to parse as a finite number to check against configured ranges
        try:
            val = _to_float(raw_str)
        except ValueError:
            # Non-numeric band label (e.g., "B3", "n78")
            return raw_str.upper(), True

        # Check against configured ranges for this specific technology
        tech_mapping = self.band_mapping.get(tech, {})
        for target_band, ranges in tech_mapping.items():
            for r in ranges:
                if isinstance(r, (list, tuple)) and len(r) == 2:
                    try:
                        low = _to_float(r[0])
                        high = _to_float(r[1])
                    except ValueError:
                        continue
                    if low <= val <= high:
                        return str(target_band), True

        # Fallback: numeric channel fell outside all configured ranges
        fallback_band = str(int(val)) if val.is_integer() else str(val)
        return fallback_band, False

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
            ("MSAN", ("MSAN",)),
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
        site_id = _clean_text(row.get(mapping.get("site_id", "")), "SITE_INCONNU")
        cell_id = _clean_text(row.get(mapping.get("cell_id", "")), "CELL_INCONNUE")
        site_name = _clean_text(row.get(mapping.get("site_name", "")), site_id)
        cell_name = _clean_text(row.get(mapping.get("cell_name", "")), cell_id)
        raw_lat = row.get(mapping.get("latitude", ""))
        raw_lon = row.get(mapping.get("longitude", ""))

        # 3. Technology determination
        tech = None
        tech_col = mapping.get("tech", "")
        if tech_col and tech_col in row:
            tech = self._tech_from_text(row.get(tech_col, ""))
        tech = tech or default_tech or "DEFAULT"
        is_non_radio = tech in NON_RADIO_TECHS

        # 1. Geocoordinates validation
        try:
            lat = _to_float(raw_lat)
            lon = _to_float(raw_lon)
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
            if not (0 <= azimuth <= 360):
                if not is_non_radio:
                    self.log_issue(row_idx, file_name, site_id, cell_id, "WARNING", f"Azimut Invalide ({raw_az}). Réinitialisé à 0°")
                azimuth = 0.0
        except Exception:
            if not is_non_radio and _clean_text(raw_az):
                self.log_issue(row_idx, file_name, site_id, cell_id, "WARNING", f"Azimut non numérique ({raw_az}). Réinitialisé à 0°")
            azimuth = 0.0

        # 4. Band Translation
        band_col = mapping.get("band", "")
        raw_band = row.get(band_col, "") if band_col else ""
        if is_non_radio and not _clean_text(raw_band):
            band, matched = tech, True
        else:
            band, matched = self._translate_band(tech, raw_band)
        
        self.band_counts[(tech, band)] += 1

        if not matched:
            raw_label = _clean_text(raw_band) or "(vide)"
            self.unmatched_channels[(tech, raw_label)] += 1

        self.total_valid += 1
        attributes = {str(k): _clean_text(v, "") for k, v in row.items()}

        return {
            "site_id": site_id,
            "site_name": site_name,
            "cell_id": cell_id,
            "cell_name": cell_name,
            "tech": tech,
            "band": band,
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
            rule_key = f"{tech}_{band}"
            if rule_key in band_rules:
                flag = "OK"
            elif tech in band_rules:
                flag = f"TECH ({tech})"
            else:
                flag = "PAR DÉFAUT (aucune règle)"
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