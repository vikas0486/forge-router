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


def test_auto_load_local_file(tmp_path):
    """A real file path in the prompt is read locally and injected into context."""
    chat = ForgeChat()
    f = tmp_path / "notes.md"
    f.write_text("forge auto-load bridge test content")
    with patch("forge.chat.console.print"):
        chat._auto_load_paths(f"Can you read my local file? {f}")
    assert any(item["path"] == str(f) for item in chat._context_files)
    assert "auto-load bridge test content" in chat._build_file_prefix()


def test_auto_load_ignores_nonexistent_paths():
    """Paths that don't exist on disk are never loaded."""
    chat = ForgeChat()
    with patch("forge.chat.console.print"):
        chat._auto_load_paths("look at /no/such/path/here.py please")
    assert chat._context_files == []


def test_auto_load_skips_binary(tmp_path):
    """Binary files are skipped, not injected as garbage context."""
    chat = ForgeChat()
    b = tmp_path / "blob.bin"
    b.write_bytes(b"\x00\x01\x02binary")
    with patch("forge.chat.console.print"):
        chat._auto_load_paths(f"read {b}")
    assert chat._context_files == []


def test_visual_prompt_detection():
    """Prompts asking for visuals should trigger the preview, plain ones not."""
    from forge.chat import _wants_visual
    for p in ("draw a diagram of a fish", "make some ascii art", "generate an image of a cat",
              "Draw a mermaid flowchart", "create a video intro", "sketch the architecture",
              "show me a photo", "plot the latency graph", "show the system architecture",
              "draw a UML sequence diagram", "render this in graphviz", "show this as plantuml",
              "draw this in d2"):
        assert _wants_visual(p), p
    for p in ("explain the routing engine", "fix this bug", "hello how are you",
              "write a bash script"):
        assert not _wants_visual(p), p


def test_visual_content_detection():
    """Visual output detection should catch diagram and SVG formats that the preview can render."""
    from forge.chat import _has_visual
    assert _has_visual("```mermaid\nflowchart TD\nA-->B\n```")
    assert _has_visual("```Mermaid\r\nflowchart TD\r\nA-->B\r\n```")
    assert _has_visual("```graphviz\ndigraph G { A -> B }\n```")
    assert _has_visual("```plantuml\n@startuml\nA -> B\n@enduml\n```")
    assert _has_visual("```svg\n<svg viewBox='0 0 10 10'></svg>\n```")
    assert _has_visual("<svg viewBox='0 0 10 10'></svg>")
    assert not _has_visual("plain markdown without diagrams")
