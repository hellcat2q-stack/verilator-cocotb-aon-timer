"""Strict offline replay of the eight-case independent fixed-reference matrix."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from tools.stage10_sample_parity.audit import compare_case

ROOT=Path(__file__).resolve().parents[2]
VARIANT="pinned-sampling-fixes-v2"
FIXES=["reset-fork-isolation","wakeup-high-word-read","named-event-wait","reset-local-scoreboard-state"]

def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def require(ok:bool,msg:str)->None:
    if not ok: raise ValueError(msg)

def audit_evidence(root:Path)->dict:
    root=Path(root); read=lambda name:json.loads((root/name).read_text())
    manifest,execution,attest,post,instrument,export=(read(n) for n in (
        "cocotb-manifest.json","execution.json","source-attestation.json","post-build-source.json","instrumentation.json","cocotb-export.json"))
    require(attest["revision"]==manifest["source_revision"]=="9f20940d494a223cc950a5b98f748fb28109d458","pinned revision mismatch")
    require(attest["all_exported_git_blobs_match"] and post["all_source_blobs_match_except_declared_patch"] and manifest["source_clean"],"source attestation failed")
    require(instrument["reference_variant"]==execution["reference_variant"]==manifest["reference_variant"]==VARIANT,"variant mismatch")
    require(instrument["reference_logic_fixes"]==FIXES and instrument["files"]==post["declared_changed_files"],"undeclared reference patch")
    require(execution["build_exit_code"]==execution["runner_exit_code"]==0,"VCS build/runner failed")
    eda_toolchain=execution["eda_python_toolchain"]
    require(eda_toolchain["fusesoc"]==eda_toolchain["fusesoc_cli"]=="0.5.dev0"
        and eda_toolchain["edalize"]=="0.4.0","VCS EDA Python toolchain mismatch")
    require(execution["eda_overlay_archive_sha256"]==execution["inputs_sha256"]["legacy-eda-overlay-v1.tar.gz"],
        "VCS legacy EDA Python overlay archive hash mismatch")
    vcs_compat=execution["vcs_compatibility"]
    require(vcs_compat["wrapper_sha256"]==execution["inputs_sha256"]["vcs_p2019_compat.sh"]
        and vcs_compat["logged_invocation_count"]>0 and vcs_compat["xprop_mmsopt_flags_removed"]>0
        and "GCC) 9.3.1" in vcs_compat["gcc_version"] and "GCC) 9.3.1" in vcs_compat["gxx_version"],
        "VCS 2019 compatibility/GCC invocation provenance mismatch")
    require(instrument["matrix_protocol_sha256"]==sha(ROOT/"configs/stage10-sample-matrix-v1.json"),"matrix protocol hash changed")
    for name,expected in manifest["tools_sha256"].items():require(sha(ROOT/name)==expected,"Cocotb capture tool changed: "+name)
    paths={"instrument.py":"tools/stage10_sample_matrix/instrument.py",
        "sample_fix_base.py":"tools/stage10_sample_fix/instrument.py",
        "instrument_base.py":"tools/stage10_sample_parity/instrument.py",
        "run_vcs.sh":"tools/stage10_sample_matrix/run_vcs.sh",
        "collect_vcs.py":"tools/stage10_sample_parity/collect_vcs.py",
        "aon_timer_smoke_vseq.sv":"tools/stage10_sample_matrix/aon_timer_smoke_vseq.sv",
        "verify_source.py":"tools/stage10_sample_parity/verify_source.py",
        "event_wait_probe.sv":"tools/stage10_sample_fix/event_wait_probe.sv",
        "fork_cleanup_probe.sv":"tools/stage10_sample_fix/fork_cleanup_probe.sv",
        "sample-matrix.json":"configs/stage10-sample-matrix-v1.json",
        "collect_matrix.py":"tools/stage10_sample_matrix/collect_matrix.py",
        "vcs-python-requirements.txt":"tools/stage10_sample_matrix/vcs-python-requirements.txt",
        "legacy-eda-overlay-v1.tar.gz":"tools/stage10_sample_matrix/legacy-eda-overlay-v1.tar.gz",
        "vcs_p2019_compat.sh":"tools/stage10_sample_matrix/vcs_p2019_compat.sh",
        "git":"tools/stage10_sample_matrix/git_compat.sh",
        "stage10-paired-short-v1.json":"configs/stage10-paired-short-v1.json",
        "stage10-sample-fix-v1.json":"configs/stage10-sample-fix-v1.json"}
    for name,path in paths.items():require(sha(ROOT/path)==execution["inputs_sha256"][name],"VCS input changed: "+name)
    require(instrument["sample_fix_instrument_tool_sha256"]==execution["inputs_sha256"]["sample_fix_base.py"],"base fix instrument changed")
    require(instrument["matrix_instrument_tool_sha256"]==execution["inputs_sha256"]["instrument.py"],"matrix instrument changed")
    cases=[]; all_inputs={}
    for case in range(8):
        vcs=read(f"vcs-case-{case}.json"); folder=root/f"cocotb-case-{case}"
        replay=json.loads((folder/"replay.json").read_text()); trace=json.loads((folder/replay["raw_adapter_trace_filename"]).read_text())
        run=manifest["cases"][case]
        require(vcs["case"]==run["case"]==case and vcs["run_status"]==run["run_status"]=="PASS","case failed")
        require(vcs["process_exit_code"]==vcs["uvm_error_count"]==vcs["uvm_fatal_count"]==run["process_exit_code"]==0 and vcs["test_passed_checks"],"VCS error/fatal/exit")
        require(run["seed"]==vcs["seed"]==1 and trace["schema_id"]=="aon_timer_pinned_sampling_matrix_trace_v1" and trace["source_variant"]==VARIANT,"trace identity mismatch")
        require(trace["coverage_credit_granted"]==0 and trace["canonical_bin_vector"] is None,"coverage credit must stay zero")
        require(sha(folder/"replay.json")==run["files_sha256"]["replay.json"],"replay hash mismatch")
        trace_path=folder/replay["raw_adapter_trace_filename"]
        require(sha(trace_path)==run["files_sha256"]["traces/"+trace_path.name],"trace hash mismatch")
        require(export["cases"][case]["original_xml_sha256"]==run["files_sha256"]["results.xml"] and export["cases"][case]["public_xml_sha256"]==sha(folder/"results.xml"),"XML hashes mismatch")
        tests=ET.parse(folder/"results.xml").findall(".//testcase")
        require(len(tests)==1 and all(t.find("failure") is None and t.find("error") is None for t in tests),"Cocotb XML failed")
        result=compare_case(vcs,replay,trace)
        result.update({"cocotb_status":run["run_status"],"producer_events_are_unique":len(vcs["control_events"])==len(set(json.dumps(x,sort_keys=True) for x in vcs["control_events"])),"producer_events":vcs["control_events"]})
        required={"timer_cfg_cg","intr_cg"}
        if case != 3: required.add("intr_pins_cg")
        if case==0:required|={"wake_up_timer_thold_hit_cg"}
        if case in (1,2,7):required|={"watchdog_timer_bark_thold_hit_cg","watchdog_timer_bite_thold_hit_cg"}
        if case in (0,4,5,6):required|={"wake_up_timer_thold_hit_cg"}
        if case==3:required|={"intr_test_cg"}
        if case==7:
            require(any(r.get("kind")=="sleep" and r.get("value")==1 for r in vcs["records"]),"sleep assertion missing from VCS timeline")
            require(any(r.get("kind")=="sleep" and r.get("value")==0 for r in vcs["records"]),"sleep deassertion missing from VCS timeline")
        if case==6:
            require(any(r.get("kind")=="reset" and r.get("rst_aon_n")==0 for r in vcs["records"]),"mid-run AON reset missing from VCS timeline")
        result["required_groups"]=sorted(required)
        result["expected_matrix_case_passed"]=(
          set(result["samples"]["groups"])==required and result["producer_events_are_unique"]
          and result["accepted_tl_inputs_and_times_equal"] and result["tl_response_callbacks_and_read_values_equal"]
          and result["aon_edge_timestamps_equal"] and result["rtl_counters_and_output_pins_at_aon_edges_equal"]
          and all(g["ordered_tuples_and_times_equal"] for g in result["samples"]["groups"].values())
          and result["samples"]["same_time_multisets_equal"])
        for path in (root/f"vcs-case-{case}.json",folder/"replay.json",trace_path,folder/"results.xml"):
            all_inputs[path.relative_to(root).as_posix()]=sha(path)
        cases.append(result)
    return {"schema":"aon-timer-fixed-sample-matrix-audit-v1","source_revision":attest["revision"],
      "reference_variant":VARIANT,"reference_logic_fixes":FIXES,
      "audit_tool_sha256":sha(Path(__file__)),"source_export_verified":True,"post_build_source_verified":True,
      "status":"MATRIX_CASE_DIFFERENCES" if not all(c["expected_matrix_case_passed"] for c in cases) else "BOUNDED_SAMPLE_MATRIX_MATCH",
      "matrix_cases_passed":sum(c["expected_matrix_case_passed"] for c in cases),"matrix_cases_total":8,
      "complete_parity_verified":False,"original_reference_parity_verified":False,
      "full_simulation_started":False,"coverage_credit_granted":0,"full_coverage_rate":None,
      "scope":"Eight short repaired-reference cases only. Intr_test/update/restart/prescale/sleep/reset included; shared sample groups and exact legacy identity/vector matrix remain out of scope.",
      "global_same_time_cross_group_order_by_case":[c["samples"]["global_invocation_order_equal"] for c in cases],
      "inputs_sha256":all_inputs,"cases":cases}

def main()->None:
    p=argparse.ArgumentParser();p.add_argument("--evidence-dir",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    report=audit_evidence(a.evidence_dir);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+"\n");a.output.with_suffix(a.output.suffix+".sha256").write_text(sha(a.output)+"  "+a.output.name+"\n")
if __name__=="__main__":main()
