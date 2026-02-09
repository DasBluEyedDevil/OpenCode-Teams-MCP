"""Entry point for running opencode-teams as a module.

Forces unbuffered stdout/stderr on Windows to prevent MCP stdio hanging.
"""
import sys
import os

# Force unbuffered output BEFORE importing anything else
# This is critical for MCP stdio transport on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(
        open(sys.stdout.fileno(), 'wb', buffering=0),
        write_through=True
    )
    sys.stderr = io.TextIOWrapper(
        open(sys.stderr.fileno(), 'wb', buffering=0),
        write_through=True
    )
    # Also set environment variable for any subprocesses
    os.environ['PYTHONUNBUFFERED'] = '1'

def main():
    """Entry point that ensures unbuffered I/O before running server."""
    # Import here AFTER unbuffered setup
    from opencode_teams.server import main as server_main
    server_main()


if __name__ == "__main__":
    main()
