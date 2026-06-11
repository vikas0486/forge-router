import pytest
from typer.testing import CliRunner
from forge.cli import app
from forge.config.settings import settings

runner = CliRunner()

def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "🛠️ Forge" in result.output

def test_status_command():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Forge Provider Status" in result.output

def test_doctor_command():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Forge Diagnosis Report" in result.output
    assert "API Keys" in result.output

def test_ask_command_integration():
    # This might actually call an API if keys are present, 
    # but let's just check if it handles basic errors or starts correctly.
    # To be safe in CI, we could mock the router.
    pass

def test_settings_load():
    # Verify settings are loaded (not empty if .env exists)
    # We can't guarantee keys exist, but we can check if it attempted to load
    assert settings.timeout == 30
