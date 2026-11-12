"""Build deterministic semantic clusters for the canonical AON Timer bins.

This is a standard-library port of the selected ``dbscan_clustering_new2``
algorithm in the caller-provided reference repository.  It intentionally
clusters bin identities only.  Coverage-derived information scores and UCB
priors require validated 0/1 run vectors and are not fabricated here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import re
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BIN_IDS = ROOT / "references" / "canonical_bin_ids.txt"
DEFAULT_OUTPUT_DIR = ROOT / "evidence" / "stage07_initial"
ALGORITHM_ID = "dbscan_clustering_new2_port_v1"
REFERENCE_REPOSITORY = (
    "https://github.com/hellcat2q-stack/opentitan-aon-timer-paper-method-repro"
)
REFERENCE_COMMIT = "ab158f7a600aee4d5eccd009c7292224a26f346b"
REFERENCE_PATH = "07_聚类与信息评分/algorithm_source/dbscan_clustering_new2.py"
MAX_CLUSTER_SIZE_DEFAULT = 256
EPS_SCHEDULE = (0.3, 0.2, 0.15, 0.1)
MIN_SAMPLES = 2
DIMENSION_WEIGHTS = (
    ("namespace", 100),
    ("component", 50),
    ("method_type", 25),
    ("primary_param", 20),
    ("secondary_param", 15),
    ("tertiary_param", 10),
    ("numeric_param", 5),
    ("structure_type", 8),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def estimate_cardinality(param: str) -> int:
    if ":" in param:
        try:
            start, end = (int(part) for part in param.split(":", 1))
            return end - start + 1
        except ValueError:
            return 50
    if param.isdigit():
        value = int(param)
        if value < 10:
            return 10
        if value < 100:
            return 50
        return 100
    if re.match(r"^[A-Za-z]+\d*$", param):
        return 5
    return 30


def classify_param_type(param: str) -> str:
    if param.isdigit():
        return "numeric"
    if ":" in param:
        return "range"
    if re.match(r"^[A-Za-z]+\d*$", param):
        return "categorical"
    return "mixed"


def extract_features(name: str) -> dict[str, int]:
    """Port of the selected upstream feature extraction routine."""
    normalized = name.replace("&lt;", "<").replace("&gt;", ">")
    base = normalized.split("-<", 1)[0]
    remainder = base
    namespace = None
    if "::" in base:
        namespace, remainder = base.split("::", 1)

    if "." in remainder:
        component, method_source = remainder.split(".", 1)
    elif "-" in remainder:
        component, method_source = remainder.split("-", 1)
    else:
        component, method_source = remainder, remainder

    if "cross_" in normalized:
        structure = 2
    elif ".cp_" in normalized or "-cp_" in normalized:
        structure = 1
    else:
        structure = 0

    parameters = re.findall(r"\[([^\]]+)\]", normalized)
    analysis = sorted(
        (
            estimate_cardinality(param),
            position,
            param,
            classify_param_type(param),
        )
        for position, param in enumerate(parameters)
    )
    parameter_features = [0, 0, 0, 0]
    for index, (_, _, param, param_type) in enumerate(analysis):
        param_hash = hash(param) % 50
        if index < 3:
            parameter_features[index] = param_hash
        elif param_type == "numeric":
            parameter_features[3] += int(param) // 10
        else:
            parameter_features[3] += param_hash

    method_name = re.split(r"[-<]", method_source, 1)[0] if method_source else ""
    return {
        "namespace": hash(namespace) % 100 if namespace else 0,
        "component": hash(component) % 50 if component else 0,
        "method_type": hash(method_name) % 30 if method_name else 0,
        "primary_param": parameter_features[0],
        "secondary_param": parameter_features[1],
        "tertiary_param": parameter_features[2],
        "numeric_param": parameter_features[3],
        "structure_type": structure,
    }


def build_feature_vector(name: str) -> tuple[float, ...]:
    features = extract_features(name)
    return tuple(float(features[key] * weight) for key, weight in DIMENSION_WEIGHTS)


def standardize(rows: list[tuple[float, ...]]) -> list[tuple[float, ...]]:
    if not rows:
        return []
    width = len(rows[0])
    means = [sum(row[column] for row in rows) / len(rows) for column in range(width)]
    variances = [
        sum((row[column] - means[column]) ** 2 for row in rows) / len(rows)
        for column in range(width)
    ]
    scales = [math.sqrt(value) if value > 0.0 else 1.0 for value in variances]
    return [
        tuple((row[column] - means[column]) / scales[column] for column in range(width))
        for row in rows
    ]


def dbscan(
    rows: list[tuple[float, ...]], *, eps: float, min_samples: int = MIN_SAMPLES
) -> list[int]:
    """Deterministic DBSCAN with Euclidean distance and sklearn-compatible core rules."""
    if eps <= 0 or min_samples < 1:
        raise ValueError("eps must be positive and min_samples must be at least one")
    count = len(rows)
    labels = [-2] * count  # -2 means unvisited; -1 is noise.
    neighbor_cache: dict[int, tuple[int, ...]] = {}
    eps_squared = eps * eps

    def neighbors(index: int) -> tuple[int, ...]:
        cached = neighbor_cache.get(index)
        if cached is not None:
            return cached
        origin = rows[index]
        result = []
        for candidate, point in enumerate(rows):
            distance_squared = sum(
                (left - right) * (left - right) for left, right in zip(origin, point)
            )
            if distance_squared <= eps_squared:
                result.append(candidate)
        cached = tuple(result)
        neighbor_cache[index] = cached
        return cached

    cluster_id = 0
    for index in range(count):
        if labels[index] != -2:
            continue
        seed_neighbors = neighbors(index)
        if len(seed_neighbors) < min_samples:
            labels[index] = -1
            continue

        labels[index] = cluster_id
        queue = deque(seed_neighbors)
        enqueued = set(seed_neighbors)
        while queue:
            candidate = queue.popleft()
            if labels[candidate] == -2:
                labels[candidate] = -1
                candidate_neighbors = neighbors(candidate)
                if len(candidate_neighbors) >= min_samples:
                    for neighbor in candidate_neighbors:
                        if neighbor not in enqueued:
                            queue.append(neighbor)
                            enqueued.add(neighbor)
            if labels[candidate] == -1:
                labels[candidate] = cluster_id
        cluster_id += 1
    return labels


def perform_clustering(
    items: list[str], *, max_cluster_size: int, eps: float, min_samples: int = MIN_SAMPLES
) -> dict[str, list[str]]:
    if len(items) <= max_cluster_size:
        return {"Cluster_0": list(items)}
    vectors = standardize([build_feature_vector(item) for item in items])
    labels = dbscan(vectors, eps=eps, min_samples=min_samples)
    clusters: dict[str, list[str]] = {}
    for item, label in zip(items, labels):
        name = "noise" if label == -1 else f"group_{label}"
        clusters.setdefault(name, []).append(item)
    return clusters


def hierarchical_split(
    items: list[str], *, max_cluster_size: int = MAX_CLUSTER_SIZE_DEFAULT,
    base_id: str = "0", level: int = 0,
) -> dict[str, list[str]]:
    if max_cluster_size < 1:
        raise ValueError("max_cluster_size must be positive")
    if len(items) <= max_cluster_size or level > 3:
        return {f"Cluster_{base_id}": list(items)}

    eps = EPS_SCHEDULE[min(level, len(EPS_SCHEDULE) - 1)]
    split = perform_clustering(items, max_cluster_size=max_cluster_size, eps=eps)
    result: dict[str, list[str]] = {}
    for ordinal, (group_name, members) in enumerate(split.items()):
        current_id = f"{base_id}_{ordinal}" if level > 0 else str(ordinal)
        if group_name == "noise":
            if members:
                result[f"Cluster_{current_id}_noise"] = members
        elif len(members) > max_cluster_size:
            result.update(
                hierarchical_split(
                    members,
                    max_cluster_size=max_cluster_size,
                    base_id=current_id,
                    level=level + 1,
                )
            )
        else:
            result[f"Cluster_{current_id}"] = members
    return result


def cluster_stats(clusters: dict[str, list[str]], max_cluster_size: int) -> dict[str, Any]:
    sizes = [len(members) for members in clusters.values()]
    ordered = sorted(sizes)
    median = (
        float(ordered[len(ordered) // 2])
        if len(ordered) % 2
        else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2.0
    ) if ordered else 0.0
    return {
        "cluster_count": len(sizes),
        "item_count": sum(sizes),
        "min_size": min(sizes) if sizes else 0,
        "max_size": max(sizes) if sizes else 0,
        "mean_size": sum(sizes) / len(sizes) if sizes else 0.0,
        "median_size": median,
        "singleton_count": sum(size == 1 for size in sizes),
        "clusters_over_max_cluster_size": sum(size > max_cluster_size for size in sizes),
    }


def summarize_partitions(items: list[str]) -> dict[str, Any]:
    component_counts: Counter[str] = Counter()
    covergroup_counts: Counter[str] = Counter()
    structure_counts: Counter[str] = Counter()
    coverpoint_counts: Counter[str] = Counter()
    token_counts: Counter[str] = Counter()
    for identity in items:
        namespace, separator, remainder = identity.partition("::")
        if separator:
            component_counts[namespace] += 1
            covergroup, inner_separator, _ = remainder.partition("||")
            if inner_separator:
                covergroup_counts[covergroup] += 1
                fields = identity.split("||")
                if len(fields) >= 2:
                    structure_counts[fields[1]] += 1
                if len(fields) >= 3:
                    coverpoint_counts[fields[2]] += 1
        token_counts.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", identity))
    return {
        "schema": "aon-timer-stage07-partition-v1",
        "key_format": "<scope>::<covergroup>||<variable_or_cross>||<item>||<bin_name>||<instance_index>",
        "bin_count": len(items),
        "unique_component_count": len(component_counts),
        "unique_covergroup_count": len(covergroup_counts),
        "unique_structure_count": len(structure_counts),
        "unique_coverpoint_count": len(coverpoint_counts),
        "top_components": component_counts.most_common(20),
        "top_covergroups": covergroup_counts.most_common(20),
        "structure_counts": dict(sorted(structure_counts.items())),
        "top_coverpoints": coverpoint_counts.most_common(30),
        "top_semantic_tokens": token_counts.most_common(50),
    }


def write_outputs(
    items: list[str], clusters: dict[str, list[str]], *, input_path: Path,
    output_dir: Path, max_cluster_size: int, seed: int,
    replay_deterministic: bool, mapping_sha256: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cluster_names = sorted(clusters)
    mapping = {
        item: cluster_id
        for cluster_id, name in enumerate(cluster_names)
        for item in clusters[name]
    }
    if len(mapping) != len(items) or set(mapping) != set(items):
        raise ValueError("cluster mapping must assign every identity exactly once")

    with (output_dir / "bin_to_cluster.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["feature_name", "cluster_id"])
        for item in items:
            writer.writerow([item, mapping[item]])

    public_clusters = {
        str(cluster_id): {"source_cluster_name": name, "bins": clusters[name]}
        for cluster_id, name in enumerate(cluster_names)
    }
    (output_dir / "clusters.json").write_text(
        json.dumps(public_clusters, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "partition_summary.json").write_text(
        json.dumps(summarize_partitions(items), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    source_hash = sha256_file(Path(__file__))
    input_hash = sha256_file(input_path)
    stats = cluster_stats(clusters, max_cluster_size)
    scheduler_input = {
        "schema": "aon-timer-stage07-scheduler-input-v1",
        "status": "BLOCKED_WAITING_EXACT_VECTORS",
        "allowed_to_schedule": False,
        "cluster_mapping": "bin_to_cluster.csv",
        "cluster_count": len(clusters),
        "canonical_bin_count": len(items),
        "mapping_sha256": mapping_sha256,
        "coverage_state": None,
        "information_scores": None,
        "cluster_priors": None,
        "blockers": [
            "No exact validated run-level coverage vectors are available; partial vectors leave omitted bins unknown.",
            "Known hits alone do not establish misses or the residual uncovered-bin set needed for coverage-based scoring.",
        ],
    }
    (output_dir / "scheduler_input.json").write_text(
        json.dumps(scheduler_input, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    parameters = {
        "schema": "aon-timer-stage07-parameters-v1",
        "algorithm_id": ALGORITHM_ID,
        "algorithm_origin": {
            "repository": REFERENCE_REPOSITORY,
            "commit": REFERENCE_COMMIT,
            "path": REFERENCE_PATH,
            "port_note": "Feature extraction, weights, hierarchical eps schedule, max size and min_samples follow the selected upstream variant; StandardScaler and DBSCAN are implemented with Python standard library only.",
        },
        "input": input_path.name,
        "input_sha256": input_hash,
        "canonical_bin_count": len(items),
        "cluster_source_sha256": source_hash,
        "max_cluster_size": max_cluster_size,
        "min_samples": MIN_SAMPLES,
        "hierarchical_eps_schedule": list(EPS_SCHEDULE),
        "pythonhashseed": seed,
        "coverage_scores_generated": False,
        "coverage_score_blocker": "Exact validated run-level coverage vectors are unavailable; sparse partial vectors leave omitted stage06 cells unknown.",
    }
    (output_dir / "parameters.json").write_text(
        json.dumps(parameters, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    validation = {
        "schema": "aon-timer-stage07-validation-v1",
        "input_sha256": input_hash,
        "input_bin_count": len(items),
        "mapped_bin_count": len(mapping),
        "unique_bin_count": len(set(items)),
        "cluster_count": len(clusters),
        "assignment_complete": len(mapping) == len(items),
        "assignment_unique": len(mapping) == len(set(mapping)),
        "selected_algorithm": ALGORITHM_ID,
        "cluster_stats": stats,
        "coverage_scores_generated": False,
        "host_platform": platform.platform(),
        "python": sys.version.split()[0],
    }
    (output_dir / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    output_names = (
        "bin_to_cluster.csv",
        "clusters.json",
        "partition_summary.json",
        "parameters.json",
        "validation.json",
        "scheduler_input.json",
    )
    sha_lines = [f"{sha256_file(output_dir / name)}  {name}" for name in output_names]
    (output_dir / "sha256.txt").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    audit = {
        "schema": "aon-timer-stage07-audit-v1",
        "input_sha256": input_hash,
        "canonical_bin_count": len(items),
        "cluster_count": len(clusters),
        "assignment_complete": len(mapping) == len(items),
        "assignment_unique": len(mapping) == len(set(mapping)),
        "deterministic_replay": replay_deterministic,
        "mapping_sha256": mapping_sha256,
        "cluster_stats": stats,
        "coverage_scores_generated": False,
        "outputs_sha256": {name: sha256_file(output_dir / name) for name in output_names},
        "limitations": [
            "This artifact groups canonical bin identities only; it is not a coverage result.",
            "Information scores and scheduler priors are withheld until exact validated run vectors and coverage scoring are available.",
        ],
    }
    (output_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return audit


def load_bin_ids(path: Path) -> list[str]:
    raw = Path(path).read_bytes()
    items = raw.decode("utf-8").splitlines()
    if not items or any(not item for item in items):
        raise ValueError("bin identity input must be non-empty and contain no blank lines")
    if len(items) != len(set(items)):
        raise ValueError("bin identity input contains duplicates")
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-ids", type=Path, default=DEFAULT_BIN_IDS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-cluster-size", type=int, default=MAX_CLUSTER_SIZE_DEFAULT)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    hash_seed = os.environ.get("PYTHONHASHSEED", "")
    if hash_seed != str(args.seed):
        parser.error(f"PYTHONHASHSEED must be {args.seed}; got {hash_seed!r}")
    try:
        items = load_bin_ids(args.bin_ids)
        clusters = hierarchical_split(items, max_cluster_size=args.max_cluster_size)
        replay = hierarchical_split(items, max_cluster_size=args.max_cluster_size)
        normalize = lambda value: {
            name: list(members) for name, members in sorted(value.items())
        }
        replay_deterministic = normalize(clusters) == normalize(replay)
        mapping_payload = "\n".join(
            f"{identity}\t{cluster_id}"
            for cluster_id, name in enumerate(sorted(clusters))
            for identity in clusters[name]
        ).encode("utf-8")
        mapping_sha256 = sha256_bytes(mapping_payload)
        audit = write_outputs(
            items,
            clusters,
            input_path=args.bin_ids,
            output_dir=args.output_dir,
            max_cluster_size=args.max_cluster_size,
            seed=args.seed,
            replay_deterministic=replay_deterministic,
            mapping_sha256=mapping_sha256,
        )
        if not replay_deterministic:
            parser.error("repeated clustering replay produced a different mapping")
        print(json.dumps(audit, ensure_ascii=False, indent=2))
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
