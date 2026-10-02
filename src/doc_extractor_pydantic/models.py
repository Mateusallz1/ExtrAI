from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DocumentKind = Literal["cnh", "rg", "unknown"]
FieldConfidence = Literal["high", "medium", "low"]

EXPECTED_FIELDS: dict[str, tuple[str, ...]] = {
    "cnh": (
        "name",
        "cpf",
        "birth_date",
        "issue_date",
        "validity",
        "first_licence_date",
        "registration",
        "category",
        "parentage",
    ),
    "rg": ("name", "cpf", "birth_date", "issue_date", "birth_place", "parentage"),
    "unknown": ("name", "cpf", "birth_date"),
}
"""Fields expected to be queried for each document type."""

FIELD_TERMS: dict[str, tuple[str, ...]] = {
    "name": ("nome",),
    "cpf": ("cpf",),
    "birth_date": ("nascimento",),
    "issue_date": ("emissão", "emissao"),
    "first_licence_date": (
        "1ª habilitação",
        "primeira habilitação",
        "1a habilitacao",
        "1ª hab",
        "1a hab",
    ),
    "registration": ("registro",),
    "category": ("categoria", "cat hab", "habilitação"),
    "validity": ("validade",),
    "nationality": ("nacionalidade",),
    "birth_place": ("local de nascimento", "naturalidade"),
    "parentage": ("filiação",),
}
"""Terms the model commonly uses when writing a warning for a field."""


def warning_applies(warning: str, kind: str) -> bool:
    """Whether a model-written warning is about a field this document even has."""

    expected = EXPECTED_FIELDS.get(kind)
    if expected is None or kind == "unknown":
        return True
    lowered = warning.casefold()
    if kind == "rg" and any(term in lowered for term in ("registro geral", "registro civil")):
        return True
    # A mixed warning must retain the information about an applicable field.
    # The text is unstructured: discarding its unrelated clause would risk changing
    # its meaning, so only warnings exclusively about inapplicable fields are dropped.
    if any(
        field in expected and any(
            re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lowered)
            for term in terms
        )
        for field, terms in FIELD_TERMS.items()
    ):
        return True
    return not any(
        field not in expected and any(term in lowered for term in terms)
        for field, terms in FIELD_TERMS.items()
    )


def _is_valid_cpf(value: str) -> bool:
    if not re.fullmatch(r"\s*\d{3}[ .-]?\d{3}[ .-]?\d{3}[ .-]?\d{2}\s*", value):
        return False
    digits = re.sub(r"\D", "", value)
    if len(digits) != 11 or re.fullmatch(r"(\d)\1{10}", digits):
        return False
    for position in (9, 10):
        total = sum(
            int(digits[index]) * (position + 1 - index)
            for index in range(position)
        )
        remainder = (total * 10) % 11
        expected = 0 if remainder == 10 else remainder
        if expected != int(digits[position]):
            return False
    return True


MAX_VALIDITY_HORIZON_YEARS = 15


def _parse_brazilian_date(value: str) -> date | None:
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", value.strip()):
        return None
    day, month, year = (int(part) for part in value.split("/"))
    if year < 1900 or year > 2100:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _is_valid_registration(value: str) -> bool:
    clean = value.strip().upper()
    if not re.fullmatch(r"[\d .-]+[X]?", clean):
        return False
    chars = re.sub(r"[^\dX]", "", clean)
    return 7 <= len(chars) <= 11 and not re.fullmatch(r"(\d)\1+", chars)


def _is_valid_category(value: str) -> bool:
    return re.fullmatch(r"(?:[A-E]|A[BCDE]|ACC)", value.strip().upper()) is not None


class ExtractedField(BaseModel):
    """A value found in the document, with an explicit uncertainty level."""

    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(
        default=None,
        description="Exact value visible in the document, or null when absent/illegible.",
    )
    confidence: FieldConfidence = Field(
        default="low",
        description="Confidence based on legibility and proximity to the field label.",
    )

    @field_validator("value", mode="before")
    @classmethod
    def blank_value_is_null(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class DocumentFields(BaseModel):
    """Known RG/CNH fields returned by the extraction agent."""

    model_config = ConfigDict(extra="forbid")

    name: ExtractedField | None = Field(default=None, description="Nome completo")
    cpf: ExtractedField | None = Field(default=None, description="CPF")
    birth_date: ExtractedField | None = Field(default=None, description="Data de nascimento")
    issue_date: ExtractedField | None = Field(default=None, description="Data de emissão")
    validity: ExtractedField | None = Field(default=None, description="Data de validade")
    first_licence_date: ExtractedField | None = Field(
        default=None, description="Data da 1ª habilitação"
    )
    registration: ExtractedField | None = Field(default=None, description="Número de registro")
    category: ExtractedField | None = Field(default=None, description="Categoria da habilitação")
    birth_place: ExtractedField | None = Field(default=None, description="Local de nascimento")
    nationality: ExtractedField | None = Field(default=None, description="Nacionalidade")
    parentage: ExtractedField | None = Field(default=None, description="Filiação")

    def sanitize(self) -> list[str]:
        """Drop semantically invalid values without guessing replacements."""

        issues: list[str] = []
        checks = (
            ("cpf", "O CPF", "confirmado", _is_valid_cpf),
            ("registration", "O registro", "confirmado", _is_valid_registration),
            ("category", "A categoria", "confirmada", _is_valid_category),
        )
        for attribute, label, verb, validator in checks:
            field = getattr(self, attribute)
            if field is None or field.value is None:
                continue
            if not validator(field.value):
                setattr(self, attribute, None)
                issues.append(f"{label} não pôde ser {verb}.")
            elif attribute == "category":
                field.value = field.value.strip().upper()

        if self.parentage and self.parentage.value:
            parentage = self.parentage.value.replace(r"\n", "\n")
            parentage = re.sub(r"\s*(?:;|\||\s/\s)\s*", "\n", parentage)
            parentage = re.sub(r"[ \t]+\n", "\n", parentage)
            parentage = re.sub(r"\n{2,}", "\n", parentage).strip()
            self.parentage.value = parentage

        date_fields = ("birth_date", "issue_date", "validity", "first_licence_date")
        date_labels = {
            "birth_date": "nascimento",
            "issue_date": "emissão",
            "validity": "validade",
            "first_licence_date": "1ª habilitação",
        }
        parsed_dates: dict[str, date] = {}
        for attribute in date_fields:
            field = getattr(self, attribute)
            if field is None or field.value is None:
                continue
            parsed = _parse_brazilian_date(field.value)
            if parsed is None:
                setattr(self, attribute, None)
                issues.append(f"A data de {date_labels[attribute]} não pôde ser confirmada.")
            else:
                parsed_dates[attribute] = parsed

        today = date.today()
        birth_date = parsed_dates.get("birth_date")
        issue_date = parsed_dates.get("issue_date")
        validity = parsed_dates.get("validity")
        first_licence_date = parsed_dates.get("first_licence_date")
        if birth_date and birth_date > today:
            self.birth_date = None
            birth_date = None
            issues.append("A data de nascimento não pode ser no futuro.")
        if issue_date and issue_date > today:
            self.issue_date = None
            issue_date = None
            issues.append("A data de emissão não pode ser no futuro.")
        if first_licence_date and first_licence_date > today:
            self.first_licence_date = None
            first_licence_date = None
            issues.append("A data de 1ª habilitação não pode ser no futuro.")
        if validity and (
            validity > date(today.year + MAX_VALIDITY_HORIZON_YEARS, 12, 31)
            or (issue_date and validity.year > issue_date.year + MAX_VALIDITY_HORIZON_YEARS)
        ):
            self.validity = None
            validity = None
            issues.append("A data de validade é excessivamente distante no futuro.")
        elif validity and validity < today:
            formatted_validity = validity.strftime("%d/%m/%Y")
            issues.append(f"A data de validade está expirada (vencida em {formatted_validity}).")
        if birth_date and issue_date and birth_date >= issue_date:
            self.birth_date = None
            self.issue_date = None
            issues.append("As datas de nascimento e emissão são incompatíveis.")
        if birth_date and first_licence_date and birth_date >= first_licence_date:
            self.birth_date = None
            self.first_licence_date = None
            issues.append("As datas de nascimento e 1ª habilitação são incompatíveis.")
        if first_licence_date and issue_date and first_licence_date > issue_date:
            self.first_licence_date = None
            self.issue_date = None
            issues.append("As datas de 1ª habilitação e emissão são incompatíveis.")
        if first_licence_date and validity and validity <= first_licence_date:
            self.first_licence_date = None
            self.validity = None
            issues.append("As datas de 1ª habilitação e validade são incompatíveis.")
        if issue_date and validity and validity <= issue_date:
            self.issue_date = None
            self.validity = None
            issues.append("As datas de emissão e validade são incompatíveis.")
        if birth_date and validity and validity <= birth_date:
            self.birth_date = None
            self.validity = None
            issues.append("As datas de nascimento e validade são incompatíveis.")
        return issues

    def populated(self) -> dict[str, ExtractedField]:
        return {
            key: value
            for key, value in self
            if value is not None and value.value is not None
        }


class DocumentExtraction(BaseModel):
    """Structured result expected from PydanticAI."""

    model_config = ConfigDict(extra="forbid")

    kind: DocumentKind = Field(
        default="unknown",
        description="Classificação do documento: cnh, rg ou unknown.",
    )
    fields: DocumentFields = Field(default_factory=DocumentFields)
    transcription: str = Field(
        default="",
        description="Transcrição limpa do texto que está legível no documento.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Avisos de legibilidade, conflito ou campo não localizado.",
    )

    @field_validator("transcription", mode="before")
    @classmethod
    def normalize_transcription(cls, value: object) -> str:
        return value.strip() if isinstance(value, str) else ""

    @model_validator(mode="after")
    def validate_extracted_fields(self) -> DocumentExtraction:
        # Drop the model's noise first: an invalid value removed below still warns.
        self.warnings = [
            warning for warning in self.warnings if warning_applies(warning, self.kind)
        ]
        for issue in self.fields.sanitize():
            if issue not in self.warnings:
                self.warnings.append(issue)
        return self
