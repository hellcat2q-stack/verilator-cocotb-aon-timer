"""Run one isolated covergroup calibration in a fresh server directory.

Python 3.6 compatible.  This does not run OpenTitan RTL or a paper scheduler.
Logs and VDB stay on the server; only the compact observations are exportable.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_xml(path):
    raw = path.read_bytes()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    return ET.fromstring(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    if (work / 'compile.log').exists() or (work / 'probe.vdb').exists():
        parser.error('work directory already contains an attempt; use a fresh directory')
    plan_path = work / 'plan.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if sha256(work / 'probe.sv') != plan['probe_source_sha256']:
        parser.error('probe source SHA-256 mismatch')
    original = subprocess.check_output(
        ['git', 'show', plan['source_revision'] + ':hw/ip/aon_timer/dv/env/aon_timer_env_cov.sv'],
        cwd=str(args.source_root))
    if hashlib.sha256(original).hexdigest() != plan['source_file_sha256']:
        parser.error('server pinned source SHA-256 mismatch')
    compile_cmd = ['vcs', '-full64', '-sverilog', '-cm', 'line', '-cm_dir', 'probe.vdb',
                   '-o', 'simv', 'probe.sv']
    simulation_cmd = ['./simv', '-cm', 'line', '-cm_dir', 'probe.vdb', '-cm_name', 'array_boundary_probe']
    with (work / 'compile.log').open('w') as log:
        compile_result = subprocess.run(compile_cmd, cwd=str(work), stdout=log,
                                        stderr=subprocess.STDOUT, timeout=180)
    result = {'schema': 'aon-timer-vcs-array-boundary-observations-v1',
              'plan_sha256': sha256(plan_path), 'probe_source_sha256': sha256(work / 'probe.sv'),
              'server_pinned_source_sha256': hashlib.sha256(original).hexdigest(),
              'compile_command': compile_cmd, 'simulation_command': simulation_cmd,
              'compile_exit_code': compile_result.returncode, 'simulation_exit_code': None,
              'full_simulation_started': False, 'coverage_credit_granted': 0, 'cases': []}
    if compile_result.returncode == 0:
        with (work / 'simulation.log').open('w') as log:
            simulation = subprocess.run(simulation_cmd, cwd=str(work), stdout=log,
                                        stderr=subprocess.STDOUT, timeout=30)
        result['simulation_exit_code'] = simulation.returncode
        if simulation.returncode == 0:
            base = work / 'probe.vdb/snps/coverage/db/testdata'
            test_dirs = list(base.iterdir())
            if len(test_dirs) != 1:
                raise ValueError('expected exactly one calibration test in a fresh VDB')
            cumulative_path = test_dirs[0] / 'testbench.cumulative.xml'
            instance_path = test_dirs[0] / 'testbench.inst.xml'
            cumulative = read_xml(cumulative_path)
            instances = read_xml(instance_path)
            point_names = {}
            for program in cumulative.findall('program'):
                for cg in program.findall('cg_src'):
                    for cp in cg.findall('cp'):
                        point_names[(program.attrib['id'], cg.attrib['id'], cp.attrib['id'])] = cp.attrib['exprname']
            by_name = {row.attrib['name']: row for row in instances.findall('cg_inst')}
            result['native_xml_sha256'] = {'cumulative': sha256(cumulative_path), 'instances': sha256(instance_path)}
            for case in plan['cases']:
                matching = [inst for name, inst in by_name.items()
                            if name == case['case_id'] or name.endswith('.' + case['case_id'])]
                if len(matching) != 1:
                    raise ValueError('missing or ambiguous instance ' + case['case_id'])
                inst = matching[0]
                cps = [cp for cp in inst.findall('cp') if point_names.get(
                    (inst.attrib['prog'], inst.attrib['srcdef'], cp.attrib['id'])) == case['coverpoint']]
                if len(cps) != 1:
                    raise ValueError('missing or ambiguous coverpoint ' + case['case_id'])
                hit_names = [bn.attrib['name'] for bn in cps[0].findall('bn')
                             if int(bn.attrib['data']) > 0 and bn.attrib.get('excl', '0') == '0']
                result['cases'].append({'case_id': case['case_id'], 'hit_bin_names': sorted(hit_names)})
    output = work / 'observations.json'
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    output.with_suffix('.json.sha256').write_text(sha256(output) + '  observations.json\n', encoding='ascii')
    print(json.dumps({'compile_exit_code': result['compile_exit_code'],
                      'simulation_exit_code': result['simulation_exit_code'],
                      'observed_case_count': len(result['cases'])}))
    if result['compile_exit_code'] != 0 or result['simulation_exit_code'] != 0:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
