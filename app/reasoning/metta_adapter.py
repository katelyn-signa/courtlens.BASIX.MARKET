from app.reasoning.rule_engine import evaluate_rules as evaluate_python_rules
from app.schemas.reasoning import RuleEvaluation, SemanticInterpretation


def evaluate_rules(
    interpretation: SemanticInterpretation,
    rule_ids: set[str] | None = None,
) -> list[RuleEvaluation]:
    """Stable adapter boundary; currently delegates to deterministic Python rules."""
    return evaluate_python_rules(interpretation, rule_ids)