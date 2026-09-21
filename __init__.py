"""
IFC-LCA-Analysis: Extract LCA data from IFC models and map to Ökobaudat.

Main components:
- ifc_parser: IFC file reading and material/quantity extraction
- material_mapper: Material classification and Ökobaudat mapping
- quantity_extractor: Quantity resolution and calculation
- oekobaudat_integration: Ökobaudat dataset access
- csv_export: CSV export functionality
"""

__version__ = "0.1.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"

try:
    from .ifc_parser import IfcParser
    from .material_mapper import MaterialMapper
    from .quantity_extractor import QuantityExtractor
    from .csv_export import CSVExporter
    
    __all__ = [
        "IfcParser",
        "MaterialMapper",
        "QuantityExtractor",
        "CSVExporter",
    ]
except ImportError:
    # Allow partial imports during development
    __all__ = []
