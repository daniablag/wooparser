from __future__ import annotations
from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, Field

class Image(BaseModel):
    url: str
    alt: Optional[str] = None

class Variation(BaseModel):
    sku: str
    regular_price: float
    sale_price: Optional[float] = None
    stock_quantity: Optional[int] = None
    attributes: Dict[str, str] = Field(default_factory=dict)
    image_url: Optional[str] = None

class Product(BaseModel):
    external_id: str
    name: str
    sku: Optional[str] = None
    description_html: Optional[str] = None
    short_description_html: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    images: List[Image] = Field(default_factory=list)
    attributes: Dict[str, List[str]] = Field(default_factory=dict)
    default_attributes: Dict[str, str] = Field(default_factory=dict)
    type: Literal["simple", "variable"] = "simple"
    regular_price: Optional[float] = None
    sale_price: Optional[float] = None
    stock_quantity: Optional[int] = None
    variations: List[Variation] = Field(default_factory=list)
