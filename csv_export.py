"""
CSV Export: Export LCA analysis results to CSV format.

Columns:
- Element metadata (ID, GUID, Type, Name)
- Material information (Name, Classification, Ökobaudat mapping)
- Quantities (Value, Unit, Source)
- Environmental impact (GWP A1-A3, GWP C1-C4, EPD)
- Timestamp
"""

from typing import List, Dict, Any, Optional
from pathlib import Path
import logging
from datetime import datetime

try:
    import pandas as pd
except ImportError:
    raise ImportError("pandas required: pip install pandas")

logger = logging.getLogger(__name__)


class CSVExporter:
    """Export IFC data to CSV in phases.
    
    Phase 1: Raw IFC extraction (materials, quantities)
    Phase 2: Ökobaudat mapping and impact calculation (separate workflow)
    """

    def __init__(self, output_path: str | Path = "ifc_extraction.csv"):
        """
        Initialize exporter.
        
        Args:
            output_path: Output CSV file path (Phase 1)
        """
        self.output_path = Path(output_path)
        self.data = []

    def add_raw_element(
        self,
        element_id: str,
        element_guid: str,
        element_type: str,
        element_name: str,
        material_name: str,
        material_classification: Optional[str],
        quantity_value: float,
        quantity_unit: str,
        quantity_source: str,
        material_classification_system: Optional[str] = None,
        material_classification_code: Optional[str] = None,
        material_density: Optional[float] = None,
        mass_kg: Optional[float] = None,
        obd_class: Optional[str] = None,
        obd_group: Optional[str] = None,
        epd_id: Optional[str] = None,
        length_m: Optional[float] = None,
        width_m: Optional[float] = None,
        height_m: Optional[float] = None,
        is_layered: bool = False,
        material_composition: Optional[str] = None,
        type_name: Optional[str] = None,
        omniclass_code: Optional[str] = None,
        element_area: Optional[float] = None,
        layer_thickness_mm: Optional[float] = None,
        layer_index: int = 1,
        constituent_name: Optional[str] = None,
    ) -> None:
        """
        Add raw IFC element data (Phase 1 - extraction only).
        """
        omni = omniclass_code
        if not omni:
            if material_classification_system and "omni" in material_classification_system.lower():
                omni = material_classification_code or material_classification
            elif material_classification and any(c.isdigit() for c in material_classification):
                omni = material_classification

        thickness_m = round(layer_thickness_mm / 1000.0, 4) if (layer_thickness_mm is not None and layer_thickness_mm > 0) else None

        wandtyp_name = type_name or element_name

        row = {
            "Element_GUID": element_guid,
            "Element_Name": wandtyp_name,
            "Material_Name": material_name,
            "Quantity_Value": round(quantity_value, 4) if quantity_value is not None else 0.0,
            "Quantity_Unit": quantity_unit or "m³",
            # Additional metadata & compatibility fields
            "Bauteil_GUID": element_guid,
            "IfcType": element_type,
            "Wandtyp_Name": wandtyp_name,
            "Schicht_Index": layer_index,
            "Material_Name_IFC": material_name,
            "Schichtdicke_m": thickness_m,
            "Constituent_Function": constituent_name or "",
            "Fläche_m2": round(element_area, 4) if (element_area is not None and element_area > 0) else None,
            "Volumen_m3": round(quantity_value, 4) if quantity_value is not None else None,
            "Volumen_Ermittlung": quantity_source,
            "OmniClass_Code": omni or "",
            "Element_ID": element_id,
            "Element_Type": element_type,
            "Material_Classification": material_classification,
            "Material_Classification_System": material_classification_system,
            "Material_Classification_Code": material_classification_code or material_classification,
            "Quantity_Source": quantity_source,
            "Material_Density_kg_m3": material_density,
            "Mass_kg": mass_kg,
            "OBD_Class": obd_class,
            "OBD_Group": obd_group,
            "EPD_ID": epd_id,
            "Length_m": length_m,
            "Width_m": width_m,
            "Height_m": height_m,
            "Is_Layered": is_layered,
            "Material_Composition": material_composition,
            "Oekobaudat_ID": "",  # To be filled in by mapping step
            "Oekobaudat_Name": "",  # To be filled in by mapping step
            "Timestamp": datetime.now().isoformat(),
        }
        self.data.append(row)

    def add_raw_layer(
        self,
        element_id: str,
        element_guid: str,
        element_type: str,
        element_name: str,
        layer_index: int,
        material_name: str,
        material_classification: Optional[str],
        layer_thickness: float,
        element_area: float,
        volume_per_layer: float,
        material_classification_system: Optional[str] = None,
        material_classification_code: Optional[str] = None,
        material_density: Optional[float] = None,
        mass_kg: Optional[float] = None,
        obd_class: Optional[str] = None,
        obd_group: Optional[str] = None,
        epd_id: Optional[str] = None,
        length_m: Optional[float] = None,
        width_m: Optional[float] = None,
        height_m: Optional[float] = None,
        material_composition: Optional[str] = None,
        type_name: Optional[str] = None,
        omniclass_code: Optional[str] = None,
        quantity_source: str = "Calculated_Fallback_AxD",
        constituent_name: Optional[str] = None,
    ) -> None:
        """
        Add raw layered element data (Phase 1 - extraction only).
        """
        omni = omniclass_code
        if not omni:
            if material_classification_system and "omni" in material_classification_system.lower():
                omni = material_classification_code or material_classification
            elif material_classification and any(c.isdigit() for c in material_classification):
                omni = material_classification

        layer_thickness_m = round(layer_thickness / 1000.0, 4) if (layer_thickness is not None and layer_thickness > 0) else None

        wandtyp_name = type_name or element_name

        row = {
            "Element_GUID": element_guid,
            "Element_Name": wandtyp_name,
            "Material_Name": material_name,
            "Quantity_Value": round(volume_per_layer, 4) if volume_per_layer is not None else 0.0,
            "Quantity_Unit": "m³",
            # Additional metadata & compatibility fields
            "Bauteil_GUID": element_guid,
            "IfcType": element_type,
            "Wandtyp_Name": wandtyp_name,
            "Schicht_Index": layer_index,
            "Material_Name_IFC": material_name,
            "Schichtdicke_m": layer_thickness_m,
            "Constituent_Function": constituent_name or "",
            "Fläche_m2": round(element_area, 4) if (element_area is not None and element_area > 0) else None,
            "Volumen_m3": round(volume_per_layer, 4) if volume_per_layer is not None else None,
            "Volumen_Ermittlung": quantity_source,
            "OmniClass_Code": omni or "",
            "Element_ID": element_id,
            "Element_Type": element_type,
            "Layer_Index": layer_index,
            "Material_Classification": material_classification,
            "Material_Classification_System": material_classification_system,
            "Material_Classification_Code": material_classification_code or material_classification,
            "Quantity_Source": quantity_source,
            "Layer_Thickness_mm": layer_thickness,
            "Element_Area_m2": element_area,
            "Material_Density_kg_m3": material_density,
            "Mass_kg": mass_kg,
            "OBD_Class": obd_class,
            "OBD_Group": obd_group,
            "EPD_ID": epd_id,
            "Length_m": length_m,
            "Width_m": width_m,
            "Height_m": height_m,
            "Is_Layered": True,
            "Material_Composition": material_composition,
            "Oekobaudat_ID": "",  # To be filled in by mapping step
            "Oekobaudat_Name": "",  # To be filled in by mapping step
            "Timestamp": datetime.now().isoformat(),
        }
        self.data.append(row)

    def export(self, columns: Optional[List[str]] = None) -> None:
        """
        Export Phase 1 data (raw IFC extraction) to CSV.
        
        Raises:
            ValueError: If no data to export
        """
        if not self.data:
            raise ValueError("No data to export")
        
        df = pd.DataFrame(self.data)
        
        # Sort by element GUID and material name
        sort_col = "Bauteil_GUID" if "Bauteil_GUID" in df.columns else "Element_GUID"
        mat_col = "Material_Name_IFC" if "Material_Name_IFC" in df.columns else "Material_Name"
        df = df.sort_values([sort_col, mat_col])
        
        if columns:
            existing_cols = [c for c in columns if c in df.columns]
            df = df[existing_cols]

        # Export to CSV
        df.to_csv(self.output_path, index=False, encoding="utf-8-sig")
        logger.info(f"Exported {len(self.data)} rows to {self.output_path}")

    def to_csv_string(self, columns: Optional[List[str]] = None) -> str:
        """Export Phase 1 data to CSV string."""
        if not self.data:
            return ""
        df = pd.DataFrame(self.data)
        sort_cols = [c for c in ["Bauteil_GUID", "Element_GUID", "Material_Name_IFC", "Material_Name"] if c in df.columns]
        if sort_cols:
            df = df.sort_values(sort_cols[:2])
        if columns:
            existing_cols = [c for c in columns if c in df.columns]
            df = df[existing_cols]
        return df.to_csv(index=False, encoding="utf-8-sig")

    def export_summary(self, summary_path: Optional[str | Path] = None) -> None:
        """
        Export Phase 1 summary (raw extraction statistics).
        
        Args:
            summary_path: Path for summary file (optional)
        """
        if not self.data:
            logger.warning("No data for summary")
            return
        
        df = pd.DataFrame(self.data)
        summary_path = Path(summary_path) if summary_path else self.output_path.with_stem(f"{self.output_path.stem}_summary")
        
        summary_stats = {
            "Total_Elements": df["Element_ID"].nunique(),
            "Total_Materials": df["Material_Name"].nunique(),
            "Total_Volume_m3": df["Quantity_Value"].sum(),
            "Materials_with_Classification": df[df["Material_Classification"].notna()].shape[0],
            "Materials_without_Classification": df[df["Material_Classification"].isna()].shape[0],
            "Extraction_Date": datetime.now().isoformat(),
        }
        
        summary_df = pd.DataFrame([summary_stats])
        summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
        logger.info(f"Exported summary to {summary_path}")

    def get_dataframe(self) -> pd.DataFrame:
        """Get results as pandas DataFrame."""
        return pd.DataFrame(self.data)
