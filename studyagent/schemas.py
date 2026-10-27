from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpaceIn(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["course", "focus"]
    topic: str = Field(min_length=2, max_length=500)


class MaterialCheck(StrictModel):
    status: Literal["accepted", "rejected", "uncertain", "conflict"]
    reason: str
    relevant: bool
    credible: bool
    conflicts: list[str] = []


class ConceptDraft(StrictModel):
    name: str
    description: str
    evidence_ids: list[str]


class EdgeDraft(StrictModel):
    source: str
    target: str
    evidence_ids: list[str]


class GraphDraft(StrictModel):
    concepts: list[ConceptDraft]
    edges: list[EdgeDraft]


class EvidenceCheck(StrictModel):
    sufficient: bool
    in_scope: bool
    missing: list[str]
    conflicts: list[str]
    reason: str


class CitationDraft(StrictModel):
    evidence_id: str
    quote: str


class Answer(StrictModel):
    answer: str
    citations: list[CitationDraft]
    gap: str = ""


class Teaching(StrictModel):
    explanation: str
    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    rubric: str
    answer_explanation: str

    @field_validator("options")
    @classmethod
    def unique_options(cls, options):
        cleaned = [option.strip() for option in options]
        if any(not option for option in cleaned) or len(set(cleaned)) != len(cleaned):
            raise ValueError("测验选项必须非空且互不相同")
        return cleaned


class Grade(StrictModel):
    correct: bool
    score: float = Field(ge=0, le=1)
    feedback: str


class Preference(StrictModel):
    save: bool
    content: str
    reason: str


class AgentDecision(StrictModel):
    action: Literal[
        "clarify",
        "answer",
        "retrieve",
        "search",
        "explanation",
        "example",
        "quiz",
        "advance",
        "stop",
        "complete",
    ]
    space_id: str
    concept_id: str | None = None
    evidence_ids: list[str] = []
    reason: str = Field(max_length=600)


class ChatIn(StrictModel):
    space_id: str | None = None
    chat_id: str | None = None
    message: str = Field(min_length=1, max_length=6000)
    baseline: bool = False


class SessionIn(StrictModel):
    concept_id: str


class Submission(StrictModel):
    quiz_id: str
    submission_id: str = Field(min_length=8, max_length=100)
    answer: str = Field(min_length=1, max_length=3000)


class Admit(StrictModel):
    source_space_id: str
    document_id: str


class PreferenceIn(StrictModel):
    content: str = Field(min_length=2, max_length=1000)
