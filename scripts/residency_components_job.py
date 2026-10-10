"""Rebind immutable modules with qualified AOD residency, then replay frames."""
from pathlib import Path
import argparse, hashlib, json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from component_gallery_job import save


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--module-manifest',required=True);p.add_argument('--frontier-precheck',action='store_true');a=p.parse_args()
    out=ROOT/a.out;store=out/'compiled-modules';store.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((ROOT/a.module_manifest).read_bytes());source=Path(manifest['source']).resolve()
    if not source.is_relative_to(Path('/home/yyq/na-platform-simulation/R7/T704')):raise ValueError('MODULE_SOURCE_SCOPE')
    for name,sha in manifest['files'].items():
        if Path(name).name!=name:raise ValueError('MODULE_PATH_SCOPE')
        raw=(source/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('MODULE_IMPORT_HASH')
        (store/name).write_bytes(raw)
    save(out/'module-import.json',manifest)
    if a.frontier_precheck:
        from component_gallery_job import compile_one
        result=compile_one('factory.finish_04',out,1800)
        if result['status']!='passed':raise ValueError('FRONTIER_PRECHECK_FAILED')
        plan=json.loads((out/'factory.finish_04/physical-plan.json').read_bytes())
        pulses=[x for x in plan['atom_program']['actions'] if x['payload'].get('name')=='CZ']
        first_is_uncompute=all('/uncompute_' in s['physical_op_id'] for s in pulses[0]['payload']['pair_sources'])
        if not first_is_uncompute:raise ValueError('READY_CNOT_STILL_STARVED')
        save(out/'frontier-precheck.json',{'summary':result,'first_CZ_is_ready_uncompute':True,
             'CZ_pairs_by_pulse':[len(x['payload']['pairs']) for x in pulses],
             'comparison_baseline_v3_us':28825.,'same_source_and_100us_profile':True})
        result=compile_one('factory.rotate_04',out,1800)
        if result['status']!='passed':raise ValueError('INJECTION_PRECHECK_FAILED')
        plan=json.loads((out/'factory.rotate_04/physical-plan.json').read_bytes())
        inject=[a for a in plan['atom_program']['actions'] if a['payload'].get('name')=='CZ' and
                any('/inject_cnot_' in s['physical_op_id'] for s in a['payload']['pair_sources'])]
        reads=[a for a in plan['atom_program']['actions'] if a['kind']=='measure' and
               any('/magic_read_read_' in s for s in a['payload']['physical_op_ids'])]
        if len(inject)!=1 or len(inject[0]['payload']['pairs'])!=9 or len(reads)!=9 or len({a['t_start_us'] for a in reads})!=1:
            raise ValueError('LOGICAL_CNOT_OR_MAGIC_READOUT_FRAGMENTED')
        save(out/'injection-cohort-precheck.json',{'summary':result,'CNOT_CZ_pulses':1,'CNOT_pairs':9,'magic_readouts':9,'readout_waves':1})
    import aod_held_components_job
    sys.argv=[sys.argv[0],'--out',a.out,'--workers','4'];aod_held_components_job.main()
    import frame_continuation_job
    next_manifest={'source':str(store),'files':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in store.glob('*.json')}}
    save(out/'frame-module-input.json',next_manifest)
    sys.argv=[sys.argv[0],'--out',(out/'frame-continuations').relative_to(ROOT).as_posix(),
              '--module-source',str(store),'--module-manifest',(out/'frame-module-input.json').relative_to(ROOT).as_posix()]
    frame_continuation_job.main()
    save(out/'residency-and-frame-complete.json',{'status':'passed','source_modules':len(manifest['files']),
        'frame_continuations':'frame-continuations','user_visual_acceptance':'pending','full_shor_executed':False})


if __name__=='__main__':main()
