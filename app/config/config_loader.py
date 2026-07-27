from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from app.config.errors import ConfigError
from app.config.strict import require_mapping, require_string_value

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "config.yaml"
)
CONFIG_PATH_ENV = "AI_LIVER_CONFIG_PATH"
MANIFEST_FILE_NAME = "index.yaml"

REQUIRED_TOP_LEVEL_KEYS = frozenset(
    {
        "app",
        "trace",
        "services",
        "models",
        "response_generator",
        "llm_roles",
        "speech",
        "topic_classifier",
        "memory",
        "character",
        "input_receivers",
        "confirmation",
    }
)
OPTIONAL_TOP_LEVEL_KEYS = frozenset({"plugins", "streaming"})
IMPORTABLE_TOP_LEVEL_KEYS = REQUIRED_TOP_LEVEL_KEYS | OPTIONAL_TOP_LEVEL_KEYS
RESERVED_TOP_LEVEL_KEYS = frozenset({"emotion_appraisal"})


@dataclass(frozen=True, slots=True)
class ConfigSourceBundle:
    """Merged raw settings and their top-level source ownership."""

    root_path: Path
    values: Mapping[str, Any]
    source_by_top_level_key: Mapping[str, Path]

    def source_for(self, yaml_path: str) -> Path:
        top_level_key = yaml_path.split(".", maxsplit=1)[0]
        return self.source_by_top_level_key.get(top_level_key, self.root_path)


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    values: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in values
        except TypeError as error:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found a duplicate key",
                key_node.start_mark,
            )
        values[key] = loader.construct_object(value_node, deep=deep)
    return values


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def resolve_config_entry(
    config_path: str | Path | None = None,
) -> tuple[Path, bool]:
    """Resolve the root entry and whether it came from a directory."""

    if config_path is None:
        configured = os.environ.get(CONFIG_PATH_ENV, "").strip()
        candidate = Path(configured) if configured else DEFAULT_CONFIG_PATH
    else:
        if isinstance(config_path, str) and not config_path.strip():
            raise ConfigError(
                path="<root>",
                expected="non-blank configuration path",
                actual="blank string",
            )
        candidate = Path(config_path)

    resolved = candidate.expanduser().resolve()
    if not resolved.exists():
        raise ConfigError(
            path="<root>",
            expected="existing YAML file or directory",
            actual="missing",
            source_file=str(resolved),
        )

    if resolved.is_dir():
        manifest_path = (resolved / MANIFEST_FILE_NAME).resolve()
        if not manifest_path.exists():
            raise ConfigError(
                path="<root>",
                expected=f"directory containing {MANIFEST_FILE_NAME}",
                actual="index.yaml missing",
                source_file=str(manifest_path),
            )
        if not manifest_path.is_file():
            raise ConfigError(
                path="<root>",
                expected="readable manifest file",
                actual="index.yaml is not a file",
                source_file=str(manifest_path),
            )
        return manifest_path, True

    if not resolved.is_file():
        raise ConfigError(
            path="<root>",
            expected="regular YAML file or directory",
            actual="not a file",
            source_file=str(resolved),
        )
    return resolved, False


def load_raw_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    """Read one YAML mapping without resolving manifests."""

    resolved_path = Path(config_path).expanduser().resolve()
    if not resolved_path.exists():
        raise ConfigError(
            path="<root>",
            expected="existing YAML file",
            actual="missing",
            source_file=str(resolved_path),
        )
    if not resolved_path.is_file():
        raise ConfigError(
            path="<root>",
            expected="regular YAML file",
            actual="directory",
            source_file=str(resolved_path),
        )

    try:
        with resolved_path.open("r", encoding="utf-8") as file:
            raw_config = yaml.load(file, Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as error:
        raise ConfigError(
            path="<yaml>",
            expected="valid YAML syntax with unique mapping keys",
            actual="invalid YAML",
            cause=type(error).__name__,
            source_file=str(resolved_path),
        ) from error
    except OSError as error:
        raise ConfigError(
            path="<root>",
            expected="readable YAML file",
            actual=type(error).__name__,
            source_file=str(resolved_path),
        ) from error

    if raw_config is None:
        raise ConfigError(
            path="<root>",
            expected="non-empty object",
            actual="empty",
            source_file=str(resolved_path),
        )
    if not isinstance(raw_config, dict):
        raise ConfigError(
            path="<root>",
            expected="object",
            actual=type(raw_config).__name__,
            source_file=str(resolved_path),
        )
    try:
        return require_mapping(raw_config, "<root>")
    except ConfigError as error:
        raise error.with_source(str(resolved_path)) from error


def load_config_bundle(
    config_path: str | Path | None = None,
) -> ConfigSourceBundle:
    """Load a legacy file or merge a strict top-level ownership manifest."""

    root_path, directory_input = resolve_config_entry(config_path)
    root_values = load_raw_config(root_path)
    if "imports" not in root_values:
        if directory_input or root_path.name == MANIFEST_FILE_NAME:
            raise ConfigError(
                path="imports",
                expected="manifest imports mapping",
                actual="missing",
                source_file=str(root_path),
            )
        return ConfigSourceBundle(
            root_path=root_path,
            values=MappingProxyType(dict(root_values)),
            source_by_top_level_key=MappingProxyType(
                {key: root_path for key in root_values}
            ),
        )
    return _load_manifest_bundle(root_path, root_values)


def _load_manifest_bundle(
    manifest_path: Path,
    manifest_values: dict[str, Any],
) -> ConfigSourceBundle:
    extra_manifest_keys = set(manifest_values) - {"imports"}
    if extra_manifest_keys:
        key = sorted(extra_manifest_keys)[0]
        raise ConfigError(
            path=key,
            expected="manifest containing only imports",
            actual="mixed regular setting",
            source_file=str(manifest_path),
        )

    imports = _manifest_imports(manifest_path, manifest_values["imports"])
    missing = REQUIRED_TOP_LEVEL_KEYS - set(imports)
    if missing:
        key = sorted(missing)[0]
        raise ConfigError(
            path=f"imports.{key}",
            expected="required top-level key assignment",
            actual="missing",
            source_file=str(manifest_path),
        )

    assigned_by_file: dict[Path, set[str]] = defaultdict(set)
    for key, imported_path in imports.items():
        assigned_by_file[imported_path].add(key)

    cache: dict[Path, dict[str, Any]] = {}
    for imported_path, assigned_keys in assigned_by_file.items():
        if imported_path == manifest_path:
            raise ConfigError(
                path=f"imports.{sorted(assigned_keys)[0]}",
                expected="acyclic import path",
                actual=f"circular import: {manifest_path}",
                source_file=str(manifest_path),
            )
        imported = load_raw_config(imported_path)
        cache[imported_path] = imported
        if "imports" in imported:
            raise ConfigError(
                path="imports",
                expected="imported file without nested imports",
                actual=f"nested or circular import via {imported_path}",
                source_file=str(imported_path),
            )

        unexpected = set(imported) - assigned_keys
        if unexpected:
            key = sorted(unexpected)[0]
            raise ConfigError(
                path=f"imports.{sorted(assigned_keys)[0]}",
                expected="imported file containing only assigned top-level keys",
                actual=f"unexpected key {key}",
                source_file=str(imported_path),
            )
        absent = assigned_keys - set(imported)
        if absent:
            key = sorted(absent)[0]
            raise ConfigError(
                path=f"imports.{key}",
                expected=f"imported file containing top-level key {key}",
                actual="missing key",
                source_file=str(imported_path),
            )

    merged: dict[str, Any] = {}
    sources: dict[str, Path] = {}
    for key, imported_path in imports.items():
        if key in merged:
            raise ConfigError(
                path=f"imports.{key}",
                expected="single top-level owner",
                actual="duplicate ownership",
                source_file=str(manifest_path),
            )
        merged[key] = cache[imported_path][key]
        sources[key] = imported_path

    return ConfigSourceBundle(
        root_path=manifest_path,
        values=MappingProxyType(merged),
        source_by_top_level_key=MappingProxyType(sources),
    )


def _manifest_imports(
    manifest_path: Path,
    value: object,
) -> dict[str, Path]:
    try:
        raw_imports = require_mapping(value, "imports")
    except ConfigError as error:
        raise error.with_source(str(manifest_path)) from error

    imports: dict[str, Path] = {}
    for key, raw_path in raw_imports.items():
        if key in RESERVED_TOP_LEVEL_KEYS:
            raise ConfigError(
                path=f"imports.{key}",
                expected="key integrated into AppConfig before manifest import",
                actual="reserved key is not importable yet",
                source_file=str(manifest_path),
            )
        if key not in IMPORTABLE_TOP_LEVEL_KEYS:
            raise ConfigError(
                path=f"imports.{key}",
                expected="known AppConfig top-level key",
                actual="unknown key",
                source_file=str(manifest_path),
            )
        try:
            import_value = require_string_value(raw_path, f"imports.{key}")
        except ConfigError as error:
            raise error.with_source(str(manifest_path)) from error
        imported_path = Path(import_value).expanduser()
        if not imported_path.is_absolute():
            imported_path = manifest_path.parent / imported_path
        imports[key] = imported_path.resolve()
    return imports
