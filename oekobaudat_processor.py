"""
Ökobaudat Filter- & Aggregationstool (Phase 2 Datenvorbereitung / Baustoff-Verknüpfung).

Ermöglicht das effiziente Filtern großer Ökobaudat-CSV-Dateien (Streaming / Chunking)
nach Suchbegriffen (z. B. "Kalksandstein", "Beton", "Dämmung") sowie das
statistische Vermitteln / Bilden von Durchschnittswerten für GWP-Kennwerte
(GWPtotal (A2) / GWP) pro Lebenszyklus-Modul (A1-A3, A4, A5, C1-C4, D usw.),
sofern die Werte innerhalb einer konfigurierbaren Toleranzgrenze (Standard: 15%) liegen.
"""

import csv
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Generator, Iterable, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


@dataclass
class OekobaudatRecord:
    """Repräsentiert eine Zeile aus einem Ökobaudat-Datensatz."""
    uuid: str
    version: str
    name_de: str
    name_en: str
    kategorie_de: str
    kategorie_en: str
    konformitaet: str
    bezugsgroesse: float
    bezugseinheit: str
    rohdichte_kg_m3: Optional[float]
    modul: str
    szenario: str
    gwp_total_a2: Optional[float]
    gwp_fossil_a2: Optional[float]
    gwp_biogenic_a2: Optional[float]
    gwp_a1_a2: Optional[float]  # GWP Spalte (DIN EN 15804+A1/A2 legacy)
    raw_data: Dict[str, str] = field(default_factory=dict)


def _parse_german_float(val: Optional[str]) -> Optional[float]:
    """Konvertiert deutsche Zahlenformate (z. B. '1,43' oder '1.43' oder wissenschaftlich '2,68E-19') in float."""
    if not val:
        return None
    val_str = str(val).strip()
    if not val_str or val_str == "-" or val_str.lower() == "nan":
        return None
    # Komma durch Punkt ersetzen
    val_normalized = val_str.replace(",", ".")
    try:
        return float(val_normalized)
    except ValueError:
        return None


def _format_german_float(val: Optional[float], decimals: int = 6) -> str:
    """Formatiert Float für CSV mit deutschem Komma."""
    if val is None:
        return ""
    # Format number nicely, removing trailing zeroes if possible
    formatted = f"{val:.{decimals}f}".rstrip("0").rstrip(".")
    if not formatted or formatted == "-0":
        formatted = "0"
    return formatted.replace(".", ",")


class OekobaudatProcessor:
    """
    Effiziente Verarbeitung von Ökobaudat CSV-Exports.
    Unterstützt Streaming / Zeilen-weises Einlesen, flexible Baustoff-Filterung
    und Mittelwertbildung mit 15%-Toleranzprüfung.
    """

    def __init__(self, delimiter: str = ";", encoding: str = "utf-8-sig"):
        self.delimiter = delimiter
        self.encoding = encoding

    def parse_row(self, row: Dict[str, str]) -> OekobaudatRecord:
        """Extrahiert relevante Kernattribute aus einem Ökobaudat CSV-Dictionary."""
        # Feldnamen können Leerzeichen oder leicht abweichende Schreibweisen haben
        def get_field(keys: List[str]) -> str:
            for k in keys:
                if k in row and row[k]:
                    return row[k].strip()
            return ""

        uuid = get_field(["UUID", "uuid"])
        version = get_field(["Version", "version"])
        name_de = get_field(["Name (de)", "Name", "name_de"])
        name_en = get_field(["Name (en)", "name_en"])
        kat_de = get_field(["Kategorie (original)", "Kategorie (de)", "Kategorie"])
        kat_en = get_field(["Kategorie (en)"])
        konformitaet = get_field(["Konformitaet", "Konformität"])
        bezugsgroesse = _parse_german_float(get_field(["Bezugsgroesse", "Bezugsgroesse", "Bezugsgröße"])) or 1.0
        bezugseinheit = get_field(["Bezugseinheit", "Einheit"]) or "kg"
        rohdichte = _parse_german_float(get_field(["Rohdichte (kg/m3)", "Rohdichte", "Schuettdichte (kg/m3)"]))
        modul = get_field(["Modul", "Lebenszyklusstadium", "Lifecycle stage"])
        szenario = get_field(["Szenario", "Scenario"])

        gwp_total_a2 = _parse_german_float(get_field(["GWPtotal (A2)", "GWP-total (A2)", "GWPtotal"]))
        gwp_fossil_a2 = _parse_german_float(get_field(["GWPfossil (A2)", "GWP-fossil (A2)", "GWPfossil"]))
        gwp_biogenic_a2 = _parse_german_float(get_field(["GWPbiogenic (A2)", "GWP-biogenic (A2)", "GWPbiogenic"]))
        gwp_a1 = _parse_german_float(get_field(["GWP", "GWP (A1)"]))

        return OekobaudatRecord(
            uuid=uuid,
            version=version,
            name_de=name_de,
            name_en=name_en,
            kategorie_de=kat_de,
            kategorie_en=kat_en,
            konformitaet=konformitaet,
            bezugsgroesse=bezugsgroesse,
            bezugseinheit=bezugseinheit,
            rohdichte_kg_m3=rohdichte,
            modul=modul,
            szenario=szenario,
            gwp_total_a2=gwp_total_a2,
            gwp_fossil_a2=gwp_fossil_a2,
            gwp_biogenic_a2=gwp_biogenic_a2,
            gwp_a1_a2=gwp_a1,
            raw_data=row
        )

    def stream_filter(
        self,
        file_path_or_buffer: Union[str, Path, io.TextIOBase],
        keywords: List[str],
        modules: Optional[List[str]] = None,
        case_sensitive: bool = False
    ) -> Generator[Tuple[OekobaudatRecord, Dict[str, str]], None, None]:
        """
        Liest eine CSV-Datei zeilenweise (Speicherschonend / Streaming)
        und liefert Datensätze zurück, die die Suchbegriffe enthalten.

        Args:
            file_path_or_buffer: Pfad zur CSV oder File-like Object
            keywords: Liste von Suchbegriffen (z. B. ['Kalksandstein', 'Schaumglas'])
            modules: Optionale Filterung nach Modulen (z. B. ['A1-A3', 'A4', 'A5'])
            case_sensitive: Groß-/Kleinschreibung beachten
        """
        if isinstance(file_path_or_buffer, (str, Path)):
            f = open(file_path_or_buffer, mode="r", encoding=self.encoding, errors="replace")
            close_needed = True
        else:
            f = file_path_or_buffer
            close_needed = False

        try:
            reader = csv.DictReader(f, delimiter=self.delimiter)
            
            # Schlüsselwörter vorbereiten
            prepared_kw = [kw if case_sensitive else kw.lower() for kw in keywords if kw.strip()]
            prepared_modules = set(m.upper() for m in modules) if modules else None

            for row in reader:
                # Schnelle Textprüfung in Name & Kategorie
                name_de = row.get("Name (de)", "") or ""
                name_en = row.get("Name (en)", "") or ""
                kat = row.get("Kategorie (original)", "") or ""
                
                search_text = f"{name_de} {name_en} {kat}"
                if not case_sensitive:
                    search_text = search_text.lower()

                # Prüfen ob mindestens ein Keyword matcht
                matched = any(kw in search_text for kw in prepared_kw) if prepared_kw else True
                if not matched:
                    continue

                modul_val = (row.get("Modul") or "").strip().upper()
                if prepared_modules and modul_val not in prepared_modules:
                    continue

                record = self.parse_row(row)
                yield record, row

        finally:
            if close_needed:
                f.close()

    def filter_and_save(
        self,
        input_csv: Union[str, Path],
        output_csv: Union[str, Path],
        keywords: List[str],
        modules: Optional[List[str]] = None
    ) -> int:
        """
        Filtert die CSV nach Suchbegriffen und speichert alle passenden Zeilen
        in eine neue CSV-Datei.
        """
        input_path = Path(input_csv)
        output_path = Path(output_csv)
        
        count = 0
        header: Optional[List[str]] = None

        with open(input_path, "r", encoding=self.encoding, errors="replace") as fin:
            reader = csv.DictReader(fin, delimiter=self.delimiter)
            header = reader.fieldnames

            if not header:
                logger.warning(f"Keine Header in {input_csv} gefunden.")
                return 0

            with open(output_path, "w", encoding="utf-8-sig", newline="") as fout:
                writer = csv.DictWriter(fout, fieldnames=header, delimiter=self.delimiter)
                writer.writeheader()

                for record, raw_row in self.stream_filter(fin, keywords=keywords, modules=modules):
                    writer.writerow(raw_row)
                    count += 1

        logger.info(f"{count} Datensätze nach {output_csv} exportiert.")
        return count

    @staticmethod
    def check_deviation_within_tolerance(values: List[float], max_deviation_percent: float = 15.0) -> bool:
        """
        Prüft, ob alle Werte in der Liste maximal `max_deviation_percent` (z. B. 15%)
        vom Mittelwert oder von Min/Max abweichen.

        Definition: (max(values) - min(values)) / mean(values) <= (max_deviation_percent / 100)
        Falls Mittelwert 0 ist, müssen alle Werte identisch sein.
        """
        if not values:
            return True
        if len(values) == 1:
            return True

        min_val = min(values)
        max_val = max(values)
        mean_val = sum(values) / len(values)

        if mean_val == 0:
            return min_val == max_val

        # Relative Spanne im Verhältnis zum Mittelwert
        span = max_val - min_val
        relative_span = (span / abs(mean_val)) * 100.0
        return relative_span <= max_deviation_percent

    def aggregate_materials_by_module(
        self,
        records: List[OekobaudatRecord],
        target_modules: Optional[List[str]] = None,
        max_deviation_percent: float = 15.0,
        gwp_field: str = "gwp_total_a2"
    ) -> Dict[str, Dict[str, Union[float, bool, int, List[float], str]]]:
        """
        Gruppiert Datensätze nach Modul (z. B. A1-A3, A4, A5), prüft die 15% Abweichung
        und berechnet den vermittelten Durchschnittswert.

        Args:
            records: Liste der gefilterten Oekobaudat-Datensätze
            target_modules: Relevante Module (Standard: ['A1-A3', 'A4', 'A5'])
            max_deviation_percent: Max. zulässige Abweichung in % (Standard: 15.0)
            gwp_field: Zu aggregierendes Feld ('gwp_total_a2' oder 'gwp_a1_a2')

        Returns:
            Dictionary gemappt nach Modul:
            {
                'A1-A3': {
                    'mean_gwp': 1.43,
                    'min_gwp': 1.35,
                    'max_gwp': 1.50,
                    'count': 3,
                    'within_tolerance': True,
                    'deviation_percent': 10.5,
                    'unit': 'kg',
                    'material_names': ['...', '...']
                }, ...
            }
        """
        if target_modules is None:
            target_modules = ["A1-A3", "A4", "A5"]

        # Modul -> Liste von Werten
        module_data: Dict[str, List[Tuple[float, str, str]]] = {m.upper(): [] for m in target_modules}

        for rec in records:
            mod = rec.modul.strip().upper()
            if mod in module_data:
                # Wähle GWP Wert
                val = getattr(rec, gwp_field, None)
                if val is None and gwp_field == "gwp_total_a2":
                    # Fallback auf gwp_a1_a2 falls GWPtotal nicht belegt ist
                    val = rec.gwp_a1_a2

                if val is not None:
                    module_data[mod].append((val, rec.name_de, rec.bezugseinheit))

        results = {}
        for mod, val_entries in module_data.items():
            if not val_entries:
                results[mod] = {
                    "count": 0,
                    "mean_gwp": None,
                    "min_gwp": None,
                    "max_gwp": None,
                    "within_tolerance": False,
                    "deviation_percent": 0.0,
                    "unit": "",
                    "material_names": [],
                    "status": "Keine Werte vorhanden"
                }
                continue

            vals = [e[0] for e in val_entries]
            names = list(set(e[1] for e in val_entries))
            units = list(set(e[2] for e in val_entries))
            unit_str = units[0] if units else "kg"

            min_v = min(vals)
            max_v = max(vals)
            mean_v = sum(vals) / len(vals)

            span = max_v - min_v
            rel_dev = (span / abs(mean_v) * 100.0) if mean_v != 0 else 0.0
            within_tol = rel_dev <= max_deviation_percent

            results[mod] = {
                "count": len(vals),
                "mean_gwp": round(mean_v, 6),
                "min_gwp": min_v,
                "max_gwp": max_v,
                "within_tolerance": within_tol,
                "deviation_percent": round(rel_dev, 2),
                "unit": unit_str,
                "material_names": names,
                "status": "Vermittelt (innerhalb 15%)" if within_tol else f"Abweichung zu hoch ({rel_dev:.1f}% > {max_deviation_percent}%)"
            }

        return results

    def filter_and_aggregate_summary(
        self,
        input_csv: Union[str, Path],
        keywords: List[str],
        modules: Optional[List[str]] = None,
        max_deviation_percent: float = 15.0,
        output_summary_csv: Optional[Union[str, Path]] = None,
        output_filtered_csv: Optional[Union[str, Path]] = None
    ) -> Tuple[List[OekobaudatRecord], Dict[str, Dict[str, Any]]]:
        """
        Gesamter Workflow:
        1. Filtert die große Ökobaudat-CSV nach Suchbegriffen (Streaming)
        2. Speichert optional die gefilterten Rohdaten in `output_filtered_csv`
        3. Aggregiert Module (A1-A3, A4, A5 etc.) und prüft 15% Abweichung
        4. Speichert optional die vermittelten Durchschnittswerte in `output_summary_csv`
        """
        if modules is None:
            modules = ["A1-A3", "A4", "A5"]

        filtered_records: List[OekobaudatRecord] = []
        raw_rows: List[Dict[str, str]] = []

        # 1. Filtern
        with open(input_csv, "r", encoding=self.encoding, errors="replace") as fin:
            for rec, raw in self.stream_filter(fin, keywords=keywords, modules=None):
                filtered_records.append(rec)
                raw_rows.append(raw)

        logger.info(f"Gefiltert: {len(filtered_records)} Zeilen für Suchbegriffe {keywords}")

        # 2. Gefilterte Roh-CSV speichern (optional)
        if output_filtered_csv and raw_rows:
            out_p = Path(output_filtered_csv)
            with open(out_p, "w", encoding="utf-8-sig", newline="") as fout:
                writer = csv.DictWriter(fout, fieldnames=list(raw_rows[0].keys()), delimiter=self.delimiter)
                writer.writeheader()
                writer.writerows(raw_rows)

        # 3. Aggregieren & Vermitteln
        aggregation = self.aggregate_materials_by_module(
            records=filtered_records,
            target_modules=modules,
            max_deviation_percent=max_deviation_percent
        )

        # 4. Summary CSV speichern (optional)
        if output_summary_csv:
            summary_fields = [
                "Suchbegriffe",
                "Modul",
                "GWP_Vermittelt",
                "Einheit",
                "Innerhalb_15_Prozent",
                "Abweichung_Prozent",
                "Anzahl_Datensaetze",
                "GWP_Min",
                "GWP_Max",
                "Status",
                "Beruecksichtigte_Baustoffe"
            ]
            with open(output_summary_csv, "w", encoding="utf-8-sig", newline="") as fout:
                writer = csv.DictWriter(fout, fieldnames=summary_fields, delimiter=";")
                writer.writeheader()
                for mod, data in aggregation.items():
                    writer.writerow({
                        "Suchbegriffe": ", ".join(keywords),
                        "Modul": mod,
                        "GWP_Vermittelt": _format_german_float(data["mean_gwp"]) if data["mean_gwp"] is not None else "",
                        "Einheit": data["unit"],
                        "Innerhalb_15_Prozent": "Ja" if data["within_tolerance"] else "Nein",
                        "Abweichung_Prozent": _format_german_float(data["deviation_percent"], 1),
                        "Anzahl_Datensaetze": data["count"],
                        "GWP_Min": _format_german_float(data["min_gwp"]) if data["min_gwp"] is not None else "",
                        "GWP_Max": _format_german_float(data["max_gwp"]) if data["max_gwp"] is not None else "",
                        "Status": data["status"],
                        "Beruecksichtigte_Baustoffe": "; ".join(data.get("material_names", []))
                    })

        return filtered_records, aggregation
