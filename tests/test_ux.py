import pytest
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from forge.cli import app
from forge.chat import ForgeChat

runner = CliRunner()

def test_default_launches_chat():
    """Test that running 'forge' with no args launches the chat session."""
    with patch("forge.chat.ForgeChat.start", return_value=None) as mock_start:
        result = runner.invoke(app, [])
        # Typer might return exit code 0 if it successfully called the callback
        assert mock_start.called

def test_chat_command_launches_chat():
    """Test that running 'forge chat' launches the chat session."""
    with patch("forge.chat.ForgeChat.start", return_value=None) as mock_start:
        result = runner.invoke(app, ["chat"])
        assert mock_start.called

@pytest.mark.asyncio
async def test_handle_command_history():
    """Test that /history command logic works."""
    chat = ForgeChat()
    chat.session = MagicMock()
    chat.session.history.get_strings.return_value = ["test prompt 1", "test prompt 2"]
    
    with patch("forge.chat.console.print") as mock_print:
        await chat.handle_command("/history")
        # Check if it printed history header
        mock_print.assert_any_call("\n[bold]Chat History:[/bold]")

@pytest.mark.asyncio
async def test_image_attachment_logic():
    """Test that /image command correctly encodes and stores image info."""
    chat = ForgeChat()
    
    # Mock os.path.exists and open to simulate a file
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", MagicMock()), \
         patch("base64.b64encode", return_value=b"base64data"), \
         patch("mimetypes.guess_type", return_value=("image/png", None)):
        
        await chat.handle_command("/image test.png")
        assert len(chat.attachments) == 1
        assert chat.attachments[0]["name"] == "test.png"
        assert chat.attachments[0]["data"] == "base64data"

def test_thinking_display_render():
    """Test that ThinkingDisplay renders without error."""
    from forge.ui.console import ThinkingDisplay
    thinking = ThinkingDisplay(initial_provider="Gemini")
    thinking.update(status="Testing...", failed_provider="Groq")
    
    # Just check if __rich__ returns a renderable
    renderable = thinking.__rich__()
    assert renderable is not None

def test_header_display():
    """Test that display_header doesn't crash."""
    from forge.ui.console import display_header
    # Just call it and see if it runs (it uses console.print which might need mocking if we wanted to check output)
    with patch("forge.ui.console.console.print") as mock_print:
        display_header("auto", "Gemini", 5)
        assert mock_print.called
