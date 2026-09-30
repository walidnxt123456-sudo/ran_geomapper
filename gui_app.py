import os
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from main import RANGeoMapper
from kml_generator import KMLGenerator
from file_reader import read_data_file

TECHS = ["2G", "3G", "4G", "5G"]
IGNORE_LABEL = "(Ignorer / Non spécifié)"


class ColumnMappingDialog(tk.Toplevel):
    """
    Discovery dialog: shows the file and lets the user confirm the technology
    and map dataset columns to target fields.
    """
    def __init__(self, parent, file_name, df, current_mapping, detected_tech=""):
        super().__init__(parent)
        self.title(f"Découverte - {file_name}")
        self.geometry("700x600")
        self.transient(parent)
        self.grab_set()

        self.df = df
        self.cols = list(df.columns)
        self.file_name = file_name
        self.result_mapping = None
        self.result_tech = None

        self.fields_to_map = [
            ("tech", "Colonne technologie (optionnel)"),
            ("band", "Bande / Fréquence"),
            ("site_id", "ID du Site"),
            ("site_name", "Nom du Site"),
            ("cell_id", "ID de la Cellule"),
            ("cell_name", "Nom de la Cellule"),
            ("latitude", "Latitude"),
            ("longitude", "Longitude"),
            ("azimuth", "Azimut"),
        ]
        self.combos = {}
        self.tech_var = tk.StringVar(value=detected_tech if detected_tech in TECHS else "")
        self._build_ui(current_mapping or {})

    def _build_ui(self, current_mapping):
        tk.Label(
            self,
            text=f"Fichier : {self.file_name} ({len(self.df)} lignes, {len(self.cols)} colonnes)",
            font=("Segoe UI", 10, "bold"),
        ).pack(pady=10)

        frame = tk.Frame(self, padx=15, pady=5)
        frame.pack(fill="x", expand=True)

        # Technology of the whole file (required)
        tk.Label(frame, text="Technologie du fichier * :", anchor="w", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=5, pady=5)
        ttk.Combobox(frame, textvariable=self.tech_var, values=TECHS, state="readonly", width=12).grid(
            row=0, column=1, sticky="w", padx=5, pady=5)

        options = [IGNORE_LABEL] + self.cols
        for i, (key, label) in enumerate(self.fields_to_map, start=1):
            tk.Label(frame, text=f"{label} :", anchor="w").grid(row=i, column=0, sticky="w", padx=5, pady=3)
            var = tk.StringVar()
            mapped = current_mapping.get(key, "")
            var.set(mapped if mapped in self.cols else IGNORE_LABEL)
            ttk.Combobox(frame, textvariable=var, values=options, state="readonly", width=38).grid(
                row=i, column=1, sticky="w", padx=5, pady=3)
            self.combos[key] = var

        btns = tk.Frame(self, pady=15)
        btns.pack(fill="x")
        tk.Button(btns, text="Enregistrer la configuration", bg="#28a745", fg="white",
                  font=("Segoe UI", 9, "bold"), padx=15, pady=5, command=self.on_validate).pack(side="right", padx=20)
        tk.Button(btns, text="Annuler", padx=10, pady=5, command=self.destroy).pack(side="right")

    def on_validate(self):
        mapping = {}
        for key, var in self.combos.items():
            val = var.get()
            if val and val != IGNORE_LABEL:
                mapping[key] = val

        if not all(k in mapping for k in ("latitude", "longitude", "cell_id")):
            messagebox.showwarning(
                "Champs manquants",
                "Les champs 'Latitude', 'Longitude' et 'ID de la Cellule' sont obligatoires !",
                parent=self)
            return
        if self.tech_var.get() not in TECHS:
            messagebox.showwarning("Technologie manquante", "Choisissez la technologie du fichier.", parent=self)
            return

        self.result_mapping = mapping
        self.result_tech = self.tech_var.get()
        self.destroy()


class RANGeoMapperGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RAN-GeoMapper Studio")
        self.geometry("780x720")
        self.resizable(False, False)

        self.selected_files = []
        self.mapper = RANGeoMapper()
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        tk.Label(self, text="RAN-GeoMapper Studio", font=("Segoe UI", 16, "bold")).pack(pady=(10, 0))
        tk.Label(self, text="Découverte des fichiers RAN, puis génération KMZ/KML", font=("Segoe UI", 9)).pack(pady=(0, 8))

        frame_files = tk.LabelFrame(self, text=" Fichiers source ", padx=10, pady=8)
        frame_files.pack(fill="x", padx=20, pady=5)
        tk.Button(frame_files, text="Sélectionner fichiers (.xlsx, .xls, .csv)", command=self.select_files).pack(anchor="w", pady=3)
        self.lbl_files = tk.Label(frame_files, text="Aucun fichier sélectionné", fg="gray", justify="left")
        self.lbl_files.pack(anchor="w")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="x", padx=20, pady=8)

        # Tab 1: discovery
        tab_disc = tk.Frame(self, padx=10, pady=10)
        self.notebook.add(tab_disc, text="  1 · Découverte  ")
        tk.Label(tab_disc, justify="left", text=(
            "Lit les fichiers, configure colonnes et technologie, puis valide à blanc.\n"
            "Aucun fichier KMZ n'est produit. À refaire seulement si la structure d'un fichier change.")
        ).pack(anchor="w")
        self.var_confirm_known = tk.BooleanVar(value=False)
        tk.Checkbutton(tab_disc, text="Reconfirmer aussi les fichiers déjà configurés",
                       variable=self.var_confirm_known).pack(anchor="w", pady=4)
        self.btn_discover = tk.Button(tab_disc, text="🔍 Analyser et configurer", bg="#6f42c1", fg="white",
                                      font=("Segoe UI", 10, "bold"), padx=10, pady=4, command=self.run_discovery)
        self.btn_discover.pack(anchor="w", pady=4)

        # Tab 2: generation
        tab_gen = tk.Frame(self, padx=10, pady=10)
        self.notebook.add(tab_gen, text="  2 · Génération  ")
        tk.Label(tab_gen, justify="left", text=(
            "Utilise la configuration enregistrée, sans aucune question.\n"
            "Un fichier de structure inconnue est signalé : repassez alors par la Découverte.")
        ).pack(anchor="w")
        row = tk.Frame(tab_gen)
        row.pack(anchor="w", pady=6)
        tk.Label(row, text="Format de sortie :").pack(side="left")
        self.fmt_var = tk.StringVar(value=str(self.mapper.config.get("settings", {}).get("output_format", "kmz")).lower())
        ttk.Combobox(row, textvariable=self.fmt_var, values=["kmz", "kml"], state="readonly", width=8).pack(side="left", padx=6)
        self.btn_generate = tk.Button(tab_gen, text="🚀 Générer la cartographie", bg="#0066cc", fg="white",
                                      font=("Segoe UI", 10, "bold"), padx=10, pady=4, command=self.run_generation)
        self.btn_generate.pack(anchor="w", pady=4)

        self.txt_log = tk.Text(self, height=16, width=98, font=("Consolas", 8), state="disabled")
        self.txt_log.pack(padx=20, pady=5)

    def log(self, message):
        self.txt_log.config(state="normal")
        self.txt_log.insert(tk.END, message + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")
        self.update_idletasks()

    def _busy(self, busy):
        state = "disabled" if busy else "normal"
        self.btn_discover.config(state=state)
        self.btn_generate.config(state=state)

    def select_files(self):
        files = filedialog.askopenfilenames(
            title="Sélectionner les bases RAN",
            filetypes=[("Fichiers Excel / CSV", "*.xlsx *.xls *.csv"), ("Tous les fichiers", "*.*")])
        if files:
            self.selected_files = [f for f in files if not os.path.basename(f).startswith("~$")]
            names = "\n".join(os.path.basename(f) for f in self.selected_files)
            self.lbl_files.config(text=f"{len(self.selected_files)} fichier(s) sélectionné(s):\n{names}", fg="black")

    def _require_files(self):
        if not self.selected_files:
            messagebox.showwarning("Attention", "Veuillez d'abord sélectionner au moins un fichier !")
            return False
        return True

    def _log_audit_summary(self):
        a = self.mapper.auditor
        self.log(f"Cellules valides : {a.total_valid} | rejetées : {a.total_dropped} | avertissements azimut : {a.total_warnings}")
        for line in a.band_summary_text(self.mapper.config.get("band_rules", {})).splitlines():
            self.log(line)
        a.export_csv_report("ran_audit_report.csv")

    # ------------------------------------------------------- mode 1: discovery
    def run_discovery(self):
        if not self._require_files():
            return
        self._busy(True)
        try:
            self.mapper.new_run()
            self.log("--- DÉCOUVERTE ---")
            configured = 0
            for file_path in self.selected_files:
                name = os.path.basename(file_path)
                self.log(f"Lecture : {name}")
                df = read_data_file(file_path)
                if df is None or df.empty:
                    self.log("Fichier vide ou illisible.")
                    continue

                mapping, known = self.mapper.suggest_mapping(df, name)
                tech = known["tech"] if known else (self.mapper.auditor.detect_file_tech(df, name, mapping or {}) or "")
                usable = bool(known and mapping and all(v in df.columns for v in mapping.values() if v))

                if usable and not self.var_confirm_known.get():
                    self.log(f"  ↺ Structure déjà configurée ({tech}).")
                else:
                    dialog = ColumnMappingDialog(self, name, df, mapping, tech)
                    self.wait_window(dialog)
                    if not dialog.result_mapping:
                        self.log("Configuration annulée : fichier ignoré.")
                        continue
                    mapping, tech = dialog.result_mapping, dialog.result_tech
                    self.mapper.save_source(df, name, mapping, tech)
                    self.log(f"Configuration enregistrée ({tech}).")

                valid = self.mapper.validate_df(df, name, mapping, tech)
                self.log(f"{len(valid)}/{len(df)} cellules valides (validation à blanc).")
                configured += 1

            self._log_audit_summary()
            self.log(f"Découverte terminée : {configured}/{len(self.selected_files)} fichier(s) configuré(s). Aucun KMZ généré.")

            if self.mapper.auditor.unmatched_channels:
                messagebox.showwarning(
                    "Canaux non reconnus",
                    "Certains canaux n'appartiennent à aucune bande de band_mapping.\n"
                    "Consultez le récapitulatif, corrigez config.json, puis relancez la découverte.")
            elif configured == len(self.selected_files):
                self.notebook.select(1)
        except Exception as e:
            self.log(f"Erreur critique : {e}")
            messagebox.showerror("Erreur", f"Une erreur est survenue :\n{e}")
        finally:
            self._busy(False)

    # ------------------------------------------------------ mode 2: generation
    def run_generation(self):
        if not self._require_files():
            return
        fmt = self.fmt_var.get()
        out_path = filedialog.asksaveasfilename(
            title="Enregistrer le fichier de sortie",
            defaultextension=f".{fmt}",
            initialfile=f"ran_network_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}",
            filetypes=[(f"Fichier {fmt.upper()}", f"*.{fmt}")])
        if not out_path:
            return

        self._busy(True)
        try:
            self.mapper.new_run()
            self.log("--- GÉNÉRATION ---")
            all_cells, failures = [], []
            for file_path in self.selected_files:
                name = os.path.basename(file_path)
                cells, error = self.mapper.generate_file(file_path)
                if error:
                    failures.append((name, error))
                    self.log(f"{name} : {error}")
                else:
                    all_cells.extend(cells)
                    self.log(f"{name} : {len(cells)} cellules valides.")

            if failures:
                detail = "\n".join(f"• {n} : {e}" for n, e in failures)
                if not all_cells:
                    messagebox.showerror("Fichiers non configurés",
                                         f"{detail}\n\nUtilisez d'abord l'onglet Découverte.")
                    return
                if not messagebox.askyesno("Fichiers non configurés",
                                           f"{detail}\n\nContinuer sans ces fichiers ?"):
                    self.log("Génération annulée.")
                    return

            self._log_audit_summary()
            if not all_cells:
                self.log("Aucune donnée valide à exporter.")
                messagebox.showerror("Erreur", "Aucune donnée valide à exporter.")
                return

            self.log(f"Génération du fichier {fmt.upper()}...")
            KMLGenerator(self.mapper.config).export(all_cells, out_path)
            self.log(f"Fichier généré : {out_path}")
            messagebox.showinfo("Succès", f"Fichier généré avec succès !\n\n{out_path}")
        except Exception as e:
            self.log(f"Erreur critique : {e}")
            messagebox.showerror("Erreur", f"Une erreur est survenue :\n{e}")
        finally:
            self._busy(False)


if __name__ == "__main__":
    RANGeoMapperGUI().mainloop()