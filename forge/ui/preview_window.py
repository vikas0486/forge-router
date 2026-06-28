"""
Forge Preview Window — runs as a subprocess.

Launches a native macOS WKWebView window (via pywebview) pointing at the
forge preview HTTP server. Must run as __main__ because pywebview requires
the UI on the process's main thread.

The parent forge chat process launches this as:
    python -m forge.ui.preview_window http://localhost:7654
"""
import sys


def main():
    try:
        import webview
    except ImportError:
        print("[forge preview] pywebview not installed — run: uv add pywebview", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:7654"

    window = webview.create_window(
        title="⚒ Forge Preview",
        url=url,
        width=980,
        height=740,
        resizable=True,
        min_size=(560, 400),
        background_color="#0d1117",   # matches our dark theme — no white flash on load
    )

    # start() blocks until the window is closed (X button or Cmd+W)
    # when the user closes it this subprocess exits cleanly
    webview.start(debug=False)


if __name__ == "__main__":
    main()
