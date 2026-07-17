"""Phase 0 guarantee: forge_core is importable with zero CLI/UI dependencies."""
import subprocess
import sys


def test_forge_core_public_api():
    from forge_core import router, RouterEngine, RoutingContext, settings, ProviderResponse
    assert isinstance(router, RouterEngine)
    assert len(router.providers) == 11
    ctx = router.new_context("write a function")
    assert isinstance(ctx, RoutingContext)
    assert ctx.intent == "code"


def test_forge_core_has_no_cli_imports():
    """forge_core must never import the forge CLI/UI package."""
    code = (
        "import sys, forge_core; "
        "bad = [m for m in sys.modules if m == 'forge' or m.startswith('forge.')]; "
        "assert not bad, f'forge_core pulled in CLI modules: {bad}'"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
