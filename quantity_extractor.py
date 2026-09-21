"""
Quantity Extractor: Resolve quantities from IFC with geometry fallback.

Handles:
- IfcElementQuantity (Qto_*BaseQuantities)
- Layer-based volume calculation (LayerThickness × Area)
- Geometry-based fallback calculation
- Plausibility checks
"""

from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class QuantityExtractor:
    """Extract and calculate quantities from IFC elements."""

    @staticmethod
    def extract_volume_from_quantities(quantities: Dict[str, Any]) -> Optional[float]:
        """
        Extract volume from quantities dict.
        
        Priority:
        1. GrossVolume
        2. NetVolume
        3. None
        
        Args:
            quantities: Dict of Quantity objects
            
        Returns:
            Volume in m³ or None
        """
        if "GrossVolume" in quantities:
            return quantities["GrossVolume"].value
        
        if "NetVolume" in quantities:
            return quantities["NetVolume"].value
        
        return None

    @staticmethod
    def calculate_volume_from_layers(
        layer_thicknesses: Dict[str, float],
        base_area: float
    ) -> Dict[str, float]:
        """
        Calculate volume per material from layer thicknesses.
        
        For IfcMaterialLayerSet:
        Volume_per_material = LayerThickness (mm) × Element_NetSideArea (m²)
        
        Args:
            layer_thicknesses: Dict mapping material name to thickness in mm
            base_area: Element area in m²
            
        Returns:
            Dict mapping material name to volume in m³
        """
        volumes = {}
        
        for material_name, thickness_mm in layer_thicknesses.items():
            thickness_m = thickness_mm / 1000.0  # Convert mm to m
            volume = thickness_m * base_area
            volumes[material_name] = volume
            logger.debug(f"Layer volume: {material_name}: {thickness_mm}mm × {base_area}m² = {volume}m³")
        
        return volumes

    @staticmethod
    def calculate_volume_from_dimensions(
        length: float,
        width: Optional[float] = None,
        height: Optional[float] = None
    ) -> Optional[float]:
        """
        Calculate volume from length, width, height.
        
        Args:
            length: Length in m
            width: Width in m (optional)
            height: Height in m (optional)
            
        Returns:
            Volume in m³ or None
        """
        try:
            if width is not None and height is not None:
                return length * width * height
            elif width is not None:
                return length * width
            else:
                return None
        except Exception as e:
            logger.error(f"Error calculating volume: {e}")
            return None

    @staticmethod
    def calculate_area_from_dimensions(
        length: float,
        width: Optional[float] = None
    ) -> Optional[float]:
        """
        Calculate area from length and width.
        
        Args:
            length: Length in m
            width: Width in m (optional)
            
        Returns:
            Area in m² or None
        """
        try:
            if width is not None:
                return length * width
            else:
                return None
        except Exception as e:
            logger.error(f"Error calculating area: {e}")
            return None

    @staticmethod
    def validate_quantity(value: float, element_type: str, quantity_type: str) -> bool:
        """
        Validate quantity for plausibility.
        
        Args:
            value: Quantity value
            element_type: IFC element type (e.g., "IfcWall")
            quantity_type: Quantity type (e.g., "Volume")
            
        Returns:
            True if plausible, False otherwise
        """
        # Basic sanity checks
        if value <= 0:
            return False
        
        # Element-specific checks (example ranges)
        plausibility_ranges = {
            "Volume": (0.001, 10000),  # 0.001 m³ to 10000 m³
            "Area": (0.01, 100000),     # 0.01 m² to 100000 m²
            "Length": (0.01, 1000),     # 0.01 m to 1000 m
        }
        
        if quantity_type in plausibility_ranges:
            min_val, max_val = plausibility_ranges[quantity_type]
            return min_val <= value <= max_val
        
        return True

    @staticmethod
    def estimate_volume_from_geometry(element: Any) -> Optional[float]:
        """
        Estimate volume from element geometry (fallback).
        
        This is a placeholder for geometry-based calculation.
        Requires ifcopenshell geometry module.
        
        Args:
            element: IfcElement object
            
        Returns:
            Volume in m³ or None
        """
        try:
            # This would require geometry calculation
            # Placeholder implementation
            logger.debug("Geometry-based volume estimation not yet implemented")
            return None
        except Exception as e:
            logger.error(f"Error estimating volume from geometry: {e}")
            return None

    @staticmethod
    def resolve_quantity(
        explicit_volume: Optional[float] = None,
        calculated_volume: Optional[float] = None,
        fallback_volume: Optional[float] = None,
        element_type: str = "Unknown"
    ) -> tuple[Optional[float], str]:
        """
        Resolve final quantity with source attribution.
        
        Priority:
        1. Explicit (from Qto_*BaseQuantities) if plausible
        2. Calculated (from layer thicknesses or dimensions)
        3. Fallback (from geometry)
        4. None
        
        Args:
            explicit_volume: Volume from IfcElementQuantity
            calculated_volume: Volume from calculated dimensions
            fallback_volume: Volume from geometry
            element_type: IFC element type for validation
            
        Returns:
            Tuple of (volume_m3, source_string)
        """
        # Try explicit first
        if explicit_volume is not None:
            if QuantityExtractor.validate_quantity(explicit_volume, element_type, "Volume"):
                return explicit_volume, "Explicit"
            else:
                logger.warning(f"Explicit volume {explicit_volume} failed plausibility check")
        
        # Try calculated
        if calculated_volume is not None:
            if QuantityExtractor.validate_quantity(calculated_volume, element_type, "Volume"):
                return calculated_volume, "Calculated"
        
        # Try fallback
        if fallback_volume is not None:
            if QuantityExtractor.validate_quantity(fallback_volume, element_type, "Volume"):
                return fallback_volume, "Fallback"
        
        return None, "None"
