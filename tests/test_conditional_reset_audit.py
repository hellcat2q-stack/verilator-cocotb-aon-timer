from __future__ import annotations

import tempfile
import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.audit_conditional_reset import PINNED_REVISION, REQUIRED_FILES, audit_source_tree


class ConditionalResetAuditTests(unittest.TestCase):
    def _audit_fixture(self, root):
        hashes = {relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
                  for relative in REQUIRED_FILES}
        with patch("tools.audit_conditional_reset.PINNED_HASHES", hashes), patch(
                "tools.audit_conditional_reset.subprocess.check_output",
                side_effect=[PINNED_REVISION + "\n", ""]):
            return audit_source_tree(root, PINNED_REVISION)

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
            result = self._audit_fixture(root)
        self.assertEqual(result["status"], "NOT_APPLICABLE_NUM_EDN_ZERO")
        self.assertEqual(result["num_edn"]["override_sites"], [])
        self.assertTrue(result["guards"]["covergroup_instantiation_present"])
        self.assertTrue(result["guards"]["sample_task_guard_present"])

    def test_num_edn_override_keeps_audit_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_tree(root, "  num_edn = 1;\n")
            result = self._audit_fixture(root)
        self.assertEqual(result["status"], "REQUIRES_RUNTIME_CONFIG_AUDIT")
        self.assertTrue(result["num_edn"]["override_sites"])

    def test_missing_sampling_guard_cannot_be_marked_inapplicable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_tree(root)
            (root / REQUIRED_FILES[3]).write_text("// no guard\n")
            result = self._audit_fixture(root)
        self.assertEqual(result["status"], "REQUIRES_RUNTIME_CONFIG_AUDIT")

    def test_labeling_another_tree_with_pinned_revision_does_not_verify_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_tree(root)
            with patch("tools.audit_conditional_reset.subprocess.check_output",
                       side_effect=[PINNED_REVISION + "\n", ""]):
                result = audit_source_tree(root, PINNED_REVISION)
        self.assertFalse(result["source_provenance_verified"])
        self.assertEqual(len(result["mismatched_source_hashes"]), 4)
        self.assertEqual(result["status"], "REQUIRES_RUNTIME_CONFIG_AUDIT")


if __name__ == "__main__":
    unittest.main()
