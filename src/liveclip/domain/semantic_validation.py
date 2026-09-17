"""Immutable semantic validation identities, independent of wire schemas."""

from typing import Final, Literal

SemanticValidationContract = Literal["semantic-v4-validation-v1", "semantic-v4-quality-v2"]

LEGACY_SEMANTIC_VALIDATION: Final[SemanticValidationContract] = "semantic-v4-validation-v1"
CURRENT_SEMANTIC_VALIDATION: Final[SemanticValidationContract] = "semantic-v4-quality-v2"
SemanticLineageContract = Literal["semantic-v5-lineage-v1"]
CURRENT_SEMANTIC_LINEAGE: Final[SemanticLineageContract] = "semantic-v5-lineage-v1"
SemanticTransportContract = Literal["semantic-cue-table-v1"]
CURRENT_SEMANTIC_TRANSPORT: Final[SemanticTransportContract] = "semantic-cue-table-v1"
SemanticExecutionContract = Literal["semantic-bounded-units-v1"]
CURRENT_SEMANTIC_EXECUTION: Final[SemanticExecutionContract] = "semantic-bounded-units-v1"
# A complete transient pre-repair failure can retry, but repeated stage/manual
# recovery cannot purchase an unlimited number of logical invocations.
SEMANTIC_UNIT_MAX_INVOCATIONS: Final[int] = 3


def uses_current_semantic_validation(contract: SemanticValidationContract) -> bool:
    if contract not in (LEGACY_SEMANTIC_VALIDATION, CURRENT_SEMANTIC_VALIDATION):
        raise ValueError("unsupported semantic validation contract")
    return contract == CURRENT_SEMANTIC_VALIDATION
