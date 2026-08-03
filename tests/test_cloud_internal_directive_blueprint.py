from pathlib import Path

import yaml


def test_internal_directive_lab_blueprint_is_isolated_and_uses_secrets() -> None:
    blueprint_path = Path("render.internal-directive-lab.yaml")
    blueprint = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))

    services = blueprint["services"]
    assert len(services) == 1

    service = services[0]
    assert service["name"] == "yura-internal-directive-lab"
    assert service["type"] == "web"
    assert service["runtime"] == "python"
    assert service["plan"] == "free"
    assert service["branch"] == "test/internal-directive-cloud-validation"
    assert service["healthCheckPath"] == "/health"
    assert (
        "cloud_validation.internal_directive_lab_compact:app"
        in service["startCommand"]
    )

    env_vars = {item["key"]: item for item in service["envVars"]}
    for secret_name in (
        "YURA_INTERNAL_DIRECTIVE_LAB_MODEL",
        "OPENAI_API_KEY",
        "YURA_LAB_USERNAME",
        "YURA_LAB_PASSWORD",
    ):
        assert env_vars[secret_name] == {"key": secret_name, "sync": False}
