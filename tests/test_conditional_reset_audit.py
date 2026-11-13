from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.audit_conditional_reset import REQUIRED_FILES, audit_source_tree


class ConditionalResetAuditTests(unittest.TestCase):
    def _write_tree(self, root: Path, env_cfg: str = "") -> None:
        files = {
            REQUIRED_FILES[0]: "class cip_base_env_cfg; uint num_edn; endclass\n",
            REQUIRED_FILES[1]: "class aon_timer_env_cfg;\n" + env_cfg + "endclass\n",
            REQUIRED_FILES[2]: 'if (cfg.num_edn) resets_cg = new("dut_and_edn_rsts");\n',
            REQUIRED_FILES[3]: "if (cfg.num_edn && cfg.en_cov) begin\nend\n",
        }
        for relative, text in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def test_zero_num_edn_is_audited_from_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_tree(root)
            result = audit_source_tree(root, "rev")
        self.assertEqual(result["status"], "NOT_APPLICABLE_NUM_EDN_ZERO")
        self.assertEqual(result["num_edn"]["override_sites"], [])
        self.assertTrue(result["guards"]["covergroup_instantiation_present"])
        self.assertTrue(result["guards"]["sample_task_guard_present"])

    def test_num_edn_override_keeps_audit_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_tree(root, "  num_edn = 1;\n")
            result = audit_source_tree(root, "rev")
        self.assertEqual(result["status"], "REQUIRES_RUNTIME_CONFIG_AUDIT")
        self.assertTrue(result["num_edn"]["override_sites"])


if __name__ == "__main__":
    unittest.main()
