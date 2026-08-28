from pathlib import Path


def test_product_packages_and_app_entrypoint_do_not_depend_on_loop_engine() -> None:
    root = Path(__file__).resolve().parents[3]
    product_paths = [
        root / "app" / "runtime",
        root / "app" / "domain",
        root / "app" / "usecases",
        root / "app" / "adapters",
        root / "app" / "infrastructure",
        root / "app" / "__main__.py",
    ]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for item in product_paths
        for path in (item.rglob("*.py") if item.is_dir() else (item,))
    )
    assert "tools.loop_engine" not in source


def test_loop_engine_is_outside_app_and_old_operations_module_is_absent() -> None:
    root = Path(__file__).resolve().parents[3]
    assert (root / "tools" / "loop_engine" / "supervisor.py").is_file()
    assert not (root / "app" / "operations" / "mission_supervisor.py").exists()
    assert not (root / "app" / "operations").exists()
