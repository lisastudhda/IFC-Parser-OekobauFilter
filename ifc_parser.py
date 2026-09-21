"""
IFC Parser: Extract materials, quantities, and element data from IFC files.

Handles:
- IfcRelAssociatesMaterial relationships
- Single materials, layer sets, and constituent materials
- IfcElementQuantity (Qto_*BaseQuantities)
- Geometry fallback for missing quantity data
"""

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from pathlib import Path
import logging

try:
    import ifcopenshell
    from ifcopenshell.util.element import get_pset
except ImportError:
    raise ImportError("ifcopenshell required: pip install ifcopenshell")

logger = logging.getLogger(__name__)


@dataclass
class Material:
    """Represents a single material."""
    name: str
    classification_ref: Optional[str] = None
    classification_system: Optional[str] = None
    classification_code: Optional[str] = None
    fraction: Optional[float] = None  # Fraction / percentage for constituents (0.0 - 1.0)
    density: Optional[float] = None  # kg/m³
    constituent_name: Optional[str] = None  # Name / role of the constituent (e.g. "LoadBearing", "Finishing")
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MaterialLayer:
    """Represents a layer in IfcMaterialLayerSet."""
    material: Material
    thickness: float  # mm


@dataclass
class Quantity:
    """Represents a quantity value."""
    name: str
    value: float
    unit: str
    source: str = "Explicit"  # Explicit, Calculated, Fallback


@dataclass
class ElementData:
    """Represents extracted element data."""
    ifc_id: str
    ifc_guid: str
    element_type: str
    element_name: str
    type_name: Optional[str] = None
    element_classification_system: Optional[str] = None
    element_classification_code: Optional[str] = None
    parent_guid: Optional[str] = None
    has_sub_elements: bool = False
    materials: List[Material] = field(default_factory=list)
    material_layers: List[MaterialLayer] = field(default_factory=list)
    complex_layer_quantities: Dict[str, Dict[str, float]] = field(default_factory=dict)
    quantities: Dict[str, Quantity] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)


class IfcParser:
    """Parse IFC files and extract material and quantity data."""

    def __init__(self, ifc_file_path: str | Path):
        """
        Initialize IFC parser.
        
        Args:
            ifc_file_path: Path to IFC file
            
        Raises:
            FileNotFoundError: If file does not exist
        """
        self.file_path = Path(ifc_file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"IFC file not found: {self.file_path}")
        
        self.ifc = ifcopenshell.open(str(self.file_path))
        logger.info(f"Loaded IFC file: {self.file_path}")

    def parse_all_elements(self) -> List[ElementData]:
        """
        Parse all elements with materials and quantities.
        
        Returns:
            List of ElementData objects
        """
        elements = []
        
        # Get all relevant element types
        element_types = [
            "IfcWall", "IfcWallStandardCase",
            "IfcSlab", "IfcSlabStandardCase",
            "IfcBeam", "IfcColumn", "IfcFooting", "IfcRoof",
            "IfcDoor", "IfcWindow", "IfcMember", "IfcPlate",
        ]
        
        for elem_type in element_types:
            for elem in self.ifc.by_type(elem_type):
                try:
                    element_data = self._parse_element(elem)
                    if element_data:
                        elements.append(element_data)
                except Exception as e:
                    logger.warning(f"Error parsing {elem.GlobalId}: {e}")
        
        logger.info(f"Parsed {len(elements)} elements")
        return elements

    def _parse_element(self, element: Any) -> Optional[ElementData]:
        """
        Parse a single IFC element.
        
        Args:
            element: IfcElement object
            
        Returns:
            ElementData or None if parsing fails
        """
        try:
            elem_data = ElementData(
                ifc_id=str(element.id()),
                ifc_guid=element.GlobalId,
                element_type=element.is_a(),
                element_name=element.Name or "Unnamed",
            )
            
            # Check for parent / decomposition relationships
            self._extract_decomposition_info(element, elem_data)

            # Extract type object info (e.g. Wandtyp / IfcTypeProduct)
            self._extract_type_info(element, elem_data)

            # Extract element-level classification
            self._extract_element_classification(element, elem_data)

            # Extract materials
            self._extract_materials(element, elem_data)
            
            # Extract quantities
            self._extract_quantities(element, elem_data)
            
            # Extract properties
            self._extract_properties(element, elem_data)

            # Filter out pure 2D annotation / curve objects (e.g. 2D symbol lines exported by Vectorworks as IfcMember)
            # which have no 3D volume or layer data and represent duplicate 2D line representations.
            if self._is_pure_2d_annotation(element, elem_data):
                return None
            
            return elem_data if (elem_data.materials or elem_data.material_layers or elem_data.quantities) else None
            
        except Exception as e:
            logger.error(f"Error parsing element {getattr(element, 'GlobalId', 'unknown')}: {e}")
            return None

    def _is_pure_2d_annotation(self, element: Any, elem_data: ElementData) -> bool:
        """Check if an element is purely a 2D line/annotation representation without physical quantities."""
        if not hasattr(element, "Representation") or not element.Representation:
            return False
        
        rep_types = [
            getattr(rep, "RepresentationType", "") or ""
            for rep in getattr(element.Representation, "Representations", [])
        ]
        
        # If element is only 2D Annotation / Curve and has no volume/area quantities
        is_only_2d_rep = all(t in ("Annotation2D", "Curve2D", "Plan", "Axis", "FootPrint") for t in rep_types if t)
        if is_only_2d_rep and rep_types:
            has_vol = any(
                q.value > 0 for q in elem_data.quantities.values() if "volume" in q.name.lower() or q.unit in ("m³", "m3")
            )
            if not has_vol:
                return True

        return False

    def _extract_decomposition_info(self, element: Any, elem_data: ElementData) -> None:
        """Extract parent/child relationships (IfcRelAggregates / IfcRelDecomposes / IfcRelNests)."""
        try:
            # Check if this element is a child of another element
            if hasattr(element, "Decomposes"):
                for rel in element.Decomposes:
                    parent = getattr(rel, "RelatingObject", None)
                    if parent and hasattr(parent, "GlobalId"):
                        elem_data.parent_guid = parent.GlobalId
                        break
            if not elem_data.parent_guid and hasattr(element, "Nests"):
                for rel in element.Nests:
                    parent = getattr(rel, "RelatingObject", None)
                    if parent and hasattr(parent, "GlobalId"):
                        elem_data.parent_guid = parent.GlobalId
                        break

            # Check if this element decomposes into sub-elements
            if hasattr(element, "IsDecomposedBy"):
                for rel in element.IsDecomposedBy:
                    parts = getattr(rel, "RelatedObjects", [])
                    if parts:
                        elem_data.has_sub_elements = True
                        break
            if not elem_data.has_sub_elements and hasattr(element, "IsNestedBy"):
                for rel in element.IsNestedBy:
                    parts = getattr(rel, "RelatedObjects", [])
                    if parts:
                        elem_data.has_sub_elements = True
                        break
        except Exception as e:
            logger.debug(f"Error extracting decomposition info for {getattr(element, 'GlobalId', '')}: {e}")

    def _extract_type_info(self, element: Any, elem_data: ElementData) -> None:
        """Extract type product information (e.g. Wandtyp_Name)."""
        try:
            if hasattr(element, "IsTypedBy"):
                for rel in element.IsTypedBy:
                    if rel.is_a("IfcRelDefinesByType"):
                        type_prod = getattr(rel, "RelatingType", None)
                        if type_prod:
                            elem_data.type_name = type_prod.Name or type_prod.is_a()
                            return
            if hasattr(element, "IsDefinedBy"):
                for rel in element.IsDefinedBy:
                    if rel.is_a("IfcRelDefinesByType"):
                        type_prod = getattr(rel, "RelatingType", None)
                        if type_prod:
                            elem_data.type_name = type_prod.Name or type_prod.is_a()
                            return
        except Exception as e:
            logger.debug(f"Error extracting type info for {getattr(element, 'GlobalId', '')}: {e}")

    def _extract_element_classification(self, element: Any, elem_data: ElementData) -> None:
        """Extract classification reference associated with the element."""
        try:
            if hasattr(element, "HasAssociations"):
                for rel in element.HasAssociations:
                    if rel.is_a("IfcRelAssociatesClassification"):
                        class_select = getattr(rel, "RelatingClassification", None)
                        if class_select:
                            if class_select.is_a("IfcClassificationReference"):
                                source = getattr(class_select, "ReferencedSource", None)
                                system = getattr(source, "Name", None) if source else None
                                code = getattr(class_select, "Identification", None) or getattr(class_select, "Name", None)
                                elem_data.element_classification_system = system
                                elem_data.element_classification_code = code
                                return
        except Exception as e:
            logger.debug(f"Error extracting element classification for {getattr(element, 'GlobalId', '')}: {e}")

    def _extract_materials(self, element: Any, elem_data: ElementData) -> None:
        """
        Extract materials from IfcRelAssociatesMaterial.
        
        Handles:
        - IfcMaterial (single)
        - IfcMaterialLayerSet
        - IfcMaterialLayerSetUsage
        - IfcMaterialLayer
        - IfcMaterialConstituentSet
        - IfcMaterialList
        Also checks associated IfcTypeProduct / IfcWallType for material associations.
        """
        # 1. Check direct material associations on the element
        self._find_and_parse_material_associations(element, elem_data)

        # 2. If no materials/layers found on instance, check its Type Object (e.g. IfcWallType)
        if not elem_data.materials and not elem_data.material_layers:
            type_obj = None
            if hasattr(element, "IsTypedBy"):
                for rel in element.IsTypedBy:
                    if rel.is_a("IfcRelDefinesByType"):
                        type_obj = getattr(rel, "RelatingType", None)
                        if type_obj:
                            break
            if not type_obj and hasattr(element, "IsDefinedBy"):
                for rel in element.IsDefinedBy:
                    if rel.is_a("IfcRelDefinesByType"):
                        type_obj = getattr(rel, "RelatingType", None)
                        if type_obj:
                            break
            if type_obj:
                self._find_and_parse_material_associations(type_obj, elem_data)

        # 3. Fallback for elements (e.g. IfcMember, IfcColumn, IfcBeam) with placeholder/default or missing material
        self._apply_element_material_fallback(element, elem_data)

    def _apply_element_material_fallback(self, element: Any, elem_data: ElementData) -> None:
        """Apply heuristics/fallback to determine actual material when IFC only has 'Default' or missing material."""
        has_generic_material = (
            not elem_data.materials and not elem_data.material_layers
        ) or any(
            m.name.strip().lower() in ("default", "material-default", "material default", "unknown", "unspecified")
            for m in elem_data.materials
        )

        if not has_generic_material:
            return

        # Check Name, Description, ObjectType, Tag, and Pset properties of the element
        elem_name = (elem_data.element_name or "").strip()
        elem_desc = (getattr(element, "Description", "") or "").strip()
        elem_obj_type = (getattr(element, "ObjectType", "") or "").strip()
        
        # Also check Pset_MemberCommon / Pset_ColumnCommon / Pset_BeamCommon properties
        pset_props = []
        if hasattr(element, "IsDefinedBy"):
            for rel in element.IsDefinedBy:
                if rel.is_a("IfcRelDefinesByProperties"):
                    pset = rel.RelatingPropertyDefinition
                    if hasattr(pset, "HasProperties"):
                        for p in pset.HasProperties:
                            p_name = getattr(p, "Name", "")
                            p_val = getattr(p, "NominalValue", None)
                            if p_val is not None:
                                pset_props.append(f"{p_name}={p_val}")

        combined_text = " ".join([elem_name, elem_desc, elem_obj_type] + pset_props).lower()

        fallback_material_name = None

        # 1. Direct name / pattern matching (e.g. A01 standard timber stud / KVH in timber construction)
        if "kvh" in combined_text or "konstruktionsvollholz" in combined_text or "bsh" in combined_text or "brettschichtholz" in combined_text:
            fallback_material_name = "Konstruktionsvollholz (KVH)"
        elif "timber" in combined_text or "holz" in combined_text or "wood" in combined_text:
            fallback_material_name = "Konstruktionsvollholz (KVH)"
        elif "steel" in combined_text or "stahl" in combined_text or "ipe" in combined_text or "hea" in combined_text or "heb" in combined_text or "hem" in combined_text:
            fallback_material_name = "Baustahl / Structural Steel"
        elif "beton" in combined_text or "concrete" in combined_text or "c25" in combined_text or "c30" in combined_text:
            fallback_material_name = "Beton / Concrete"
        elif elem_data.element_type in ("IfcMember", "IfcColumn", "IfcBeam"):
            # Typical CAD code: A01, S01, ST01... or framing in timber wall
            # Check if building contains timber/wood materials anywhere in the file
            has_timber_in_model = any(
                "wood" in getattr(m, "Name", "").lower() or "holz" in getattr(m, "Name", "").lower() or "timber" in getattr(m, "Name", "").lower()
                for m in self.ifc.by_type("IfcMaterial")
            )
            if elem_name.upper().startswith("A") or "stud" in combined_text or "frame" in combined_text or "riegel" in combined_text or "stiel" in combined_text or has_timber_in_model:
                fallback_material_name = "Konstruktionsvollholz (KVH)"
            else:
                fallback_material_name = "Baustahl / Structural Steel"

        if fallback_material_name:
            new_mat = Material(name=fallback_material_name)
            if elem_data.materials:
                # Replace generic 'Material-Default'
                for m in elem_data.materials:
                    if m.name.strip().lower() in ("default", "material-default", "material default", "unknown", "unspecified"):
                        m.name = fallback_material_name
            else:
                elem_data.materials.append(new_mat)

    def _find_and_parse_material_associations(self, obj: Any, elem_data: ElementData) -> None:
        """Find and parse IfcRelAssociatesMaterial on an object (instance or type)."""
        if not hasattr(obj, "HasAssociations"):
            return

        for rel in obj.HasAssociations:
            if rel.is_a("IfcRelAssociatesMaterial"):
                material_select = rel.RelatingMaterial
                if not material_select:
                    continue
                
                if material_select.is_a("IfcMaterial"):
                    # Single material
                    material = self._parse_single_material(material_select)
                    elem_data.materials.append(material)
                    
                elif material_select.is_a("IfcMaterialLayerSet"):
                    # Layer set - extract individual layers
                    self._parse_material_layer_set(material_select, elem_data)

                elif material_select.is_a("IfcMaterialLayerSetUsage"):
                    # Layer set usage - unwrap to LayerSet
                    layer_set = getattr(material_select, "ForLayerSet", None)
                    if layer_set:
                        self._parse_material_layer_set(layer_set, elem_data)

                elif material_select.is_a("IfcMaterialLayer"):
                    # Direct single layer association
                    material = self._parse_single_material(material_select.Material)
                    thickness = getattr(material_select, "LayerThickness", 0.0) or 0.0
                    elem_data.material_layers.append(MaterialLayer(material, thickness))
                    
                elif material_select.is_a("IfcMaterialConstituentSet"):
                    # Constituent materials
                    self._parse_material_constituents(material_select, elem_data)

                elif material_select.is_a("IfcMaterialList"):
                    # List of single materials
                    if hasattr(material_select, "Materials"):
                        for mat_item in material_select.Materials:
                            elem_data.materials.append(self._parse_single_material(mat_item))

    def _parse_single_material(self, material: Any) -> Material:
        """Parse IfcMaterial."""
        raw_name = getattr(material, "Name", None) or "Unknown"
        # Standardize generic/placeholder default names
        if raw_name.strip().lower() in ("default", "material-default", "material default", "unknown"):
            raw_name = "Material-Default"

        classification_system, classification_code = self._get_classification_info(material)
        mat = Material(
            name=raw_name,
            classification_ref=classification_code,
            classification_system=classification_system,
            classification_code=classification_code,
            density=self._extract_density_from_material(material),
        )
        mat.properties = self._extract_material_properties(material)
        return mat

    def _parse_material_layer_set(self, layer_set: Any, elem_data: ElementData) -> None:
        """Parse IfcMaterialLayerSet."""
        if not hasattr(layer_set, "MaterialLayers"):
            return
        
        for layer in layer_set.MaterialLayers:
            material = self._parse_single_material(layer.Material)
            # Read direct thickness attribute or fallback to property
            thickness = getattr(layer, "LayerThickness", None)
            if thickness is None and hasattr(layer, "thickness"):
                thickness = getattr(layer, "thickness")
            thickness = float(thickness or 0.0)
            elem_data.material_layers.append(MaterialLayer(material, thickness))

    def _parse_material_constituents(self, constituent_set: Any, elem_data: ElementData) -> None:
        """Parse IfcMaterialConstituentSet and constituent fractions/functions."""
        if not hasattr(constituent_set, "MaterialConstituents"):
            return
        
        for constituent in constituent_set.MaterialConstituents:
            mat_obj = getattr(constituent, "Material", None)
            if not mat_obj:
                continue
            material = self._parse_single_material(mat_obj)
            
            # Extract Constituent Category/Function (e.g. "LoadBearing", "Finishing", "Insulation")
            # In IFC, Category holds the function (e.g. "LoadBearing"), while Name is often the material description.
            category = getattr(constituent, "Category", None)
            name = getattr(constituent, "Name", None)
            constituent_function = category or name
            if constituent_function:
                material.constituent_name = str(constituent_function)
            
            # Extract Fraction if specified (e.g. 0.04257778)
            fraction_val = getattr(constituent, "Fraction", None)
            if fraction_val is not None:
                try:
                    material.fraction = float(fraction_val)
                except (ValueError, TypeError):
                    pass
            elem_data.materials.append(material)

    def _get_classification_ref(self, material: Any) -> Optional[str]:
        """Extract IfcClassificationReference from material."""
        _, code = self._get_classification_info(material)
        return code

    def _get_classification_info(self, material: Any) -> Tuple[Optional[str], Optional[str]]:
        """Return classification system name and code, such as OmniClass."""
        if hasattr(material, "HasExternalReferences"):
            for ref in material.HasExternalReferences:
                if ref.is_a("IfcClassificationReference"):
                    source = getattr(ref, "ReferencedSource", None)
                    system = getattr(source, "Name", None) if source else None
                    code = getattr(ref, "Identification", None) or getattr(ref, "Name", None)
                    return system, code
        return None, None

    def _extract_density_from_material(self, material: Any) -> Optional[float]:
        """Extract density from Pset_MaterialCommon."""
        try:
            pset = get_pset(material, "Pset_MaterialCommon")
            if pset and "MassDensity" in pset:
                return float(pset["MassDensity"])
        except Exception as e:
            logger.debug(f"Could not extract density: {e}")
        return None

    def _extract_material_properties(self, material: Any) -> Dict[str, Any]:
        """Extract all properties from material."""
        props = {}
        try:
            pset = get_pset(material, "Pset_MaterialCommon")
            if pset:
                props.update(pset)
        except Exception:
            pass
        return props

    def _extract_quantities(self, element: Any, elem_data: ElementData) -> None:
        """
        Extract quantities from IfcElementQuantity (Qto_*BaseQuantities).
        """
        try:
            if not hasattr(element, "IsDefinedBy"):
                return
            
            for rel in element.IsDefinedBy:
                if rel.is_a("IfcRelDefinesByProperties"):
                    prop_set = rel.RelatingPropertyDefinition
                    
                    if prop_set.is_a("IfcElementQuantity"):
                        # Process quantity set
                        self._process_element_quantity_set(prop_set, elem_data)
                        
        except Exception as e:
            logger.debug(f"Error extracting quantities: {e}")

    def _process_element_quantity_set(self, quant_set: Any, elem_data: ElementData) -> None:
        """Process IfcElementQuantity (Qto_*BaseQuantities)."""
        if not hasattr(quant_set, "Quantities"):
            return
        
        for quantity in quant_set.Quantities:
            quant_name = quantity.Name or "Unknown"
            
            if quantity.is_a("IfcQuantityVolume"):
                if hasattr(quantity, "VolumeValue"):
                    elem_data.quantities[quant_name] = Quantity(
                        name=quant_name,
                        value=float(quantity.VolumeValue),
                        unit="m³",
                        source="Explicit"
                    )
                    if "GrossVolume" not in elem_data.quantities or quant_name in ("GrossVolume", "NetVolume"):
                        elem_data.quantities["GrossVolume"] = Quantity(
                            name="GrossVolume",
                            value=float(quantity.VolumeValue),
                            unit="m³",
                            source="Explicit"
                        )
                    
            elif quantity.is_a("IfcQuantityArea"):
                if hasattr(quantity, "AreaValue"):
                    elem_data.quantities[quant_name] = Quantity(
                        name=quant_name,
                        value=float(quantity.AreaValue),
                        unit="m²",
                        source="Explicit"
                    )
                    # Fallback for NetSideArea if GrossSideArea is present
                    if "NetSideArea" not in elem_data.quantities and quant_name in ("GrossSideArea", "NetSideArea", "GrossArea", "NetArea", "Area"):
                        elem_data.quantities["NetSideArea"] = Quantity(
                            name="NetSideArea",
                            value=float(quantity.AreaValue),
                            unit="m²",
                            source="Explicit"
                        )
                    
            elif quantity.is_a("IfcQuantityLength"):
                if hasattr(quantity, "LengthValue"):
                    elem_data.quantities[quant_name] = Quantity(
                        name=quant_name,
                        value=float(quantity.LengthValue),
                        unit="m",
                        source="Explicit"
                    )

            elif quantity.is_a("IfcPhysicalComplexQuantity"):
                # Handle IfcPhysicalComplexQuantity (e.g. per-layer dimensions / widths from Vectorworks / Revit)
                c_name = quantity.Name or "Unknown"
                sub_quantities = {}
                if hasattr(quantity, "HasQuantities"):
                    for sub_q in quantity.HasQuantities:
                        sub_q_name = sub_q.Name or "Unknown"
                        val = None
                        if hasattr(sub_q, "LengthValue"):
                            val = float(sub_q.LengthValue)
                        elif hasattr(sub_q, "AreaValue"):
                            val = float(sub_q.AreaValue)
                        elif hasattr(sub_q, "VolumeValue"):
                            val = float(sub_q.VolumeValue)
                        if val is not None:
                            sub_quantities[sub_q_name] = val
                if sub_quantities:
                    elem_data.complex_layer_quantities[c_name] = sub_quantities

    def _extract_properties(self, element: Any, elem_data: ElementData) -> None:
        """Extract general properties from element."""
        if hasattr(element, "IsDefinedBy"):
            for rel in element.IsDefinedBy:
                if rel.is_a("IfcRelDefinesByProperties"):
                    prop_set = rel.RelatingPropertyDefinition
                    if prop_set.is_a("IfcPropertySet"):
                        try:
                            for prop in prop_set.HasProperties:
                                if hasattr(prop, "NominalValue"):
                                    elem_data.properties[prop.Name] = prop.NominalValue
                        except Exception:
                            pass

    def close(self) -> None:
        """Close IFC file."""
        if hasattr(self, "ifc"):
            self.ifc.close()
