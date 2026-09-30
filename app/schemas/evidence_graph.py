from typing import Any, Literal

from pydantic import BaseModel, Field

GraphNodeType = Literal[
    "document",
    "fact",
    "evidence",
    "claim",
    "conflict",
    "rule",
    "recommendation",
]


class EvidenceGraphNode(BaseModel):
    node_id: str
    node_type: GraphNodeType
    label: str
    provenance: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)


class EvidenceGraphEdge(BaseModel):
    edge_id: str
    source_id: str
    target_id: str
    relationship: str
    provenance: dict[str, Any] = Field(default_factory=dict)


class EvidenceGraph(BaseModel):
    case_id: str
    version: int
    nodes: list[EvidenceGraphNode]
    edges: list[EvidenceGraphEdge]
