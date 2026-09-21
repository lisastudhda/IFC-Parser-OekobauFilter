"""
CLI: Command-line interface for IFC-LCA-Analysis.

Two-phase workflow:
Phase 1: Extract raw IFC data (materials, quantities) to CSV
Phase 2: Enrich CSV with Ökobaudat mappings and impact data

Usage:
    ifc-lca extract model.ifc --output extraction.csv
    # Then fill Oekobaudat_ID and Oekobaudat_Name columns
    # Then import into dashboard system
"""

from pathlib import Path
from typing import List, Optional
import logging

try:
    import typer
except ImportError:
    raise ImportError("typer required: pip install typer")

from .ifc_parser import IfcParser
from .quantity_extractor import QuantityExtractor
from .csv_export import CSVExporter
from .oekobaudat_processor import OekobaudatProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = typer.Typer(help="IFC-LCA-Analysis: Extract LCA data from IFC models")


@app.command()
def extract(
    ifc_file: Path = typer.Argument(..., help="Path to IFC file"),
    output: Path = typer.Option("ifc_extraction.csv", help="Output CSV file"),
) -> None:
    """
    Phase 1: Extract raw IFC data (materials, quantities).
    
    Output CSV contains all material and quantity data from the IFC model
    with empty Oekobaudat_ID and Oekobaudat_Name columns for Phase 2.
    
    Example:
        ifc-lca extract model.ifc --output extraction.csv
    """
    try:
        logger.info(f"Extracting IFC data from {ifc_file}")
        
        # Parse IFC
        parser = IfcParser(ifc_file)
        elements = parser.parse_all_elements()
        logger.info(f"Extracted {len(elements)} elements")
        
        # Initialize exporter (Phase 1 only - raw extraction)
        exporter = CSVExporter(output)
        
        # Parent GUID detection to avoid container double counting
        parent_guids_with_children = {e.parent_guid for e in elements if e.parent_guid}

        # Process each element
        for elem in elements:
            # Skip pure container elements whose sub-elements are extracted separately
            if elem.has_sub_elements and elem.ifc_guid in parent_guids_with_children:
                if not elem.material_layers and not elem.materials:
                    continue

            # Extract element dimensions if available
            length = elem.properties.get("Length") if elem.properties else None
            width = elem.properties.get("Width") if elem.properties else None
            height = elem.properties.get("Height") if elem.properties else None
            
            # Get element area for volume calculations
            element_area = None
            if "NetSideArea" in elem.quantities:
                element_area = elem.quantities["NetSideArea"].value

            # Export layered materials if present (preferred for composite elements)
            if elem.material_layers:
                gross_vol = QuantityExtractor.extract_volume_from_quantities(elem.quantities)
                total_thickness = sum(l.thickness for l in elem.material_layers)

                for layer_idx, layer in enumerate(elem.material_layers, 1):
                    thickness = layer.thickness
                    if not thickness or thickness <= 0:
                        for comp_name, comp_dict in elem.complex_layer_quantities.items():
                            if comp_name.lower() in layer.material.name.lower() or layer.material.name.lower() in comp_name.lower():
                                thickness = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length") or 0.0
                                break

                    volume_layer = 0.0
                    vol_source = "None"
                    
                    if element_area and thickness and thickness > 0:
                        volume_layer = QuantityExtractor.calculate_volume_from_layers(
                            {layer.material.name: thickness},
                            element_area
                        ).get(layer.material.name, 0)
                        vol_source = "Calculated_Fallback_AxD"
                    elif gross_vol and total_thickness > 0 and thickness > 0:
                        volume_layer = gross_vol * (thickness / total_thickness)
                        vol_source = "Calculated_ThicknessRatio"
                    elif gross_vol:
                        volume_layer = gross_vol / len(elem.material_layers)
                        vol_source = "Calculated_VolumeShare"
                        
                    # Calculate mass for layer
                    mass_kg_layer = None
                    if volume_layer and layer.material.density:
                        mass_kg_layer = volume_layer * layer.material.density
                    
                    # Export raw layer data
                    exporter.add_raw_layer(
                        element_id=elem.ifc_id,
                        element_guid=elem.ifc_guid,
                        element_type=elem.element_type,
                        element_name=elem.element_name,
                        layer_index=layer_idx,
                        material_name=layer.material.name,
                        material_classification=layer.material.classification_ref,
                        material_classification_system=layer.material.classification_system or elem.element_classification_system,
                        material_classification_code=layer.material.classification_code or elem.element_classification_code,
                        layer_thickness=thickness,
                        element_area=element_area or 0.0,
                        volume_per_layer=volume_layer,
                        material_density=layer.material.density,
                        mass_kg=mass_kg_layer,
                        length_m=length,
                        width_m=width,
                        height_m=height,
                        material_composition="Layered composite material",
                        type_name=elem.type_name,
                        omniclass_code=layer.material.classification_code or elem.element_classification_code,
                        quantity_source=vol_source,
                    )
            # Export single materials / constituent sets
            elif elem.materials:
                volume = QuantityExtractor.extract_volume_from_quantities(elem.quantities)
                num_materials = len(elem.materials)
                has_fractions = any(m.fraction is not None for m in elem.materials)
                element_width = elem.quantities.get("Width").value if "Width" in elem.quantities else None

                for index, material in enumerate(elem.materials, 1):
                    vol_source = "Explicit" if volume else "None"
                    vol_per_mat = 0.0
                    mat_thickness_mm = None

                    for comp_name, comp_dict in elem.complex_layer_quantities.items():
                        if comp_name.lower() in material.name.lower() or material.name.lower() in comp_name.lower():
                            mat_thickness_mm = comp_dict.get("Width") or comp_dict.get("Thickness") or comp_dict.get("Length")
                            break

                    if volume is not None:
                        if material.fraction is not None:
                            vol_per_mat = volume * material.fraction
                            vol_source = "Calculated_ConstituentFraction"
                        elif mat_thickness_mm and element_area and element_area > 0:
                            vol_per_mat = (mat_thickness_mm / 1000.0) * element_area
                            vol_source = "Calculated_Fallback_AxD"
                        elif has_fractions:
                            known_fractions = sum(m.fraction for m in elem.materials if m.fraction is not None)
                            unspecified_count = sum(1 for m in elem.materials if m.fraction is None)
                            remaining_fraction = max(0.0, 1.0 - known_fractions)
                            vol_per_mat = volume * (remaining_fraction / unspecified_count)
                            vol_source = "Calculated_ConstituentFractionRemainder"
                        elif num_materials > 1:
                            vol_per_mat = volume / num_materials
                            vol_source = "Calculated_VolumeShare"
                        else:
                            vol_per_mat = volume
                            vol_source = "Explicit"

                    if mat_thickness_mm is None:
                        if material.fraction is not None and element_width is not None and element_width > 0:
                            mat_thickness_mm = element_width * material.fraction
                        elif vol_per_mat and element_area and element_area > 0:
                            mat_thickness_mm = (vol_per_mat / element_area) * 1000.0
                        elif element_width and num_materials == 1:
                            mat_thickness_mm = element_width

                    mass_kg = None
                    if vol_per_mat and material.density:
                        mass_kg = vol_per_mat * material.density
                    
                    exporter.add_raw_element(
                        element_id=elem.ifc_id,
                        element_guid=elem.ifc_guid,
                        element_type=elem.element_type,
                        element_name=elem.element_name,
                        material_name=material.name,
                        material_classification=material.classification_ref,
                        material_classification_system=material.classification_system or elem.element_classification_system,
                        material_classification_code=material.classification_code or elem.element_classification_code,
                        quantity_value=vol_per_mat,
                        quantity_unit="m³",
                        quantity_source=vol_source,
                        material_density=material.density,
                        mass_kg=mass_kg,
                        length_m=length,
                        width_m=width,
                        height_m=height,
                        is_layered=False,
                        material_composition="Single material" if num_materials == 1 else "Constituent set",
                        type_name=elem.type_name,
                        omniclass_code=material.classification_code or elem.element_classification_code,
                        element_area=element_area,
                        layer_thickness_mm=mat_thickness_mm,
                        layer_index=index,
                    )
        
        # Export results
        exporter.export()
        exporter.export_summary()
        
        logger.info(f"Extraction complete. Results exported to {output}")
        typer.echo("")
        typer.echo("✓ Phase 1 complete: IFC data extracted")
        typer.echo(f"  Output: {output}")
        typer.echo("")
        typer.echo("📋 Next steps:")
        typer.echo("  1. Open the CSV file")
        typer.echo("  2. Fill Oekobaudat_ID column (e.g., OB_001, OB_002)")
        typer.echo("     → Use Ökobaudat Live Katalog or your Ökobaudat database")
        typer.echo("  3. Fill Oekobaudat_Name column with dataset names")
        typer.echo("  4. Import enriched CSV into dashboard system for Phase 2 (impact calc)")
        typer.echo("")
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        typer.echo(f"✗ Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def summary(
    csv_file: Path = typer.Argument(..., help="IFC extraction CSV file"),
) -> None:
    """
    View summary of extracted IFC data.
    
    Example:
        ifc-lca summary extraction.csv
    """
    try:
        import pandas as pd
        
        df = pd.read_csv(csv_file)
        
        typer.echo("")
        typer.echo("═" * 60)
        typer.echo(f"IFC Extraction Summary: {csv_file.name}")
        typer.echo("═" * 60)
        typer.echo(f"Total rows: {len(df)}")
        typer.echo(f"Unique elements: {df['Element_GUID'].nunique()}")
        typer.echo(f"Unique materials: {df['Material_Name'].nunique()}")
        typer.echo(f"Total volume: {df['Quantity_Value'].sum():.2f} m³")
        typer.echo("")
        typer.echo("Materials by type:")
        for elem_type in df['Element_Type'].unique():
            materials = df[df['Element_Type'] == elem_type]['Material_Name'].unique()
            typer.echo(f"  {elem_type}: {len(materials)} materials")
        typer.echo("")
        typer.echo("Materials without Ökobaudat mapping:")
        unmapped = df[df['Oekobaudat_ID'].isna() | (df['Oekobaudat_ID'] == '')]
        if len(unmapped) > 0:
            for mat_name in unmapped['Material_Name'].unique():
                count = len(unmapped[unmapped['Material_Name'] == mat_name])
                typer.echo(f"  • {mat_name}: {count} rows")
        typer.echo("")
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        typer.echo(f"✗ Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def filter_obd(
    oekobaudat_csv: Path = typer.Argument(..., help="Path to large Ökobaudat CSV file"),
    keywords: List[str] = typer.Option(..., "--keyword", "-k", help="Search keyword(s), e.g. -k Kalksandstein -k Schaumglas"),
    output: Path = typer.Option("oekobaudat_filtered.csv", "--output", "-o", help="Output path for filtered dataset rows"),
    summary_output: Optional[Path] = typer.Option(None, "--summary", "-s", help="Optional output path for averaged GWP summary CSV"),
    tolerance: float = typer.Option(15.0, "--tolerance", "-t", help="Max allowed deviation percentage for averaging (default: 15%)"),
    modules: List[str] = typer.Option(["A1-A3", "A4", "A5"], "--module", "-m", help="Lifecycle modules to aggregate (default: A1-A3, A4, A5)"),
) -> None:
    """
    Filter large Ökobaudat CSV efficiently by keywords and aggregate GWP values.
    
    Checks if GWP values differ by no more than tolerance (default 15%) across matching materials.
    
    Example:
        ifc-lca filter-obd Oekobaudat.csv -k Kalksandstein -o gefiltert.csv -s summary.csv
    """
    try:
        typer.echo("")
        typer.echo("═" * 60)
        typer.echo(f"Ökobaudat Filtering & Aggregation: {oekobaudat_csv.name}")
        typer.echo("═" * 60)
        typer.echo(f"Keywords: {', '.join(keywords)}")
        typer.echo(f"Tolerance: {tolerance}%")
        typer.echo(f"Modules: {', '.join(modules)}")
        typer.echo("")

        processor = OekobaudatProcessor()
        records, aggregation = processor.filter_and_aggregate_summary(
            input_csv=oekobaudat_csv,
            keywords=keywords,
            modules=modules,
            max_deviation_percent=tolerance,
            output_summary_csv=summary_output,
            output_filtered_csv=output,
        )

        typer.echo(f"✓ Found {len(records)} matching records.")
        typer.echo(f"✓ Filtered raw CSV written to: {output}")
        if summary_output:
            typer.echo(f"✓ Aggregation summary written to: {summary_output}")

        typer.echo("")
        typer.echo("Module Summary (GWPtotal A2):")
        typer.echo("-" * 60)
        for mod, data in aggregation.items():
            status_symbol = "✓" if data["within_tolerance"] else "⚠"
            mean_str = f"{data['mean_gwp']:.6f} {data['unit']}" if data["mean_gwp"] is not None else "N/A"
            typer.echo(f"{status_symbol} Modul {mod:6s}: Mean = {mean_str} | Dev = {data['deviation_percent']:.1f}% | Count = {data['count']} ({data['status']})")
        typer.echo("═" * 60)
        typer.echo("")

    except Exception as e:
        logger.error(f"Error in filter_obd: {e}", exc_info=True)
        typer.echo(f"✗ Error: {e}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
