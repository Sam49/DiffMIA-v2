from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    RESEARCHER = "RESEARCHER"
    VIEWER = "VIEWER"


class ProviderType(str, Enum):
    MOCK = "mock"
    TRANSFORMERS = "transformers"
    OPENAI_COMPATIBLE = "openai_compatible"


class ExperimentStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExperimentStage(str, Enum):
    QUEUED = "queued"
    MUTATION_GENERATION = "mutation_generation"
    INFERENCE = "inference"
    ANALYSIS = "analysis"
    COMPLETED = "completed"


class Variant(str, Enum):
    ORIGINAL = "original"
    MUTATION = "mutation"


class InferenceStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    RETRY_LIMIT = "RETRY_LIMIT"
    NO_CANDIDATES = "NO_CANDIDATES"


class Classification(str, Enum):
    LOW_EVIDENCE = "LOW_EVIDENCE"
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    POSSIBLE_CONTAMINATION = "POSSIBLE_CONTAMINATION"
    HIGH_CONTAMINATION_SIGNAL = "HIGH_CONTAMINATION_SIGNAL"


class MutationStrategy(str, Enum):
    IDENTIFIER_RENAME = "identifier_rename"
