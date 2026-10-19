from __future__ import annotations

from collections.abc import Collection

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.agent_runtime.models import AgentArtifact


class TitleOptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    title: str = Field(min_length=1, max_length=80)
    style_label: str = Field(min_length=1, max_length=40)
    title_score: int = Field(ge=0, le=100)
    grounding_cue_ids: list[int] = Field(min_length=1, max_length=32)
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_cue_ids(self) -> TitleOptionInput:
        if any(isinstance(value, bool) or value < 1 for value in self.grounding_cue_ids):
            raise ValueError("title grounding cue IDs must be positive integers")
        if len(set(self.grounding_cue_ids)) != len(self.grounding_cue_ids):
            raise ValueError("title grounding cue IDs must be unique")
        return self


class SaveTitleOptionsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    artifact_id: str
    candidate_artifact_id: str
    primary_index: int = Field(ge=0, le=4)
    options: list[TitleOptionInput] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def validate_options(self) -> SaveTitleOptionsArguments:
        if self.primary_index >= len(self.options):
            raise ValueError("primary title index is outside the supplied options")
        normalized = tuple(option.title.strip().casefold() for option in self.options)
        if len(set(normalized)) != len(normalized):
            raise ValueError("title alternatives must be distinct")
        return self


class SaveTitleBatchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: list[SaveTitleOptionsArguments] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_items(self) -> SaveTitleBatchArguments:
        artifact_ids = [item.artifact_id for item in self.items]
        candidate_ids = [item.candidate_artifact_id for item in self.items]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("batch title artifact IDs must be unique")
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("batch titles may target each candidate only once")
        return self


class StoredTitleOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    title: str = Field(min_length=1, max_length=80)
    style_label: str = Field(min_length=1, max_length=40)
    title_score: int = Field(ge=0, le=100)
    grounding_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=32)
    rationale: str = Field(min_length=1, max_length=500)


class TitleOptionsData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_candidate_id: str
    primary_index: int = Field(ge=0, le=4)
    primary_title: str = Field(min_length=1, max_length=80)
    options: tuple[StoredTitleOption, ...] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def validate_primary(self) -> TitleOptionsData:
        if self.primary_index >= len(self.options):
            raise ValueError("primary title index is outside stored options")
        if self.primary_title != self.options[self.primary_index].title:
            raise ValueError("primary title must match its selected option")
        return self


def build_title_options_artifact(
    arguments: SaveTitleOptionsArguments,
    *,
    allowed_cue_ids: Collection[int],
) -> AgentArtifact:
    allowed = set(allowed_cue_ids)
    if any(
        cue_id not in allowed for option in arguments.options for cue_id in option.grounding_cue_ids
    ):
        raise ValueError("title grounding cue is outside the source candidate")
    options = tuple(
        StoredTitleOption(
            title=option.title,
            style_label=option.style_label,
            title_score=option.title_score,
            grounding_cue_ids=tuple(option.grounding_cue_ids),
            rationale=option.rationale,
        )
        for option in arguments.options
    )
    data = TitleOptionsData(
        source_candidate_id=arguments.candidate_artifact_id,
        primary_index=arguments.primary_index,
        primary_title=options[arguments.primary_index].title,
        options=options,
    )
    return AgentArtifact(
        artifact_id=arguments.artifact_id,
        artifact_type="title_options",
        data=data.model_dump(mode="json"),
        evidence=tuple(
            {
                "title_index": index,
                "grounding_cue_ids": list(option.grounding_cue_ids),
            }
            for index, option in enumerate(options)
        ),
    )


__all__ = [
    "SaveTitleBatchArguments",
    "SaveTitleOptionsArguments",
    "StoredTitleOption",
    "TitleOptionInput",
    "TitleOptionsData",
    "build_title_options_artifact",
]
