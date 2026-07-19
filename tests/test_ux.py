import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace
from typer.testing import CliRunner
from forge.cli import app
from forge.chat import ForgeChat
from forge_core.providers.base import ProviderResponse, UsageInfo

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


@pytest.mark.asyncio
async def test_bye_prints_goodbye_once():
    """Typing bye should exit cleanly and print the farewell once."""
    chat = ForgeChat()
    chat.session = SimpleNamespace(prompt_async=AsyncMock(return_value="bye"))

    with patch("forge.chat.display_welcome"), \
         patch("forge.chat.display_header"), \
         patch("forge.chat.preview.shutdown"), \
         patch("forge.chat.console.print") as mock_print:
        await chat.start()

    goodbye_calls = [
        call for call in mock_print.call_args_list
        if call.args and call.args[0] == "[info]Goodbye! 👋[/info]"
    ]
    assert len(goodbye_calls) == 1


@pytest.mark.asyncio
async def test_usage_persisted_and_reported(tmp_path):
    """A routed chat turn should persist usage and keep provider-reported counts."""
    usage_file = tmp_path / "session-usage.jsonl"
    chat = ForgeChat()
    chat.session = SimpleNamespace(prompt_async=AsyncMock(side_effect=["hello", "bye"]))

    response = ProviderResponse(
        provider="groq",
        content="hello back",
        model="llama",
        usage=UsageInfo.from_counts(14, 6, 20, estimated=False),
    )

    with patch("forge.chat.SESSION_USAGE_FILE", usage_file), \
         patch("forge.chat.display_welcome"), \
         patch("forge.chat.display_header"), \
         patch("forge.chat.display_response"), \
         patch("forge.chat.preview.shutdown"), \
         patch("forge.chat.router.route", AsyncMock(return_value=response)):
        await chat.start()

    assert len(chat._usage_entries) == 1
    assert chat._usage_entries[0]["input_tokens"] == 14
    assert chat._usage_entries[0]["output_tokens"] == 6
    assert chat._usage_entries[0]["total_tokens"] == 20
    assert chat._usage_entries[0]["estimated"] is False

    rows = [json.loads(line) for line in usage_file.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["provider"] == "groq"
    assert rows[0]["total_tokens"] == 20
    assert rows[0]["estimated"] is False


def test_usage_total_reads_persisted_log(tmp_path):
    """`/usage total` should aggregate persisted session usage across sessions."""
    usage_file = tmp_path / "session-usage.jsonl"
    usage_file.write_text(
        json.dumps({
            "session_id": "s1", "turn": 1, "provider": "groq",
            "input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "estimated": False,
        }) + "\n" +
        json.dumps({
            "session_id": "s2", "turn": 1, "provider": "claude",
            "input_tokens": 4, "output_tokens": 6, "total_tokens": 10, "estimated": True,
        }) + "\n"
    )

    chat = ForgeChat()
    with patch("forge.chat.SESSION_USAGE_FILE", usage_file), \
         patch("forge.chat.console.print") as mock_print:
        chat._print_usage_total()

    printed = "\n".join(call.args[0] for call in mock_print.call_args_list if call.args)
    assert "Sessions        : 2" in printed
    assert "Turns           : 2" in printed
    assert "Total tokens    : 25" in printed
    assert "1 reported / 1 estimated" in printed


@pytest.mark.asyncio
async def test_uses_alias_shows_session_usage():
    """`/uses` should behave the same as `/usage`."""
    chat = ForgeChat()
    chat._usage_entries = [{
        "turn": 1,
        "provider": "groq",
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "estimated": False,
        "session_id": "s1",
    }]

    with patch("forge.chat.console.print") as mock_print:
        await chat.handle_command("/uses")

    printed = "\n".join(call.args[0] for call in mock_print.call_args_list if call.args)
    assert "Session Usage" in printed
    assert "groq" in printed
