"""
Material Mapper: Map IFC materials to Ökobaudat datasets.

Strategies:
1. Classification-based: Direct mapping via IfcClassificationReference
2. Name-based: Fuzzy matching on material names (fallback)
3. Hybrid: Combined approach for maximum coverage
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


@dataclass
class OekobaudatDataset:
    """Represents an Ökobaudat dataset entry."""
    id: str
    name: str
    density: float  # kg/m³
    gwp_a1a3: Optional[float] = None  # kg CO₂-eq per kg
    gwp_c1c4: Optional[float] = None
    epd_id: Optional[str] = None
    description: str = ""


class MaterialMapper:
    """Map materials to Ökobaudat datasets."""

    def __init__(self, strategy: str = "hybrid"):
        """
        Initialize mapper.
        
        Args:
            strategy: "classification", "name", or "hybrid"
        """
        self.strategy = strategy
        self.oekobaudat_db: Dict[str, OekobaudatDataset] = {}
        self._load_default_oekobaudat()

    def _load_default_oekobaudat(self) -> None:
        """Load default Ökobaudat materials (stub)."""
        # This would be loaded from actual Ökobaudat database/API
        self.oekobaudat_db = {
            "OB_00001": OekobaudatDataset(
                id="OB_00001",
                name="Concrete C30/37",
                density=2400.0,
                gwp_a1a3=0.38,
                gwp_c1c4=0.05,
                description="Reinforced concrete"
            ),
            "OB_00002": OekobaudatDataset(
                id="OB_00002",
                name="Steel reinforcement",
                density=7850.0,
                gwp_a1a3=2.8,
                gwp_c1c4=0.1,
                description="Reinforcing steel bars"
            ),
            "OB_00003": OekobaudatDataset(
                id="OB_00003",
                name="Wood - softwood",
                density=500.0,
                gwp_a1a3=-0.5,
                gwp_c1c4=0.02,
                description="Softwood timber"
            ),
        }
        logger.info(f"Loaded {len(self.oekobaudat_db)} default Ökobaudat entries")

    def add_oekobaudat_dataset(self, dataset: OekobaudatDataset) -> None:
        """Add a dataset to the database."""
        self.oekobaudat_db[dataset.id] = dataset

    def map_material(self, material_name: str, classification_ref: Optional[str] = None) -> Optional[OekobaudatDataset]:
        """
        Map a material to Ökobaudat dataset.
        
        Args:
            material_name: Name of the material
            classification_ref: Optional classification reference
            
        Returns:
            OekobaudatDataset or None
        """
        if self.strategy in ("classification", "hybrid"):
            if classification_ref:
                dataset = self._map_by_classification(classification_ref)
                if dataset:
                    return dataset
        
        if self.strategy in ("name", "hybrid"):
            dataset = self._map_by_name(material_name)
            if dataset:
                return dataset
        
        return None

    def _map_by_classification(self, classification_ref: str) -> Optional[OekobaudatDataset]:
        """Map by IfcClassificationReference."""
        # Direct ID lookup
        if classification_ref in self.oekobaudat_db:
            return self.oekobaudat_db[classification_ref]
        
        # Partial ID match
        for ref_id, dataset in self.oekobaudat_db.items():
            if classification_ref.lower() in ref_id.lower() or ref_id.lower() in classification_ref.lower():
                logger.debug(f"Matched classification {classification_ref} to {ref_id}")
                return dataset
        
        return None

    def _map_by_name(self, material_name: str, threshold: float = 0.6) -> Optional[OekobaudatDataset]:
        """
        Map by name matching using sequence matching.
        
        Args:
            material_name: Material name to match
            threshold: Minimum match ratio (0-1)
            
        Returns:
            Best matching dataset or None
        """
        best_match = None
        best_ratio = threshold
        
        for dataset in self.oekobaudat_db.values():
            # Compare full name
            ratio = SequenceMatcher(None, material_name.lower(), dataset.name.lower()).ratio()
            
            if ratio > best_ratio:
                best_match = dataset
                best_ratio = ratio
            
            # Compare components (e.g., "Concrete" in "Concrete C30/37")
            if ratio > threshold:
                logger.debug(f"Name match: '{material_name}' ≈ '{dataset.name}' ({ratio:.2%})")
        
        if best_match:
            logger.debug(f"Best name match for '{material_name}': {best_match.name} ({best_ratio:.2%})")
        
        return best_match

    def map_materials_batch(self, materials: List[Tuple[str, Optional[str]]]) -> Dict[str, Optional[OekobaudatDataset]]:
        """
        Map multiple materials.
        
        Args:
            materials: List of (name, classification_ref) tuples
            
        Returns:
            Dict mapping material names to datasets
        """
        results = {}
        for name, classification_ref in materials:
            results[name] = self.map_material(name, classification_ref)
        return results

    def get_density(self, material_name: str, density_override: Optional[float] = None, classification_ref: Optional[str] = None) -> Optional[float]:
        """
        Get density for material.
        
        Priority:
        1. Provided override
        2. Ökobaudat dataset
        3. Material properties (if available)
        4. None
        
        Args:
            material_name: Material name
            density_override: Manual override (kg/m³)
            classification_ref: Optional classification reference
            
        Returns:
            Density in kg/m³ or None
        """
        if density_override is not None:
            return density_override
        
        dataset = self.map_material(material_name, classification_ref)
        if dataset:
            return dataset.density
        
        return None

    def estimate_mass(self, volume: float, density: float) -> float:
        """
        Calculate mass from volume and density.
        
        Args:
            volume: Volume in m³
            density: Density in kg/m³
            
        Returns:
            Mass in kg
        """
        return volume * density

    def calculate_environmental_impact(self, mass: float, dataset: OekobaudatDataset) -> Dict[str, float]:
        """
        Calculate environmental impact (GWP, etc.).
        
        Args:
            mass: Mass in kg
            dataset: Ökobaudat dataset
            
        Returns:
            Dict with impact indicators
        """
        impacts = {}
        
        if dataset.gwp_a1a3 is not None:
            impacts["GWP_A1A3"] = mass * dataset.gwp_a1a3
        
        if dataset.gwp_c1c4 is not None:
            impacts["GWP_C1C4"] = mass * dataset.gwp_c1c4
        
        return impacts
