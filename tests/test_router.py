import pytest
from unittest.mock import AsyncMock, MagicMock
from forge_core.router.engine import RouterEngine
from forge_core.providers.base import ProviderResponse

@pytest.mark.asyncio
async def test_router_fallback():
    # Setup mocks
    router = RouterEngine()
    
    # Mock providers
    p1 = MagicMock()
    p1.name = "p1"
    p1.priority = 1
    p1.check_health = AsyncMock(return_value={"ok": True})
    p1.generate = AsyncMock(side_effect=ValueError("P1 Failed"))
    
    p2 = MagicMock()
    p2.name = "p2"
    p2.priority = 2
    p2.check_health = AsyncMock(return_value={"ok": True})
    p2.generate = AsyncMock(return_value=ProviderResponse("p2", "Success from P2"))
    
    router.providers = [p1, p2]
    
    response = await router.route("test prompt")
    
    assert response.provider == "p2"
    assert response.content == "Success from P2"
    p1.generate.assert_called_once()
    p2.generate.assert_called_once()

@pytest.mark.asyncio
async def test_router_preferred_model():
    router = RouterEngine()
    
    p1 = MagicMock()
    p1.name = "p1"
    p1.priority = 1
    p1.check_health = AsyncMock(return_value={"ok": True})
    p1.generate = AsyncMock(return_value=ProviderResponse("p1", "Success from P1"))
    
    p2 = MagicMock()
    p2.name = "p2"
    p2.priority = 2
    p2.check_health = AsyncMock(return_value={"ok": True})
    p2.generate = AsyncMock(return_value=ProviderResponse("p2", "Success from P2"))
    
    router.providers = [p1, p2]
    
    # Force p2
    response = await router.route("test prompt", preferred="p2")
    
    assert response.provider == "p2"
    p1.generate.assert_not_called()
    p2.generate.assert_called_once()

@pytest.mark.asyncio
async def test_all_providers_fail():
    router = RouterEngine()
    
    p1 = MagicMock()
    p1.name = "p1"
    p1.priority = 1
    p1.check_health = AsyncMock(return_value={"ok": True})
    p1.generate = AsyncMock(side_effect=ValueError("Fail"))
    
    router.providers = [p1]
    
    with pytest.raises(ValueError, match="All providers failed"):
        await router.route("test prompt")
