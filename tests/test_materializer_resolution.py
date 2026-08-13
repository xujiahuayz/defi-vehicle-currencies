"""Every declared materializer must resolve identically under any invocation.

The liquidity registry declares one ``module:callable`` reference per ready
capability.  Most name a ``ddvc.*`` library callable, but the constant-product
deposited-capital contract names the ``scripts.build_pool_capital_panel``
entrypoint.  That module is importable by name only when the repository root is
on the import path, which ``./scripts/run`` arranges and a bare
``python scripts/x.py`` does not.  The findings-freeze audit validates these
references, so a launch-dependent verdict would make the gate itself unreliable.
"""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

from ddvc.liquidity import LIQUIDITY_CONTRACTS, resolve_materializer


ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"


class MaterializerResolutionTests(unittest.TestCase):
    def test_every_ready_capability_resolves_to_a_callable(self) -> None:
        unresolved: list[str] = []
        for (venue, family), contract in LIQUIDITY_CONTRACTS.items():
            for capability in contract.capabilities:
                if not (capability.ready and capability.materializer):
                    continue
                try:
                    self.assertTrue(callable(resolve_materializer(capability.materializer)))
                except (ImportError, ValueError) as exc:
                    unresolved.append(f"{venue}/{family}:{capability.quantity_kind}: {exc}")
        self.assertEqual(unresolved, [])

    def test_entrypoint_reference_resolves_without_the_repository_root_importable(self) -> None:
        """Reproduce the bare-script launch: sys.path[0] is scripts/, not the root."""

        code = (
            "import json, sys\n"
            "from ddvc.liquidity import resolve_materializer\n"
            "resolved = resolve_materializer('scripts.build_pool_capital_panel:main')\n"
            "print(json.dumps({'name': resolved.__name__, 'module': resolved.__module__,"
            " 'root_importable': str(sys.argv[1]) in sys.path}))\n"
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in ("PYTHONPATH", "PYTHONSAFEPATH")
        }
        completed = subprocess.run(
            [str(VENV_PYTHON), "-c", code, str(ROOT)],
            cwd=ROOT / "scripts",
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        resolved = json.loads(completed.stdout)
        self.assertFalse(resolved["root_importable"], "the launch under test must not see the root")
        self.assertEqual(resolved["name"], "main")
        self.assertEqual(resolved["module"], "scripts.build_pool_capital_panel")

    def test_missing_module_and_missing_attribute_still_fail(self) -> None:
        with self.assertRaises(ImportError):
            resolve_materializer("scripts.no_such_entrypoint_module:main")
        with self.assertRaises(ImportError):
            resolve_materializer("ddvc.no_such_module:main")
        with self.assertRaises(ValueError):
            resolve_materializer("ddvc.liquidity:no_such_callable")
        with self.assertRaises(ValueError):
            resolve_materializer("ddvc.liquidity")
        with self.assertRaises(ValueError):
            resolve_materializer("ddvc.liquidity:LOCAL_DEPTH_COLUMN")
