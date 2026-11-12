from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.stage07_clustering import (
    dbscan,
    extract_features,
    hierarchical_split,
    load_bin_ids,
    write_outputs,
)


class Stage07ClusteringTests(unittest.TestCase):
    def test_feature_vector_extraction_preserves_reference_dimensions(self):
        features = extract_features(
            "aon_timer_pkg::timer_cfg_cg||variable||bark_thold_cp||name:bark[0]||0"
        )
        self.assertEqual(
            set(features),
            {
                "namespace",
                "component",
                "method_type",
                "primary_param",
                "secondary_param",
                "tertiary_param",
                "numeric_param",
                "structure_type",
            },
        )
        self.assertEqual(features["primary_param"], hash("0") % 50)

    def test_dbscan_groups_density_connected_points_and_marks_noise(self):
        labels = dbscan([(0.0,), (0.1,), (0.2,), (5.0,)], eps=0.15, min_samples=2)
        self.assertEqual(labels[:3], [0, 0, 0])
        self.assertEqual(labels[3], -1)

    def test_hierarchical_split_assigns_every_identity_once(self):
        identities = [f"scope::covergroup||variable||cp_{i}||name:value||0" for i in range(12)]
        clusters = hierarchical_split(identities, max_cluster_size=3)
        flattened = [identity for members in clusters.values() for identity in members]
        self.assertCountEqual(flattened, identities)
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_input_rejects_empty_or_duplicate_identity_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ids.txt"
            path.write_text("one\none\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicates"):
                load_bin_ids(path)
            path.write_text("one\n\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "blank"):
                load_bin_ids(path)

    def test_outputs_are_traceable_and_do_not_invent_coverage_scores(self):
        identities = ["scope::cg||variable||cp||name:a||0", "scope::cg||variable||cp||name:b||0"]
        clusters = {"Cluster_0": identities}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "ids.txt"
            input_path.write_text("\n".join(identities) + "\n", encoding="utf-8")
            output_dir = root / "out"
            audit = write_outputs(
                identities,
                clusters,
                input_path=input_path,
                output_dir=output_dir,
                max_cluster_size=256,
                seed=0,
                replay_deterministic=True,
                mapping_sha256="a" * 64,
            )
            self.assertTrue(audit["assignment_complete"])
            self.assertFalse(audit["coverage_scores_generated"])
            self.assertTrue((output_dir / "bin_to_cluster.csv").is_file())
            self.assertTrue((output_dir / "clusters.json").is_file())
            self.assertTrue((output_dir / "scheduler_input.json").is_file())
            scheduler = json.loads((output_dir / "scheduler_input.json").read_text(encoding="utf-8"))
            self.assertFalse(scheduler["allowed_to_schedule"])
            self.assertEqual(scheduler["status"], "BLOCKED_WAITING_EXACT_VECTORS")
            self.assertIn("partial vectors leave omitted bins unknown", scheduler["blockers"][0])
            self.assertIn("Known hits alone do not establish misses", scheduler["blockers"][1])
            with (output_dir / "bin_to_cluster.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["feature_name"] for row in rows], identities)
            self.assertFalse((output_dir / "bin_information_scores.csv").exists())


if __name__ == "__main__":
    unittest.main()
