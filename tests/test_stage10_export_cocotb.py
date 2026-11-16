import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.stage10_sample_parity.export_cocotb import export_run


class Stage10CocotbExportTests(unittest.TestCase):
    def test_exports_all_manifest_cases_and_normalizes_xml_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            output = Path(temporary) / "public"
            root.mkdir()
            cases = []
            for case in range(8):
                folder = root / f"case-{case}"
                (folder / "traces").mkdir(parents=True)
                (folder / "replay.json").write_text(json.dumps({"case": case}))
                (folder / "process.exit").write_text("0\n")
                (folder / "traces" / f"trace-{case}.json").write_text("{}\n")
                ET.ElementTree(ET.fromstring(
                    f'<testsuites><testsuite><testcase file="/tmp/test_{case}.py" /></testsuite></testsuites>'
                )).write(folder / "results.xml", encoding="utf-8")
                cases.append({"case": case, "run_status": "PASS", "process_exit_code": 0, "xml_passed": True})
            (root / "manifest.json").write_text(json.dumps({"cases": cases}))

            report = export_run(root, output)

            self.assertEqual([item["case"] for item in report["cases"]], list(range(8)))
            for case in range(8):
                folder = output / f"cocotb-case-{case}"
                self.assertTrue((folder / "replay.json").is_file())
                self.assertTrue((folder / f"trace-{case}.json").is_file())
                testcase = ET.parse(folder / "results.xml").find(".//testcase")
                self.assertEqual(testcase.get("file"), f"tools/test_{case}.py")

    def test_refuses_failed_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            output = Path(temporary) / "public"
            root.mkdir()
            (root / "manifest.json").write_text(json.dumps({"cases": [
                {"case": 0, "run_status": "FAIL", "process_exit_code": 1, "xml_passed": False}
            ]}))
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "failed Cocotb cases"):
                export_run(root, output)


if __name__ == "__main__":
    unittest.main()
