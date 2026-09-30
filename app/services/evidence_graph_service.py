from app.schemas.agent_state import CaseAgentState
from app.schemas.evidence_graph import (
    EvidenceGraph,
    EvidenceGraphEdge,
    EvidenceGraphNode,
)


def build_evidence_graph(state: CaseAgentState) -> EvidenceGraph:
    nodes: dict[str, EvidenceGraphNode] = {}
    edges: dict[str, EvidenceGraphEdge] = {}

    def add_node(node: EvidenceGraphNode) -> None:
        nodes[node.node_id] = node

    def add_edge(
        source_id: str,
        target_id: str,
        relationship: str,
        provenance: dict | None = None,
    ) -> None:
        if source_id not in nodes or target_id not in nodes:
            return
        edge_id = f"{source_id}-[{relationship}]->{target_id}"
        edges[edge_id] = EvidenceGraphEdge(
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relationship=relationship,
            provenance=provenance or {},
        )

    document_types = {item.document_id: item.document_type for item in state.documents}
    filenames = {item.document_id: item.filename for item in state.documents}
    for document_id, document_type in document_types.items():
        add_node(
            EvidenceGraphNode(
                node_id=f"document:{document_id}",
                node_type="document",
                label=filenames.get(document_id) or document_id,
                provenance={"document_id": document_id, "document_type": document_type},
            )
        )

    facts_by_key = {}
    for fact in state.facts:
        fact_node_id = f"fact:{fact.document_id or 'unknown'}:{fact.fact_id}"
        facts_by_key[(fact.document_id, fact.fact_id)] = fact_node_id
        add_node(
            EvidenceGraphNode(
                node_id=fact_node_id,
                node_type="fact",
                label=f"{fact.field}: {fact.value}",
                provenance={
                    "document_id": fact.document_id,
                    "page": fact.page,
                    "quote": fact.quote,
                    "confidence": fact.confidence,
                    "extraction_method": fact.extraction_method,
                },
                attributes={
                    "fact_id": fact.fact_id,
                    "fact_type": fact.fact_type,
                    "field": fact.field,
                    "normalized_value": fact.normalized_value,
                },
            )
        )
        if fact.document_id:
            if f"document:{fact.document_id}" not in nodes:
                add_node(EvidenceGraphNode(
                    node_id=f"document:{fact.document_id}",
                    node_type="document",
                    label=fact.document_id,
                    provenance={"document_id": fact.document_id},
                ))
            add_edge(f"document:{fact.document_id}", fact_node_id, "contains_fact")

    evidence_by_id = {}
    evidence_node_by_id = {}
    for evidence in state.evidence:
        node_id = f"evidence:{evidence.document_id}:{evidence.evidence_id}"
        evidence_by_id.setdefault(evidence.evidence_id, []).append(evidence)
        evidence_node_by_id[(evidence.document_id, evidence.evidence_id)] = node_id
        add_node(
            EvidenceGraphNode(
                node_id=node_id,
                node_type="evidence",
                label=f"{evidence.evidence_type}: {evidence.quote[:100]}",
                provenance={
                    "document_id": evidence.document_id,
                    "document_type": evidence.document_type,
                    "page": evidence.page,
                    "quote": evidence.quote,
                    "normalized_value": evidence.normalized_value,
                    "confidence": evidence.confidence,
                    "extraction_method": evidence.extraction_method,
                    "fact_id": evidence.fact_id,
                },
                attributes={"evidence_id": evidence.evidence_id, "evidence_type": evidence.evidence_type},
            )
        )
        document_node_id = f"document:{evidence.document_id}"
        if document_node_id not in nodes:
            add_node(EvidenceGraphNode(
                node_id=document_node_id,
                node_type="document",
                label=filenames.get(evidence.document_id) or evidence.document_id,
                provenance={"document_id": evidence.document_id, "document_type": evidence.document_type},
            ))
        add_edge(document_node_id, node_id, "contains_evidence")
        fact_node_id = facts_by_key.get((evidence.document_id, evidence.fact_id))
        if fact_node_id:
            add_edge(fact_node_id, node_id, "supports_evidence", {
                "fact_id": evidence.fact_id,
                "evidence_id": evidence.evidence_id,
            })

    claim_nodes = {}
    for claim in state.claims:
        node_id = f"claim:{claim.document_id}:{claim.claim_id}"
        claim_nodes[claim.claim_id] = node_id
        add_node(
            EvidenceGraphNode(
                node_id=node_id,
                node_type="claim",
                label=claim.claim_text,
                provenance={
                    "document_id": claim.document_id,
                    "document_type": claim.document_type,
                    "page": claim.page,
                    "quote": claim.quote,
                    "confidence": claim.confidence,
                },
                attributes={"claim_id": claim.claim_id, "claim_type": claim.claim_type},
            )
        )
        document_node_id = f"document:{claim.document_id}"
        if document_node_id not in nodes:
            add_node(EvidenceGraphNode(
                node_id=document_node_id,
                node_type="document",
                label=filenames.get(claim.document_id) or claim.document_id,
                provenance={"document_id": claim.document_id, "document_type": claim.document_type},
            ))
        add_edge(document_node_id, node_id, "contains_claim")
        for evidence_id in claim.supporting_evidence_ids:
            for evidence in evidence_by_id.get(evidence_id, []):
                add_edge(
                    evidence_node_by_id[(evidence.document_id, evidence_id)],
                    node_id,
                    "supports_claim",
                    {"evidence_id": evidence_id, "claim_id": claim.claim_id},
                )

    conflict_nodes = {}
    for conflict in state.conflicts:
        node_id = f"conflict:{conflict.conflict_id}"
        conflict_nodes[conflict.conflict_id] = node_id
        add_node(
            EvidenceGraphNode(
                node_id=node_id,
                node_type="conflict",
                label=conflict.description,
                provenance={
                    "document_ids": conflict.document_ids,
                    "source_pages": conflict.source_pages,
                    "quotes": conflict.quotes,
                    "evidence_ids": conflict.evidence_ids,
                },
                attributes={
                    "conflict_id": conflict.conflict_id,
                    "conflict_type": conflict.conflict_type,
                    "event_type": conflict.event_type,
                    "severity": conflict.severity,
                },
            )
        )
        for source in conflict.conflicting_values:
            evidence_node_id = evidence_node_by_id.get((source.document_id, source.evidence_id))
            if evidence_node_id:
                add_edge(
                    evidence_node_id,
                    node_id,
                    "participates_in_conflict",
                    {
                        "document_id": source.document_id,
                        "page": source.page,
                        "quote": source.quote,
                        "normalized_value": source.normalized_value,
                    },
                )
        for claim_id in conflict.claim_ids:
            claim_node_id = claim_nodes.get(claim_id)
            if claim_node_id:
                add_edge(claim_node_id, node_id, "involved_in_conflict")

    latest = state.reasoning_results[-1] if state.reasoning_results else None
    recommendation_node_id = None
    if latest:
        recommendation_node_id = f"recommendation:{latest.reasoning_id}"
        add_node(
            EvidenceGraphNode(
                node_id=recommendation_node_id,
                node_type="recommendation",
                label=latest.recommendation,
                provenance={"reasoning_id": latest.reasoning_id},
                attributes={
                    "recommendation": latest.recommendation,
                    "effective_recommendation": (
                        state.overrides[-1].recommendation if state.overrides else latest.recommendation
                    ),
                    "human_review_required": latest.human_review_required,
                    "override_id": state.overrides[-1].override_id if state.overrides else None,
                },
            )
        )
        for evaluation in latest.rules_evaluated:
            rule_node_id = f"rule:{evaluation.rule_id}"
            add_node(
                EvidenceGraphNode(
                    node_id=rule_node_id,
                    node_type="rule",
                    label=evaluation.rule_name,
                    provenance={"evidence_ids": evaluation.evidence_ids},
                    attributes={
                        "rule_id": evaluation.rule_id,
                        "triggered": evaluation.triggered,
                        "explanation": evaluation.explanation,
                    },
                )
            )
            for conflict in state.conflicts:
                if set(evaluation.evidence_ids) & set(conflict.evidence_ids):
                    add_edge(
                        conflict_nodes[conflict.conflict_id],
                        rule_node_id,
                        "evaluated_by",
                        {"conflict_id": conflict.conflict_id, "rule_id": evaluation.rule_id},
                    )
            if evaluation.triggered:
                add_edge(rule_node_id, recommendation_node_id, "informs_recommendation", {
                    "rule_id": evaluation.rule_id,
                    "reasoning_id": latest.reasoning_id,
                })

    return EvidenceGraph(
        case_id=state.case_id,
        version=state.version,
        nodes=list(nodes.values()),
        edges=list(edges.values()),
    )
