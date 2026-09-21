"""
Extraction Engine: Flask-freie Kernlogik für die IFC-Extraktion.

Enthält die Funktionen `_extract_rows` und `_build_material_summary`,
die sowohl von der Flask-Web-App als auch von der Streamlit-App genutzt werden.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .csv_export import CSVExporter
from .ifc_parser import IfcParser
from .quantity_extractor import QuantityExtractor


def _build_material_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    material_summary: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("Material_Name_IFC") or row.get("Material_Name") or "Unknown",
            row.get("Material_Classification_System") or "",
            row.get("OmniClass_Code") or row.get("Material_Classification_Code") or "",
        )
        if key not in material_summary:
            material_summary[key] = {
                "Material_Name": key[0],
                "Material_Classification_System": key[1],
                "Material_Classification_Code": key[2],
                "Classification_Status": row.get("Classification_Status", "needs_confirmation"),
                "Element_Count": 0,
                "Total_Quantity_Value": 0.0,
                "Quantity_Unit": row.get("Quantity_Unit", "m3"),
                "_elements": set(),
            }
        elem_id = row.get("Bauteil_GUID") or row.get("Element_GUID")
        if elem_id:
            material_summary[key]["_elements"].add(elem_id)
        material_summary[key]["Total_Quantity_Value"] += float(row.get("Volumen_m3") or row.get("Quantity_Value") or 0)
    summary_rows = []
    for row in material_summary.values():
        row["Element_Count"] = len(row.pop("_elements"))
        row["Total_Quantity_Value"] = round(row["Total_Quantity_Value"], 6)
        summary_rows.append(row)
    return summary_rows


def _extract_rows(ifc_path: Path) -> list[dict[str, Any]]:
    parser = IfcParser(ifc_path)
    exporter = CSVExporter()
    elements = parser.parse_all_elements()

    # Identify parent GUIDs so we don't double count container/parent elements
    # if their children are already exported individually.
    parent_guids_with_children = {e.parent_guid for e in elements if e.parent_guid}

    for element in elements:
        # If element is an aggregate parent container with sub-elements that are also extracted,
        # and has no explicit layer breakdown or own distinct materials, skip to avoid double counting.
        if element.has_sub_elements and element.ifc_guid in parent_guids_with_children:
            # If it has no own direct materials or it is a pure container, skip
            if not element.material_layers and not element.materials:
                continue

        # Determine element area: NetSideArea, GrossSideArea, or Area
        area_obj = element.quantities.get("NetSideArea") or element.quantities.get("GrossSideArea") or element.quantities.get("Area")
        element_area = area_obj.value if area_obj else None
        
        # 1. Layered element (e.g. wall with composite layer set)
        if element.material_layers:
            for index, layer in enumerate(element.material_layers, 1):
                # Check if layer thickness is 0 and can be resolved from complex quantities
                layer_thickness = layer.thickness
                if not layer_thickness or layer_thickness <= 0:
                    for comp_name, comp_dict in element.complex_layer_quantities.items():
                        if comp_name.lower() in layer.material.name.lower() or layer.material.name.lower() in comp_name.lower():
                            layer_thickness = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length") or 0.0
                            break

                volume = None
                vol_source = "None"
                if element_area and layer_thickness and layer_thickness > 0:
                    volume = QuantityExtractor.calculate_volume_from_layers({layer.material.name: layer_thickness}, element_area).get(layer.material.name, 0)
                    vol_source = "Calculated_Fallback_AxD"
                else:
                    gross_vol = QuantityExtractor.extract_volume_from_quantities(element.quantities)
                    total_thickness = sum(l.thickness for l in element.material_layers)
                    if gross_vol and total_thickness > 0 and layer_thickness > 0:
                        volume = gross_vol * (layer_thickness / total_thickness)
                        vol_source = "Calculated_ThicknessRatio"
                    elif gross_vol:
                        volume = gross_vol / len(element.material_layers)
                        vol_source = "Calculated_VolumeShare"

                exporter.add_raw_layer(
                    element_id=element.ifc_id,
                    element_guid=element.ifc_guid,
                    element_type=element.element_type,
                    element_name=element.element_name,
                    layer_index=index,
                    material_name=layer.material.name,
                    material_classification=layer.material.classification_ref,
                    material_classification_system=layer.material.classification_system or element.element_classification_system,
                    material_classification_code=layer.material.classification_code or element.element_classification_code,
                    layer_thickness=layer_thickness,
                    element_area=element_area or 0.0,
                    volume_per_layer=volume or 0.0,
                    material_density=layer.material.density,
                    mass_kg=volume * layer.material.density if (volume and layer.material.density) else None,
                    material_composition="Layered composite material",
                    type_name=element.type_name,
                    omniclass_code=layer.material.classification_code or element.element_classification_code,
                    quantity_source=vol_source,
                    constituent_name=layer.material.constituent_name,
                )
        # 2. Single material / constituent elements
        elif element.materials:
            volume = QuantityExtractor.extract_volume_from_quantities(element.quantities)
            num_materials = len(element.materials)

            # Check if materials have constituent fractions defined (e.g. 0.04257778)
            has_fractions = any(m.fraction is not None for m in element.materials)

            # Check total element thickness if available (e.g. Width: 500 mm)
            element_width = None
            if "Width" in element.quantities:
                element_width = element.quantities["Width"].value

            # Prepare list of complex layer quantities ordered by index/occurrence if available
            complex_q_list = list(element.complex_layer_quantities.items())

            for index, material in enumerate(element.materials, 1):
                vol_source = "Explicit" if volume else "None"
                vol_per_mat = None
                mat_fraction = material.fraction
                mat_thickness_mm = None

                # 1. Try matching complex layer quantity by name or keyword
                for comp_name, comp_dict in element.complex_layer_quantities.items():
                    c_low = comp_name.lower()
                    m_low = material.name.lower()
                    if c_low in m_low or m_low in c_low:
                        mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                        break
                    # Fuzzy match words (e.g. 'Gipskarton' matches 'Gypsum Board MT' / 'Gipskartonplatte', 'Dampfsperre' matches 'Vapor Barrier MT')
                    if any(w in m_low or w in c_low for w in ["gips", "gypsum", "dampf", "vapor", "dämm", "insul", "putz", "plaster", "kalk", "lime", "stein", "brick", "clay", "lehm", "beton", "concrete", "holz", "timber", "wood"]):
                        # Check specific keywords
                        if ("gips" in c_low or "gypsum" in c_low) and ("gips" in m_low or "gypsum" in m_low):
                            mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                            break
                        if ("dampf" in c_low or "vapor" in c_low) and ("dampf" in m_low or "vapor" in m_low):
                            mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                            break
                        if ("dämm" in c_low or "insul" in c_low) and ("dämm" in m_low or "insul" in m_low):
                            mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                            break
                        if ("putz" in c_low or "plaster" in c_low) and ("putz" in m_low or "plaster" in m_low):
                            mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                            break
                        if ("lehm" in c_low or "clay" in c_low) and ("lehm" in m_low or "clay" in m_low):
                            mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                            break

                # 2. If no name match, check 1:1 positional match with IfcPhysicalComplexQuantity
                if mat_thickness_mm is None and len(complex_q_list) == len(element.materials):
                    comp_name, comp_dict = complex_q_list[index - 1]
                    mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")

                # Calculate volume and determine volume source
                if mat_thickness_mm and element_area and element_area > 0:
                    # User requirement: Layer thickness and volume directly from thickness properties
                    vol_per_mat = (mat_thickness_mm / 1000.0) * element_area
                    vol_source = "Calculated_Fallback_AxD"
                elif volume is not None:
                    if mat_fraction is not None:
                        # Material specifies its exact percentage / fraction of the total volume
                        vol_per_mat = volume * mat_fraction
                        vol_source = "Calculated_ConstituentFraction"
                    elif has_fractions:
                        # If other materials have fractions, calculate remainder
                        known_fractions = sum(m.fraction for m in element.materials if m.fraction is not None)
                        unspecified_count = sum(1 for m in element.materials if m.fraction is None)
                        remaining_fraction = max(0.0, 1.0 - known_fractions)
                        vol_per_mat = volume * (remaining_fraction / unspecified_count)
                        vol_source = "Calculated_ConstituentFractionRemainder"
                    elif num_materials > 1:
                        # Split equally among constituents
                        vol_per_mat = volume / num_materials
                        vol_source = "Calculated_VolumeShare"
                    else:
                        vol_per_mat = volume
                        vol_source = "Explicit"

                # If thickness not directly found, calculate thickness from fraction or volume & area
                if mat_thickness_mm is None:
                    if mat_fraction is not None and element_width is not None and element_width > 0:
                        mat_thickness_mm = element_width * mat_fraction
                    elif vol_per_mat and element_area and element_area > 0:
                        mat_thickness_mm = (vol_per_mat / element_area) * 1000.0
                    elif element_width and num_materials == 1:
                        mat_thickness_mm = element_width

                exporter.add_raw_element(
                    element_id=element.ifc_id,
                    element_guid=element.ifc_guid,
                    element_type=element.element_type,
                    element_name=element.element_name,
                    material_name=material.name,
                    material_classification=material.classification_ref,
                    material_classification_system=material.classification_system or element.element_classification_system,
                    material_classification_code=material.classification_code or element.element_classification_code,
                    quantity_value=vol_per_mat or 0.0,
                    quantity_unit="m3",
                    quantity_source=vol_source,
                    material_density=material.density,
                    mass_kg=vol_per_mat * material.density if (vol_per_mat and material.density) else None,
                    is_layered=False,
                    material_composition="Single material" if num_materials == 1 else "Constituent set",
                    type_name=element.type_name,
                    omniclass_code=material.classification_code or element.element_classification_code,
                    element_area=element_area,
                    layer_thickness_mm=mat_thickness_mm,
                    layer_index=index,
                    constituent_name=material.constituent_name,
                )
        # 3. Element with quantities but no explicit material association
        elif element.quantities:
            volume = QuantityExtractor.extract_volume_from_quantities(element.quantities)
            if volume:
                exporter.add_raw_element(
                    element_id=element.ifc_id,
                    element_guid=element.ifc_guid,
                    element_type=element.element_type,
                    element_name=element.element_name,
                    material_name="Unspecified",
                    material_classification=None,
                    material_classification_system=element.element_classification_system,
                    material_classification_code=element.element_classification_code,
                    quantity_value=volume,
                    quantity_unit="m3",
                    quantity_source="Explicit",
                    material_density=None,
                    mass_kg=None,
                    is_layered=False,
                    material_composition="Unknown",
                    type_name=element.type_name,
                    omniclass_code=element.element_classification_code,
                )

    for row in exporter.data:
        has_classification = bool(
            row.get("Material_Classification_System")
            and row.get("Material_Classification_Code")
        ) or bool(row.get("OmniClass_Code"))
        row["Classification_Status"] = "provided" if has_classification else "needs_confirmation"
    return exporter.data