from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import CaseStatus
from app.schemas.common import ORMModel


class StatutorySection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    act: Optional[str] = Field(default=None, max_length=200)
    section: str = Field(min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, max_length=500)


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_reference: Optional[str] = Field(default=None, min_length=1, max_length=100)
    fir_number: Optional[str] = Field(default=None, min_length=1, max_length=100)
    police_station: Optional[str] = Field(default=None, max_length=200)
    court_name: Optional[str] = Field(default=None, max_length=200)
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    jurisdiction: Optional[str] = Field(default=None, max_length=200)
    statutory_sections: list[StatutorySection] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _needs_identifier(self) -> "CaseCreate":
        if not (self.title or self.external_reference or self.fir_number):
            raise ValueError("Provide at least one of title, external_reference or fir_number.")
        return self


class CaseUpdate(BaseModel):
    """Partial update. Explicit null clears an optional field."""

    model_config = ConfigDict(extra="forbid")
    external_reference: Optional[str] = Field(default=None, min_length=1, max_length=100)
    fir_number: Optional[str] = Field(default=None, min_length=1, max_length=100)
    police_station: Optional[str] = Field(default=None, max_length=200)
    court_name: Optional[str] = Field(default=None, max_length=200)
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    jurisdiction: Optional[str] = Field(default=None, max_length=200)
    statutory_sections: Optional[list[StatutorySection]] = Field(default=None, max_length=100)
    status: Optional[CaseStatus] = None
    metadata: Optional[dict[str, Any]] = None

    @field_validator("status", "statutory_sections", "metadata")
    @classmethod
    def _not_null(cls, v):
        if v is None:
            raise ValueError("This field cannot be null.")
        return v


class CaseRead(ORMModel):
    id: str
    external_reference: Optional[str]
    fir_number: Optional[str]
    police_station: Optional[str]
    court_name: Optional[str]
    title: Optional[str]
    jurisdiction: Optional[str]
    statutory_sections: list[Any]
    status: CaseStatus
    analysis_needs_refresh: bool
    metadata: dict[str, Any] = Field(validation_alias="case_metadata")
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime
