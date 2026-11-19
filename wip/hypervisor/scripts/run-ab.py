"""Runs this worktree's ab.py as if it were the main checkout's: ab.py finds its run folders, config
copies and tools next to its own file, and those exist only in the main checkout.

    cd MAIN/emulator/debugsrv && ../mvk-mesh/verify/verify.py with-lock -- \
        uv run -q --with pillow --with numpy python WORKTREE/emulator/hvf-race/run-ab.py SPEC.json

Not needed once this branch's ab.py is merged into the main checkout.
"""
import sys
from pathlib import Path

MAIN = Path("OLD_REPO/emulator/debugsrv")
source = Path(__file__).resolve().parents[1] / "debugsrv" / "ab.py"
sys.path.insert(0, str(MAIN))
sys.path.insert(0, str(source.parent))   # modules that exist only in this worktree (speckhunt, whitecount)
exec(compile(source.read_text(), str(MAIN / "ab.py"), "exec"),
     {"__file__": str(MAIN / "ab.py"), "__name__": "__main__"})
