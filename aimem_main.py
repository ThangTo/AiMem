#!/usr/bin/env python3
"""AiMem entry point - allows running aimem from source without installing."""

import sys
import io
from pathlib import Path

# Fix Unicode output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from aimem.cli import main

if __name__ == "__main__":
    main()