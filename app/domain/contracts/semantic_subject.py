"""主体の型付きidentityと、Runtimeに固定されたSELFの整合を定義する。"""

from dataclasses import dataclass
from enum import Enum


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("主体の識別子には空でない文字列が必要です")


class SemanticSubjectKind(str, Enum):
    SELF = "SELF"
    REFERENCE = "REFERENCE"


@dataclass(frozen=True, slots=True)
class SemanticSubjectIdentity:
    kind: SemanticSubjectKind
    subject_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SemanticSubjectKind):
            raise ValueError("主体には型付きのkindが必要です")
        _identifier(self.subject_ref)


@dataclass(frozen=True, slots=True)
class RuntimeSubjectIdentity:
    self_subject_ref: str
    character_id: str
    character_schema_version: int
    character_definition_revision: int

    def __post_init__(self) -> None:
        _identifier(self.self_subject_ref)
        _identifier(self.character_id)
        if self.self_subject_ref != self.character_id:
            raise ValueError("SELFの識別子とCharacterの識別子が一致しません")
        if type(self.character_schema_version) is not int or self.character_schema_version < 1:
            raise ValueError("Character schemaのバージョンには正の整数が必要です")
        if (
            type(self.character_definition_revision) is not int
            or self.character_definition_revision < 0
        ):
            raise ValueError("Character定義のリビジョンには非負整数が必要です")

    def self_subject(self) -> SemanticSubjectIdentity:
        return SemanticSubjectIdentity(SemanticSubjectKind.SELF, self.self_subject_ref)

    def reference_subject(self, explicit_ref: str) -> SemanticSubjectIdentity:
        subject = SemanticSubjectIdentity(SemanticSubjectKind.REFERENCE, explicit_ref)
        self.validate(subject)
        return subject

    def validate(self, subject: SemanticSubjectIdentity) -> None:
        if not isinstance(subject, SemanticSubjectIdentity):
            raise ValueError("検証対象には型付きの主体identityが必要です")
        if subject.kind is SemanticSubjectKind.SELF:
            if subject.subject_ref != self.self_subject_ref:
                raise ValueError("SELFの識別子が現在のRuntimeと一致しません")
        elif subject.subject_ref == self.self_subject_ref:
            raise ValueError("REFERENCEが現在のSELF識別子と衝突しています")
