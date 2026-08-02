import pytest


def test_production_rejects_configured_test_sandbox_data_root():
    import main

    with pytest.raises(RuntimeError, match="test_sandbox"):
        main._validate_data_root_contract(
            {"mode": "production", "data_prefix": "data/test_sandbox/stale"},
            sandbox_mode="production",
        )


def test_test_runner_effective_sandbox_is_allowed_even_with_production_base_config():
    import main

    main._validate_data_root_contract(
        {"mode": "production", "data_prefix": "data/test_sandbox/session"},
        sandbox_mode="test",
    )
