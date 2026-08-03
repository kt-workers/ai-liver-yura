from pathlib import Path

import yaml


def test_input_meaning_lab_blueprint_is_isolated_and_uses_secret_placeholders() -> None:
    blueprint_path = Path("render.input-meaning-lab.yaml")
    blueprint = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))

    services = blueprint["services"]
    assert len(services) == 1

    service = services[0]
    assert service["name"] == "yura-input-meaning-lab"
    assert service["type"] == "web"
    assert service["runtime"] == "python"
    assert service["plan"] == "free"
    assert service["branch"] == "test/input-meaning-cloud-validation"
    assert service["healthCheckPath"] == "/health"
    assert "cloud_validation.input_meaning_lab:app" in service["startCommand"]

    env_vars = {item["key"]: item for item in service["envVars"]}
    for secret_name in (
        "YURA_INPUT_MEANING_LAB_MODEL",
        "OPENAI_API_KEY",
        "YURA_LAB_USERNAME",
        "YURA_LAB_PASSWORD",
    ):
        assert env_vars[secret_name] == {"key": secret_name, "sync": False}
