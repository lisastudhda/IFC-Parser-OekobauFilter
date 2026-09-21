"""Streamlit Web Application for IFC & Ökobaudat LCA Analysis."""

import io
import tempfile
import sys
from pathlib import Path
import pandas as pd
import streamlit as st

# Projekt-Quellcode-Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ifc_lca_analysis.web_app import _extract_rows, _build_material_summary
from ifc_lca_analysis.oekobaudat_processor import OekobaudatProcessor, _format_german_float


st.set_page_config(
    page_title="IFC & Ökobaudat LCA Tool",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🏗️ IFC & Ökobaudat LCA Tool")
st.markdown("Extrahiere Baustoffe und Schichten aus IFC-Dateien (mit echtem **IfcOpenShell**) und filtere große **Ökobaudat-Datenbanken**.")

tab1, tab2 = st.tabs(["1. 🏢 IFC Material-Extraktion", "2. 📊 Ökobaudat Filter & Mittelwerte"])

# =========================================================
# TAB 1: IFC MATERIAL-EXTRAKTION
# =========================================================
with tab1:
    st.subheader("IFC-Datei analysieren")
    uploaded_ifc = st.file_uploader("Wähle eine IFC-Datei aus (IFC2x3 & IFC4, z. B. aus Vectorworks, Revit, ArchiCAD)", type=["ifc", "txt"])

    if uploaded_ifc is not None:
        with st.spinner("Analysiere IFC mit IfcOpenShell..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
                tmp.write(uploaded_ifc.getvalue())
                tmp_path = Path(tmp.name)

            try:
                rows_data = _extract_rows(tmp_path)
                material_summary = _build_material_summary(rows_data)
                
                # Metriken anzeigen
                col1, col2, col3, col4 = st.columns(4)
                total_elements = len(set(r.get("Bauteil_GUID") or r.get("Element_GUID") for r in rows_data))
                total_vol = sum(float(r.get("Volumen_m3") or r.get("Quantity_Value") or 0.0) for r in rows_data)
                
                col1.metric("Bauteile", total_elements)
                col2.metric("Schichten / Zeilen", len(rows_data))
                col3.metric("Eindeutige Materialien", len(material_summary))
                col4.metric("Gesamtvolumen", f"{total_vol:,.2f} m³".replace(",", "X").replace(".", ",").replace("X", "."))

                st.markdown("---")
                
                # Ansichts-Auswahl
                view_mode = st.radio("Ansicht wählen:", ["Detail pro Schicht", "Materialsummen"], horizontal=True)

                if view_mode == "Detail pro Schicht":
                    df_detail = pd.DataFrame(rows_data)
                    cols_to_show = [
                        "Bauteil_GUID", "IfcType", "Wandtyp_Name", "Schicht_Index",
                        "Material_Name_IFC", "Schichtdicke_m", "Fläche_m2",
                        "Volumen_m3", "Volumen_Ermittlung", "OmniClass_Code"
                    ]
                    existing_cols = [c for c in cols_to_show if c in df_detail.columns]
                    df_display = df_detail[existing_cols]
                    st.dataframe(df_display, use_container_width=True, height=400)

                    # CSV Export
                    csv_buf = io.StringIO()
                    df_display.to_csv(csv_buf, sep=";", index=False)
                    st.download_button(
                        label="⬇ Schichtendetail als CSV herunterladen",
                        data=csv_buf.getvalue(),
                        file_name=f"{uploaded_ifc.name.rsplit('.', 1)[0]}_schichten.csv",
                        mime="text/csv"
                    )

                else:
                    df_mat = pd.DataFrame(material_summary)
                    cols_to_show = [
                        "Material_Name", "Material_Classification_System",
                        "Material_Classification_Code", "Classification_Status",
                        "Element_Count", "Total_Quantity_Value", "Quantity_Unit"
                    ]
                    existing_cols = [c for c in cols_to_show if c in df_mat.columns]
                    df_display = df_mat[existing_cols]
                    st.dataframe(df_display, use_container_width=True, height=400)

                    # CSV Export
                    csv_buf = io.StringIO()
                    df_display.to_csv(csv_buf, sep=";", index=False)
                    st.download_button(
                        label="⬇ Materialsummen als CSV herunterladen",
                        data=csv_buf.getvalue(),
                        file_name=f"{uploaded_ifc.name.rsplit('.', 1)[0]}_material_summary.csv",
                        mime="text/csv"
                    )

            except Exception as e:
                st.error(f"Fehler beim Parsen der IFC-Datei: {e}")
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()


# =========================================================
# TAB 2: ÖKOBAUDAT FILTER & MITTELWERTE
# =========================================================
with tab2:
    st.subheader("Ökobaudat-Datenbank filtern & Mittelwerte bilden")
    uploaded_obd = st.file_uploader("Lade eine Ökobaudat-CSV hoch (z. B. OEKOBAU.DAT_2020-II.csv)", type=["csv"])

    if uploaded_obd is not None:
        with st.expander("⚙️ Filter-Einstellungen", expanded=True):
            col_f1, col_f2, col_f3 = st.columns([2, 1, 2])
            keywords_input = col_f1.text_input("Suchbegriffe (kommagetrennt)", value="Kalksandstein")
            tolerance_input = col_f2.number_input("Toleranzgrenze (%)", min_value=1.0, max_value=100.0, value=15.0, step=1.0)
            modules_input = col_f3.text_input("Lebenszyklus-Module", value="A1-A3, A4, A5")

        if st.button("Filtern & Berechnen", type="primary"):
            with st.spinner("Filtere Ökobaudat-Daten..."):
                try:
                    content = uploaded_obd.getvalue().decode("utf-8-sig", errors="replace")
                    processor = OekobaudatProcessor(delimiter=";", encoding="utf-8-sig")
                    
                    keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]
                    modules = [m.strip() for m in modules_input.split(",") if m.strip()]
                    
                    records = []
                    raw_rows = []
                    
                    for record, raw in processor.stream_filter(io.StringIO(content), keywords=keywords):
                        records.append(record)
                        raw_rows.append(raw)
                    
                    if not records:
                        st.warning(f"Keine Datensätze für '{keywords_input}' gefunden.")
                    else:
                        st.success(f"{len(records)} Zeilen für '{keywords_input}' gefunden!")
                        
                        agg_results = processor.aggregate_materials_by_module(
                            records=records,
                            target_modules=modules,
                            max_deviation_percent=tolerance_input
                        )
                        
                        # Aggregations-Tabelle aufbereiten
                        agg_table = []
                        for mod, res in agg_results.items():
                            agg_table.append({
                                "Modul": mod,
                                "GWP Vermittelt": _format_german_float(res["mean_gwp"]) if res["mean_gwp"] is not None else "—",
                                "Einheit": res["unit"] or "kg",
                                "Innerhalb 15%": "✓ Ja" if res["within_tolerance"] else "✗ Nein",
                                "Abweichung": f"{res['deviation_percent']:.1f}%",
                                "Datensätze": res["count"],
                                "GWP Min": _format_german_float(res["min_gwp"]) if res["min_gwp"] is not None else "—",
                                "GWP Max": _format_german_float(res["max_gwp"]) if res["max_gwp"] is not None else "—",
                                "Status": res["status"]
                            })
                        
                        df_agg = pd.DataFrame(agg_table)
                        
                        st.markdown("### 📊 Vermittelte GWP-Werte nach Modulen")
                        st.dataframe(df_agg, use_container_width=True)
                        
                        # CSV Export Summary
                        csv_agg_buf = io.StringIO()
                        df_agg.to_csv(csv_agg_buf, sep=";", index=False)
                        st.download_button(
                            label="⬇ Summary als CSV herunterladen",
                            data=csv_agg_buf.getvalue(),
                            file_name=f"oekobaudat_{keywords_input}_summary.csv",
                            mime="text/csv"
                        )
                        
                        st.markdown("### 📋 Gefilterte Rohdatensätze")
                        df_raw = pd.DataFrame(raw_rows)
                        st.dataframe(df_raw.head(200), use_container_width=True, height=350)
                        
                        csv_raw_buf = io.StringIO()
                        df_raw.to_csv(csv_raw_buf, sep=";", index=False)
                        st.download_button(
                            label="⬇ Gefilterte Rohdaten als CSV herunterladen",
                            data=csv_raw_buf.getvalue(),
                            file_name=f"oekobaudat_{keywords_input}_rohdaten.csv",
                            mime="text/csv"
                        )
                        
                except Exception as e:
                    st.error(f"Fehler bei der Ökobaudat-Verarbeitung: {e}")
