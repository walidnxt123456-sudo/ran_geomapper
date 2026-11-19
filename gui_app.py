import os
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from main import RANGeoMapper
from data_validator import RANDataAuditor
from kml_generator import KMLGenerator
from file_reader import read_data_file

TECHS = ["2G", "3G", "4G", "5G", "MSAN"]
ALL_RULE_TECHS = ["2G", "3G", "4G", "5G", "MSAN"]
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
        self.geometry("820x780")
        self.minsize(780, 720)

        self.selected_files = []
        self.mapper = RANGeoMapper()
        self._build_ui()
        self._load_config_into_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        tk.Label(self, text="RAN-GeoMapper Studio", font=("Segoe UI", 16, "bold")).pack(pady=(10, 0))
        tk.Label(self, text="Découverte des fichiers RAN, génération KMZ/KML et configuration", font=("Segoe UI", 9)).pack(pady=(0, 8))

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
        self.fmt_var = tk.StringVar(value="kmz")
        ttk.Combobox(row, textvariable=self.fmt_var, values=["kmz", "kml"], state="readonly", width=8).pack(side="left", padx=6)
        self.btn_generate = tk.Button(tab_gen, text="🚀 Générer la cartographie", bg="#0066cc", fg="white",
                                      font=("Segoe UI", 10, "bold"), padx=10, pady=4, command=self.run_generation)
        self.btn_generate.pack(anchor="w", pady=4)

        # Tab 3: user-friendly configuration editor
        tab_cfg = tk.Frame(self, padx=10, pady=8)
        self.notebook.add(tab_cfg, text="  3 · Configuration  ")
        self._build_config_tab(tab_cfg)

        self.txt_log = tk.Text(self, height=13, width=98, font=("Consolas", 8), state="disabled")
        self.txt_log.pack(fill="both", expand=True, padx=20, pady=(4, 10))

    def _pick_rule_color(self):
        from tkinter import colorchooser
        chosen = colorchooser.askcolor(title="Choisir la couleur de la règle", parent=self)
        if not chosen or not chosen[1]:
            return
        hex_rgb = chosen[1].lstrip("#")  # rrggbb
        r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]

        current = self.rule_col_var.get().strip()
        alpha = current[:2] if len(current) == 8 else "ff"
        self.rule_col_var.set(f"{alpha}{b}{g}{r}".lower())
        
    def _build_config_tab(self, parent):
        settings_box = tk.LabelFrame(parent, text=" Paramètres généraux ", padx=8, pady=6)
        settings_box.pack(fill="x", pady=(0, 6))

        self.cfg_opacity = tk.StringVar()
        self.cfg_radius = tk.StringVar()
        self.cfg_beamwidth = tk.StringVar()
        self.cfg_offset = tk.StringVar()

        tk.Label(settings_box, text="Opacité (%):").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        tk.Entry(settings_box, textvariable=self.cfg_opacity, width=8).grid(row=0, column=1, sticky="w", padx=4, pady=2)

        tk.Label(settings_box, text="Rayon défaut (m):").grid(row=0, column=2, sticky="w", padx=8, pady=2)
        tk.Entry(settings_box, textvariable=self.cfg_radius, width=8).grid(row=0, column=3, sticky="w", padx=4, pady=2)

        tk.Label(settings_box, text="Ouverture défaut (°):").grid(row=0, column=4, sticky="w", padx=8, pady=2)
        tk.Entry(settings_box, textvariable=self.cfg_beamwidth, width=8).grid(row=0, column=5, sticky="w", padx=4, pady=2)

        tk.Label(settings_box, text="Décalage défaut (m):").grid(row=0, column=6, sticky="w", padx=8, pady=2)
        tk.Entry(settings_box, textvariable=self.cfg_offset, width=8).grid(row=0, column=7, sticky="w", padx=4, pady=2)

        sub_nb = ttk.Notebook(parent)
        sub_nb.pack(fill="both", expand=True, pady=4)

        # Sub-tab A: band_rules
        rules_tab = tk.Frame(sub_nb, padx=6, pady=6)
        sub_nb.add(rules_tab, text=" Règles par bande (band_rules) ")

        self.rules_tree = ttk.Treeview(
            rules_tab,
            columns=("rule", "radius", "beamwidth", "offset", "color"),
            show="headings",
            height=5,
        )
        for col, title, w in [
            ("rule", "Règle (ex: 4G_1800, MSAN)", 180),
            ("radius", "Rayon (m)", 85),
            ("beamwidth", "Angle (°)", 85),
            ("offset", "Décalage (m)", 90),
            ("color", "Couleur KML (aabbggrr)", 140),
        ]:
            self.rules_tree.heading(col, text=title)
            self.rules_tree.column(col, width=w, anchor="center")
        self.rules_tree.pack(fill="x", pady=(0, 6))
        self.rules_tree.bind("<<TreeviewSelect>>", self._on_rule_select)

        rule_form = tk.Frame(rules_tab)
        rule_form.pack(fill="x")
        self.rule_key_var = tk.StringVar()
        self.rule_rad_var = tk.StringVar()
        self.rule_bw_var = tk.StringVar()
        self.rule_off_var = tk.StringVar()
        self.rule_col_var = tk.StringVar()

        tk.Label(rule_form, text="Règle:").grid(row=0, column=0, padx=2)
        tk.Entry(rule_form, textvariable=self.rule_key_var, width=14).grid(row=0, column=1, padx=2)
        tk.Label(rule_form, text="Rayon:").grid(row=0, column=2, padx=2)
        tk.Entry(rule_form, textvariable=self.rule_rad_var, width=7).grid(row=0, column=3, padx=2)
        tk.Label(rule_form, text="Angle:").grid(row=0, column=4, padx=2)
        tk.Entry(rule_form, textvariable=self.rule_bw_var, width=7).grid(row=0, column=5, padx=2)
        tk.Label(rule_form, text="Décalage:").grid(row=0, column=6, padx=2)
        tk.Entry(rule_form, textvariable=self.rule_off_var, width=7).grid(row=0, column=7, padx=2)
        tk.Label(rule_form, text="Couleur:").grid(row=0, column=8, padx=2)
        tk.Entry(rule_form, textvariable=self.rule_col_var, width=10).grid(row=0, column=9, padx=2)

        tk.Label(rule_form, text="Couleur:").grid(row=0, column=8, padx=2)
        tk.Entry(rule_form, textvariable=self.rule_col_var, width=10).grid(row=0, column=9, padx=2)
        tk.Button(rule_form, text="🎨 Couleur", command=self._pick_rule_color).grid(row=0, column=10, padx=4)

        rule_btns = tk.Frame(rules_tab)
        rule_btns.pack(fill="x", pady=(5, 0))
        tk.Button(rule_btns, text="Ajouter / Mettre à jour", command=self._upsert_rule).pack(side="left", padx=3)
        tk.Button(rule_btns, text="Supprimer", command=self._delete_rule).pack(side="left", padx=3)
        tk.Button(rule_btns, text="Modèle MSAN", command=self._fill_msan_template).pack(side="left", padx=3)

        # Sub-tab B: band_mapping ranges
        map_tab = tk.Frame(sub_nb, padx=6, pady=6)
        sub_nb.add(map_tab, text=" Plages canaux (band_mapping) ")

        self.map_tree = ttk.Treeview(
            map_tab,
            columns=("tech", "band", "min_ch", "max_ch"),
            show="headings",
            height=5,
        )
        for col, title, w in [
            ("tech", "Technologie", 110),
            ("band", "Bande cible", 110),
            ("min_ch", "Canal min", 110),
            ("max_ch", "Canal max", 110),
        ]:
            self.map_tree.heading(col, text=title)
            self.map_tree.column(col, width=w, anchor="center")
        self.map_tree.pack(fill="x", pady=(0, 6))

        map_form = tk.Frame(map_tab)
        map_form.pack(fill="x")
        self.map_tech_var = tk.StringVar(value="4G")
        self.map_band_var = tk.StringVar()
        self.map_min_var = tk.StringVar()
        self.map_max_var = tk.StringVar()

        tk.Label(map_form, text="Tech:").grid(row=0, column=0, padx=2)
        ttk.Combobox(map_form, textvariable=self.map_tech_var, values=ALL_RULE_TECHS, state="readonly", width=8).grid(row=0, column=1, padx=2)
        tk.Label(map_form, text="Bande:").grid(row=0, column=2, padx=2)
        tk.Entry(map_form, textvariable=self.map_band_var, width=10).grid(row=0, column=3, padx=2)
        tk.Label(map_form, text="Min:").grid(row=0, column=4, padx=2)
        tk.Entry(map_form, textvariable=self.map_min_var, width=10).grid(row=0, column=5, padx=2)
        tk.Label(map_form, text="Max:").grid(row=0, column=6, padx=2)
        tk.Entry(map_form, textvariable=self.map_max_var, width=10).grid(row=0, column=7, padx=2)

        map_btns = tk.Frame(map_tab)
        map_btns.pack(fill="x", pady=(5, 0))
        tk.Button(map_btns, text="Ajouter plage", command=self._add_range).pack(side="left", padx=3)
        tk.Button(map_btns, text="Supprimer plage", command=self._delete_range).pack(side="left", padx=3)

        # Save / Reload bar
        save_bar = tk.Frame(parent)
        save_bar.pack(fill="x", pady=(6, 0))
        tk.Button(save_bar, text="💾 Appliquer et enregistrer en temps réel", bg="#28a745", fg="white",
                  font=("Segoe UI", 9, "bold"), padx=10, pady=4, command=self.save_config_realtime).pack(side="left")
        tk.Button(save_bar, text="Recharger depuis config.json", padx=8, pady=4,
                  command=self._load_config_into_ui).pack(side="left", padx=8)

        # Bloc dédié MSAN (taille du cercle + couleur)
        msan_box = tk.LabelFrame(parent, text=" Couche MSAN (Cercle) ", padx=8, pady=6)
        msan_box.pack(fill="x", pady=(0, 6))

        self.msan_radius_var = tk.StringVar(value="50")
        self.msan_color_var = tk.StringVar(value="ffff8000")

        tk.Label(msan_box, text="Taille du cercle / Rayon (m) :").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        tk.Entry(msan_box, textvariable=self.msan_radius_var, width=10).grid(row=0, column=1, sticky="w", padx=4, pady=2)

        tk.Label(msan_box, text="Couleur KML (aabbggrr) :").grid(row=0, column=2, sticky="w", padx=(12, 4), pady=2)
        tk.Entry(msan_box, textvariable=self.msan_color_var, width=12).grid(row=0, column=3, sticky="w", padx=4, pady=2)

        tk.Button(msan_box, text="🎨 Choisir couleur", command=self._pick_msan_color).grid(row=0, column=4, padx=6)

    def _pick_msan_color(self):
        from tkinter import colorchooser
        chosen = colorchooser.askcolor(title="Choisir la couleur MSAN", parent=self)
        if not chosen or not chosen[1]:
            return
        hex_rgb = chosen[1].lstrip("#")  # rrggbb
        r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
        # KML utilise aabbggrr ; l'alpha final est géré par global_opacity_percent
        self.msan_color_var.set(f"ff{b}{g}{r}".lower())

    def _load_config_into_ui(self):
        settings = self.mapper.config.get("settings", {})
        self.fmt_var.set(str(settings.get("output_format", "kmz")).lower())
        self.cfg_opacity.set(str(settings.get("global_opacity_percent", 45)))
        self.cfg_radius.set(str(settings.get("default_radius_m", 360)))
        self.cfg_beamwidth.set(str(settings.get("default_beamwidth", 60)))
        self.cfg_offset.set(str(settings.get("default_offset_m", 8)))

        msan_rule = self.mapper.config.get("band_rules", {}).get("MSAN", {})
        self.msan_radius_var.set(str(msan_rule.get("radius_m", 50)))
        self.msan_color_var.set(str(msan_rule.get("color_kml", "ffff8000")))

        for item in self.rules_tree.get_children():
            self.rules_tree.delete(item)
        for key, rule in sorted(self.mapper.config.get("band_rules", {}).items()):
            self.rules_tree.insert("", "end", values=(
                key,
                rule.get("radius_m", ""),
                rule.get("beamwidth", ""),
                rule.get("offset_m", ""),
                rule.get("color_kml", ""),
            ))

        for item in self.map_tree.get_children():
            self.map_tree.delete(item)
        for tech, bands in sorted(self.mapper.config.get("band_mapping", {}).items()):
            for band, ranges in sorted(bands.items()):
                for r in ranges:
                    if isinstance(r, (list, tuple)) and len(r) == 2:
                        self.map_tree.insert("", "end", values=(tech, band, r[0], r[1]))

    def _on_rule_select(self, _event):
        sel = self.rules_tree.selection()
        if not sel:
            return
        vals = self.rules_tree.item(sel[0], "values")
        self.rule_key_var.set(vals[0])
        self.rule_rad_var.set(vals[1])
        self.rule_bw_var.set(vals[2])
        self.rule_off_var.set(vals[3])
        self.rule_col_var.set(vals[4])

    def _upsert_rule(self):
        key = self.rule_key_var.get().strip()
        if not key:
            messagebox.showwarning("Champ requis", "Indiquez un nom de règle (ex: 4G_1800 ou MSAN).", parent=self)
            return
        try:
            rad = float(self.rule_rad_var.get())
            bw = float(self.rule_bw_var.get())
            off = float(self.rule_off_var.get())
        except ValueError:
            messagebox.showwarning("Valeur invalide", "Rayon, angle et décalage doivent être numériques.", parent=self)
            return
        col = self.rule_col_var.get().strip()
        vals = (key, rad, bw, off, col)
        for item in self.rules_tree.get_children():
            if self.rules_tree.item(item, "values")[0] == key:
                self.rules_tree.item(item, values=vals)
                return
        self.rules_tree.insert("", "end", values=vals)

    def _delete_rule(self):
            for item in self.rules_tree.selection():
                self.rules_tree.delete(item)

    def _fill_msan_template(self):
        self.rule_key_var.set("MSAN")
        self.rule_rad_var.set("50")
        self.rule_bw_var.set("360")
        self.rule_off_var.set("5")
        self.rule_col_var.set("ffff8000")

    def _add_range(self):
        tech = self.map_tech_var.get().strip()
        band = self.map_band_var.get().strip()
        if not tech or not band:
            messagebox.showwarning("Champ requis", "Indiquez la technologie et la bande cible.", parent=self)
            return
        try:
            low = float(self.map_min_var.get())
            high = float(self.map_max_var.get())
        except ValueError:
            messagebox.showwarning("Valeur invalide", "Les bornes min et max doivent être numériques.", parent=self)
            return
        if low > high:
            messagebox.showwarning("Plage invalide", "Le canal min doit être inférieur ou égal au canal max.", parent=self)
            return
        self.map_tree.insert("", "end", values=(tech, band, int(low) if low.is_integer() else low, int(high) if high.is_integer() else high))

    def _delete_range(self):
        for item in self.map_tree.selection():
            self.map_tree.delete(item)


    def save_config_realtime(self):
        try:
            opacity = float(self.cfg_opacity.get())
            radius = float(self.cfg_radius.get())
            beamwidth = float(self.cfg_beamwidth.get())
            offset = float(self.cfg_offset.get())
        except ValueError:
            messagebox.showerror("Paramètres invalides", "Vérifiez que les paramètres généraux sont numériques.")
            return

        try:
            msan_radius = float(self.msan_radius_var.get())
        except ValueError:
            messagebox.showerror("Paramètre MSAN invalide", "La taille du cercle MSAN doit être numérique.")
            return

        new_rules = {}
        for item in self.rules_tree.get_children():
            key, rad, bw, off, col = self.rules_tree.item(item, "values")
            new_rules[str(key)] = {
                "radius_m": float(rad),
                "beamwidth": float(bw),
                "offset_m": float(off),
                "color_kml": str(col).strip(),
            }

        msan_color = self.msan_color_var.get().strip()
        new_rules["MSAN"] = {
            "radius_m": msan_radius,
            "beamwidth": 360.0,
            "offset_m": float(new_rules.get("MSAN", {}).get("offset_m", 5.0)),
            "color_kml": msan_color,
        }

        new_mapping = {}
        for item in self.map_tree.get_children():
            tech, band, low, high = self.map_tree.item(item, "values")
            new_mapping.setdefault(str(tech), {}).setdefault(str(band), []).append([float(low), float(high)])

        self.mapper.config.setdefault("settings", {}).update({
            "output_format": self.fmt_var.get(),
            "global_opacity_percent": opacity,
            "default_radius_m": radius,
            "default_beamwidth": beamwidth,
            "default_offset_m": offset,
        })
        self.mapper.config["band_rules"] = new_rules
        self.mapper.config["band_mapping"] = new_mapping
        self.mapper.save_config()

        # Rafraîchir l'arbre des règles pour refléter MSAN et appliquer immédiatement à l'auditeur
        self._load_config_into_ui()
        self.mapper.auditor = RANDataAuditor(self.mapper.config.get("band_mapping", {}))
        self.log("Configuration enregistrée et appliquée en temps réel.")
        messagebox.showinfo("Configuration enregistrée", "La configuration a été enregistrée et appliquée en temps réel.")


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