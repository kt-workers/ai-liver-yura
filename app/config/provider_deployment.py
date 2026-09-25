"""秘密を保持しないS2 deployment manifestを読み込む。"""

from dataclasses import dataclass

from app.config.s2_contracts import identity, invalid, parse, revision, shape

ROLE_IDS = frozenset(("input_meaning", "subjective_appraisal", "executive_deliberation"))


@dataclass(frozen=True, slots=True)
class ProviderSourceReference:
    source_id: str
    identity: str
    revision: int

    def __post_init__(self) -> None:
        identity(self.source_id)
        identity(self.identity)
        revision(self.revision, 0)


@dataclass(frozen=True, slots=True)
class ProviderRoleBinding:
    role_id: str
    availability_mode: str
    mapping_ref: ProviderSourceReference | None
    role_config_ref: ProviderSourceReference | None

    def __post_init__(self) -> None:
        if self.role_id not in ROLE_IDS:
            invalid()
        if self.availability_mode == "unconfigured":
            if self.mapping_ref is not None or self.role_config_ref is not None:
                invalid()
        elif self.availability_mode == "configured":
            if not isinstance(self.mapping_ref, ProviderSourceReference) or not isinstance(
                self.role_config_ref, ProviderSourceReference
            ):
                invalid()
        else:
            invalid()


@dataclass(frozen=True, slots=True)
class ProviderDeploymentConfig:
    schema_id: str
    deployment_id: str
    deployment_revision: int
    role_bindings: tuple[ProviderRoleBinding, ...]

    def __post_init__(self) -> None:
        if self.schema_id != "yura.provider-deployment.s2.v1":
            invalid()
        identity(self.deployment_id)
        revision(self.deployment_revision)
        bindings = tuple(self.role_bindings)
        if any(not isinstance(binding, ProviderRoleBinding) for binding in bindings):
            invalid()
        if (
            len(bindings) != 3
            or {b.role_id for b in bindings} != ROLE_IDS
            or len({b.availability_mode for b in bindings}) != 1
        ):
            invalid()
        object.__setattr__(self, "role_bindings", bindings)


def _reference(value: object) -> ProviderSourceReference | None:
    if value is None:
        return None
    data = shape(value, "source_id identity revision")
    return ProviderSourceReference(
        identity(data["source_id"]), identity(data["identity"]), revision(data["revision"], 0)
    )


def load_provider_deployment(source: str | bytes) -> ProviderDeploymentConfig:
    data = shape(parse(source), "schema_id deployment_id deployment_revision role_bindings")
    values = data["role_bindings"]
    if not isinstance(values, list):
        invalid()
    bindings = []
    for value in values:
        row = shape(value, "role_id availability_mode mapping_ref role_config_ref")
        bindings.append(
            ProviderRoleBinding(
                identity(row["role_id"]),
                identity(row["availability_mode"]),
                _reference(row["mapping_ref"]),
                _reference(row["role_config_ref"]),
            )
        )
    return ProviderDeploymentConfig(
        identity(data["schema_id"]),
        identity(data["deployment_id"]),
        revision(data["deployment_revision"]),
        tuple(bindings),
    )
