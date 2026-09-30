import re
import math
import zipfile
import logging
from datetime import datetime
from xml.sax.saxutils import escape

_INVALID_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_HEX8 = re.compile(r"^[0-9a-fA-F]{8}$")

def xml_text(value):
    """Escapes &, <, > and strips characters that are illegal in XML 1.0."""
    return escape(_INVALID_XML_CHARS.sub("", str(value)))

def safe_id(text):
    return re.sub(r"[^a-zA-Z0-9_]", "_", str(text))

# Fallback colors if config doesn't specify them for a specific band (aabbggrr)
TECH_COLORS_FALLBACK = {
    "2G": {"fill": "8000a5ff", "line": "ff0055ff"},
    "3G": {"fill": "8000d7ff", "line": "ff00aaff"},
    "4G": {"fill": "80ff8000", "line": "ffff3300"},
    "5G": {"fill": "8000bf00", "line": "ff008000"},
    "DEFAULT": {"fill": "80808080", "line": "ff404040"}
}

TECH_ORDER = ["2G", "3G", "4G", "5G", "DEFAULT"]
SITE_ICON = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"


class KMLGenerator:
    """
    Generates structured KML/KMZ files with sector wedge polygons and rich HTML popups.
    Driven by config.json: band_rules (radius, beamwidth, offset, color) and
    settings (global_opacity_percent, default_*).

    Layout:  Tech > "01 - Sites" (one point per site)
                  > one folder per band (sector wedges of that band)
    """
    def __init__(self, config):
        self.settings = config.get("settings", {})
        self.band_rules = config.get("band_rules", {})

        self.default_radius = self.settings.get("default_radius_m", 250)
        self.default_beamwidth = self.settings.get("default_beamwidth", 60)
        self.default_offset = self.settings.get("default_offset_m", 8)

        try:
            opacity = float(self.settings.get("global_opacity_percent", 50))
        except (TypeError, ValueError):
            opacity = 50.0
        opacity = max(0.0, min(100.0, opacity))
        self.fill_alpha = f"{round(255 * opacity / 100):02x}"

    # ------------------------------------------------------------------ rules
    def _get_rule_for_cell(self, cell):
        """Looks up the specific band rule, falling back to tech defaults or global defaults."""
        tech = cell["tech"]
        band = cell["band"]
        rule_key = f"{tech}_{band}"

        # 1. Exact match (e.g., "4G_1800")
        if rule_key in self.band_rules:
            return rule_key, self.band_rules[rule_key]

        # 2. Generic tech rule (e.g., "4G")
        if tech in self.band_rules:
            return tech, self.band_rules[tech]

        # 3. Global defaults
        fallback_color = TECH_COLORS_FALLBACK.get(tech, TECH_COLORS_FALLBACK["DEFAULT"])["fill"]
        return rule_key, {
            "radius_m": self.default_radius,
            "beamwidth": self.default_beamwidth,
            "offset_m": self.default_offset,
            "color_kml": fallback_color
        }

    def _colors(self, rule, tech):
        """
        Returns (fill, line) KML colors. RGB comes from the rule's color_kml;
        the fill alpha comes from settings.global_opacity_percent, the outline is opaque.
        """
        color = str(rule.get("color_kml", ""))
        if not _HEX8.match(color):
            color = TECH_COLORS_FALLBACK.get(tech, TECH_COLORS_FALLBACK["DEFAULT"])["fill"]
        bgr = color[2:]
        return f"{self.fill_alpha}{bgr}", f"ff{bgr}"

    # --------------------------------------------------------------- geometry
    @staticmethod
    def destination_point(lat, lon, distance_m, bearing_deg):
        r_earth = 6371000.0
        bearing = math.radians(bearing_deg)
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        target_lat_rad = math.asin(
            math.sin(lat_rad) * math.cos(distance_m / r_earth) +
            math.cos(lat_rad) * math.sin(distance_m / r_earth) * math.cos(bearing)
        )
        target_lon_rad = lon_rad + math.atan2(
            math.sin(bearing) * math.sin(distance_m / r_earth) * math.cos(lat_rad),
            math.cos(distance_m / r_earth) - math.sin(lat_rad) * math.sin(target_lat_rad)
        )
        return math.degrees(target_lat_rad), math.degrees(target_lon_rad)

    def create_wedge_polygon(self, lat, lon, azimuth, radius, beamwidth, offset_m=0, num_points=12):
        """
        Wedge polygon. The apex is pushed offset_m metres along the azimuth so that
        co-sited wedges of different bands do not share the exact same corner
        (the radius is measured from that apex).
        """
        if offset_m:
            lat, lon = self.destination_point(lat, lon, offset_m, azimuth)
        half_beam = beamwidth / 2.0
        start_angle = azimuth - half_beam
        coords = [(lon, lat)]
        step = beamwidth / float(num_points)
        for i in range(num_points + 1):
            angle = start_angle + (i * step)
            pt_lat, pt_lon = self.destination_point(lat, lon, radius, angle)
            coords.append((pt_lon, pt_lat))
        coords.append((lon, lat))
        return " ".join(f"{c[0]:.6f},{c[1]:.6f},0" for c in coords)

    # ----------------------------------------------------------------- popups
    @staticmethod
    def generate_popup_html(cell):
        html = [
            "<table border='1' style='border-collapse:collapse; width:100%; font-family:Arial, sans-serif; font-size:12px;'>",
            f"<tr style='background-color:#0055ff; color:white;'><th colspan='2' style='padding:5px;'>{xml_text(cell['cell_name'])}</th></tr>",
            f"<tr><td style='padding:3px;'><b>Site ID</b></td><td style='padding:3px;'>{xml_text(cell['site_id'])}</td></tr>",
            f"<tr><td style='padding:3px;'><b>Cell ID</b></td><td style='padding:3px;'>{xml_text(cell['cell_id'])}</td></tr>",
            f"<tr><td style='padding:3px;'><b>Technologie</b></td><td style='padding:3px;'>{xml_text(cell['tech'])}</td></tr>",
            f"<tr><td style='padding:3px;'><b>Bande</b></td><td style='padding:3px;'>{xml_text(cell['band'])}</td></tr>",
            f"<tr><td style='padding:3px;'><b>Azimut</b></td><td style='padding:3px;'>{xml_text(cell['azimuth'])}°</td></tr>",
            f"<tr><td style='padding:3px;'><b>Latitude</b></td><td style='padding:3px;'>{cell['latitude']}</td></tr>",
            f"<tr><td style='padding:3px;'><b>Longitude</b></td><td style='padding:3px;'>{cell['longitude']}</td></tr>"
        ]
        for key, val in cell["attributes"].items():
            if key.lower() not in ["latitude", "longitude", "azimuth", "azimut", "site_id", "cell_id", "tech", "band", "site_name", "cell_name"]:
                html.append(f"<tr><td style='padding:3px;'>{xml_text(key)}</td><td style='padding:3px;'>{xml_text(val)}</td></tr>")
        html.append("</table>")
        return "".join(html)

    @staticmethod
    def generate_site_popup_html(site_id, site_name, cells):
        html = [
            "<table border='1' style='border-collapse:collapse; width:100%; font-family:Arial, sans-serif; font-size:12px;'>",
            f"<tr style='background-color:#333; color:white;'><th colspan='3' style='padding:5px;'>{xml_text(site_name)}</th></tr>",
            f"<tr><td style='padding:3px;'><b>Site ID</b></td><td colspan='2' style='padding:3px;'>{xml_text(site_id)}</td></tr>",
            f"<tr><td style='padding:3px;'><b>Cellules</b></td><td colspan='2' style='padding:3px;'>{len(cells)}</td></tr>",
            "<tr style='background-color:#eee;'><th style='padding:3px;'>Bande</th><th style='padding:3px;'>Cellule</th><th style='padding:3px;'>Azimut</th></tr>",
        ]
        for c in sorted(cells, key=lambda c: (c["band"], c["azimuth"], c["cell_name"])):
            html.append(
                f"<tr><td style='padding:3px;'>{xml_text(c['band'])}</td>"
                f"<td style='padding:3px;'>{xml_text(c['cell_name'])}</td>"
                f"<td style='padding:3px;'>{xml_text(c['azimuth'])}°</td></tr>"
            )
        html.append("</table>")
        return "".join(html)

    # -------------------------------------------------------------- KML build
    def build_kml(self, valid_cells):
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        kml = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<kml xmlns="http://www.opengis.net/kml/2.2">',
            '<Document>',
            f'  <name>Réseau RAN Mobile (Généré le {now_str})</name>'
        ]

        # 1. Resolve rules once; collect styles actually used
        cells_with_rules = []
        wedge_styles = {}
        for cell in valid_cells:
            rule_key, rule = self._get_rule_for_cell(cell)
            cells_with_rules.append((cell, rule_key, rule))
            if rule_key not in wedge_styles:
                wedge_styles[rule_key] = self._colors(rule, cell["tech"])

        # 2. Styles: wedges (labels hidden, popup on click) and site points (labels shown)
        for rule_key, (fill, line) in wedge_styles.items():
            kml.append(f'''  <Style id="style_{safe_id(rule_key)}">
    <LabelStyle><scale>0</scale></LabelStyle>
    <LineStyle><color>{line}</color><width>1.5</width></LineStyle>
    <PolyStyle><color>{fill}</color><fill>1</fill><outline>1</outline></PolyStyle>
  </Style>''')

        # 3. Group by tech, then by band
        tech_groups = {}
        for cell, rule_key, rule in cells_with_rules:
            tech = cell["tech"] if cell["tech"] in TECH_COLORS_FALLBACK else "DEFAULT"
            tech_groups.setdefault(tech, []).append((cell, rule_key, rule))

        for tech in TECH_ORDER:
            if tech in tech_groups:
                line = TECH_COLORS_FALLBACK[tech]["line"]
                kml.append(f'''  <Style id="site_{tech}">
    <IconStyle><color>{line}</color><scale>0.7</scale><Icon><href>{SITE_ICON}</href></Icon></IconStyle>
    <LabelStyle><scale>0.8</scale></LabelStyle>
  </Style>''')

        for tech in TECH_ORDER:
            if tech not in tech_groups:
                continue
            entries = tech_groups[tech]
            kml.append(f'  <Folder>\n    <name>{tech}</name>')

            # --- Sites: one point per site (mean of its cells' coordinates)
            sites = {}
            for cell, _, _ in entries:
                sites.setdefault(cell["site_id"], []).append(cell)
            kml.append(f'    <Folder>\n      <name>01 - {tech} Sites ({len(sites)})</name>')
            for site_id in sorted(sites):
                cells = sites[site_id]
                s_lat = sum(c["latitude"] for c in cells) / len(cells)
                s_lon = sum(c["longitude"] for c in cells) / len(cells)
                s_name = cells[0]["site_name"] or site_id
                popup = self.generate_site_popup_html(site_id, s_name, cells)
                kml.append(f'''      <Placemark>
        <name>{xml_text(s_name)}</name>
        <styleUrl>#site_{tech}</styleUrl>
        <description><![CDATA[{popup}]]></description>
        <Point><coordinates>{s_lon:.6f},{s_lat:.6f},0</coordinates></Point>
      </Placemark>''')
            kml.append('    </Folder>')

            # --- Cells: one folder per band, largest radius first (drawn underneath)
            bands = {}
            for cell, rule_key, rule in entries:
                bands.setdefault(cell["band"], []).append((cell, rule_key, rule))

            def band_sort_key(item):
                band, items = item
                return (-items[0][2].get("radius_m", self.default_radius), band)

            for idx, (band, items) in enumerate(sorted(bands.items(), key=band_sort_key), start=2):
                kml.append(f'    <Folder>\n      <name>{idx:02d} - {tech} {xml_text(band)} ({len(items)} cellules)</name>')
                for cell, rule_key, rule in items:
                    radius = rule.get("radius_m", self.default_radius)
                    beamwidth = rule.get("beamwidth", self.default_beamwidth)
                    offset = rule.get("offset_m", self.default_offset)

                    wedge_coords = self.create_wedge_polygon(
                        cell["latitude"], cell["longitude"], cell["azimuth"],
                        radius, beamwidth, offset
                    )
                    popup_content = self.generate_popup_html(cell)
                    kml.append(f'''      <Placemark>
        <name>{xml_text(cell['cell_name'])}</name>
        <styleUrl>#style_{safe_id(rule_key)}</styleUrl>
        <description><![CDATA[{popup_content}]]></description>
        <Polygon>
          <altitudeMode>clampToGround</altitudeMode>
          <outerBoundaryIs>
            <LinearRing>
              <coordinates>{wedge_coords}</coordinates>
            </LinearRing>
          </outerBoundaryIs>
        </Polygon>
      </Placemark>''')
                kml.append('    </Folder>')
            kml.append('  </Folder>')

        kml.append('</Document>')
        kml.append('</kml>')
        return "\n".join(kml)

    def export(self, valid_cells, output_path):
        kml_content = self.build_kml(valid_cells)
        if output_path.lower().endswith(".kmz"):
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as kmz:
                kmz.writestr("doc.kml", kml_content)
            logging.info(f"Fichier KMZ généré avec succès : '{output_path}'")
        else:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(kml_content)
            logging.info(f"Fichier KML généré avec succès : '{output_path}'")