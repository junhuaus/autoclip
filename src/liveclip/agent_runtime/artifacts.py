from __future__ import annotations

from liveclip.agent_runtime.models import AgentArtifact


class ArtifactStore:
    """Run-local immutable artifact store with deterministic insertion order."""

    def __init__(self, *, max_artifacts: int = 256) -> None:
        if not 1 <= max_artifacts <= 2_000:
            raise ValueError("artifact store limit must be between 1 and 2000")
        self._max_artifacts = max_artifacts
        self._artifacts: dict[str, AgentArtifact] = {}

    def add(self, artifact: AgentArtifact) -> AgentArtifact:
        if artifact.artifact_id in self._artifacts:
            raise ValueError(f"artifact already exists: {artifact.artifact_id}")
        if len(self._artifacts) >= self._max_artifacts:
            raise ValueError("artifact store limit reached")
        self._artifacts[artifact.artifact_id] = artifact
        return artifact

    def add_many(self, values: tuple[AgentArtifact, ...]) -> tuple[AgentArtifact, ...]:
        artifact_ids = tuple(value.artifact_id for value in values)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("artifact batch contains duplicate IDs")
        if any(artifact_id in self._artifacts for artifact_id in artifact_ids):
            raise ValueError("artifact batch conflicts with an existing ID")
        if len(self._artifacts) + len(values) > self._max_artifacts:
            raise ValueError("artifact store limit reached")
        self._artifacts.update((value.artifact_id, value) for value in values)
        return values

    def get(self, artifact_id: str) -> AgentArtifact:
        try:
            return self._artifacts[artifact_id]
        except KeyError as exc:
            raise ValueError(f"unknown artifact: {artifact_id}") from exc

    def all(self) -> tuple[AgentArtifact, ...]:
        return tuple(self._artifacts.values())

    def resolve(self, artifact_ids: tuple[str, ...]) -> tuple[AgentArtifact, ...]:
        return tuple(self.get(artifact_id) for artifact_id in artifact_ids)


__all__ = ["ArtifactStore"]
