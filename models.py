from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

class CatalogItem(BaseModel):
    product_id: str
    department: str
    name: str
    category: str
    price: float
    specs: Dict[str, Any]
    raw_description: str
    compatibility_tags: List[str]
    quality_flag: str

class QualityAssessment(BaseModel):
    completeness_score: int = Field(ge=0, le=100)
    is_complete: bool
    missing_attributes: List[str]
    recommended_actions: List[str]

# --- THE FIX: We define a rigid structure for specs instead of a flexible dictionary ---
class SpecItem(BaseModel):
    spec_name: str = Field(description="The name of the spec (e.g., 'storage', 'wattage')")
    spec_value: str = Field(description="The value of the spec (e.g., '256GB', '45W')")

class EnrichedCatalogItem(BaseModel):
    product_id: str
    standardized_name: str
    enriched_description: str
    seo_tags: List[str]
    deep_taxonomy: str
    cross_sell_recommendations: List[str]
    # We tell OpenAI to output a strict list of SpecItem objects
    standardized_specs: List[SpecItem] = Field(description="Standardized technical specifications")

class CatalogAgentState(TypedDict):
    raw_item: CatalogItem
    assessment: Optional[QualityAssessment]
    enriched_item: Optional[EnrichedCatalogItem]
    workflow_status: str
    error_logs: List[str]