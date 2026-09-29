"""Executor mínimo (para ambientes sem pytest). Com pytest: `pytest tests/`."""
import importlib
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
MODULES = sys.argv[1:] or ["test_parsers", "test_analytics", "test_pipeline_pg", "test_api_sql"]
failed = passed = 0
for name in MODULES:
    mod = importlib.import_module(name)
    if hasattr(mod, "setup_module"):
        mod.setup_module()
    for fn in sorted(k for k in dir(mod) if k.startswith("test_")):
        t = time.time()
        try:
            getattr(mod, fn)()
            passed += 1
            print(f"  ✓ {name}.{fn} ({time.time() - t:.1f}s)")
        except Exception:
            failed += 1
            print(f"  ✗ {name}.{fn}")
            traceback.print_exc()
print(f"\n{passed} passaram, {failed} falharam")
sys.exit(1 if failed else 0)
