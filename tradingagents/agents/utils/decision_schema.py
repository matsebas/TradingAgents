"""Structured schema for the Risk Judge's final decision.

The Risk Judge emits prose (the 8 narrative sections) PLUS a fenced JSON
block at the end with this exact shape. The downstream validator parses
the JSON, checks role-discipline gates, and either accepts the decision
or auto-downgrades it to HOLD with an explicit reason.

The schema is intentionally rigid — every BUY must have a paired entry
plan, every decision must have a stop-loss, every flip must cite a
structural reason. This is the asymmetry-fix the PM framework lacks.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


Decision = Literal["BUY", "SELL", "HOLD"]
EntryQuality = Literal["optimal", "stretched", "chasing", "n/a"]
SectorOverlapLevel = Literal["none", "partial", "full"]


class EntryPlan(BaseModel):
    """How the BUY (or scaled add) is sequenced."""

    model_config = ConfigDict(extra="forbid")

    tier_now_pct: int = Field(..., ge=0, le=100)
    tier_pullback_target: Optional[str] = None
    basis: str = Field(..., min_length=1)


class StopLoss(BaseModel):
    """Exit-side discipline. Required on every decision — even HOLD."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["trailing", "hard"]
    value: str = Field(..., min_length=1)
    basis: str = Field(..., min_length=1)


class Triggers(BaseModel):
    """Forward-looking triggers attached to the position regardless of decision.

    Closes the asymmetry where the PM framework defines exits but not
    re-entries — the Judge must define both for every position.
    """

    model_config = ConfigDict(extra="forbid")

    entry_trigger: str = Field(..., min_length=1)
    exit_trigger: str = Field(..., min_length=1)
    profit_take_levels: list[str] = Field(default_factory=list)


class PrevDecisionConsistency(BaseModel):
    """Cross-run continuity check.

    `is_flip` is True iff the new decision differs from `previous_decision`.
    Whenever it's True, `structural_reason` must be a non-trivial citation
    of regime / fundamental / role change — NOT a technical oscillator.
    """

    model_config = ConfigDict(extra="forbid")

    previous_date: Optional[str] = None
    previous_decision: Optional[Decision] = None
    is_flip: bool
    structural_reason: Optional[str] = None


class PortfolioWeightMath(BaseModel):
    """Whole-book weight check used to gate tactical adds."""

    model_config = ConfigDict(extra="forbid")

    current_weight_pct: float = Field(..., ge=0, le=100)
    target_weight_pct: float = Field(..., ge=0, le=100)
    action_brings_to_pct: float = Field(..., ge=0, le=100)
    weight_gate_passes: bool


class CandidateAttributes(BaseModel):
    """Attributes specific to a candidate (new-position) decision.

    Mirrors the precomputed CandidateFit but with the LLM's interpretation —
    so the validator can compare what the code calculated against what the
    LLM claims, and the reporter can emit a clean comparative table.
    """

    model_config = ConfigDict(extra="forbid")

    score: float = Field(..., ge=0, le=10)  # composite 0-10
    role_gap_aligned: bool  # candidate's role bucket has headroom
    sector_overlap: SectorOverlapLevel
    sector_overlap_with: list[str] = Field(default_factory=list)
    thesis_strength: Literal["high", "medium", "low"]
    recommended_size_pct: float = Field(..., ge=0, le=10)  # of total book
    recommended_size_usd: Optional[float] = None  # absolute, when book size known


class TradeDecision(BaseModel):
    """Final structured output of the Risk Judge."""

    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(..., min_length=1)
    decision: Decision
    qty_change: int = 0  # signed nominales (negative for SELL/trim)
    entry_plan: Optional[EntryPlan] = None  # required when decision == BUY
    stop_loss: StopLoss
    triggers: Triggers
    previous_decision: PrevDecisionConsistency
    cited_role_guidance: str = Field(..., min_length=1)
    role: Optional[Literal["anchor", "tactical", "speculative", "candidate"]] = None
    entry_quality: EntryQuality = "n/a"
    portfolio_weight_math: Optional[PortfolioWeightMath] = None
    falsification_criteria: list[str] = Field(..., min_length=1)
    rationale: str = Field(..., min_length=1)
    # Only set when role == "candidate". Mirrors the precomputed CandidateFit.
    candidate: Optional[CandidateAttributes] = None

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("falsification_criteria")
    @classmethod
    def _trim_falsification(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if s and s.strip()]
        if not cleaned:
            raise ValueError("falsification_criteria must have at least one non-empty entry")
        return cleaned
