"""Static layout only: reuse the saved 17-wire placement, no circuit execution."""
from pathlib import Path
from collections import Counter
from itertools import combinations
import hashlib, json, math, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from na_pipeline.device import canonical_surface17_device

SOURCE = Path('C:/Users/yuyqp/Documents/ChatGPT/Atom compiler/output/shor15_hrs_enola')
OUT = ROOT/'artifacts/demos/shor17-four-factory-layout-20261009'


def write(name, value):
    (OUT/name).write_bytes((json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    settings = json.loads((SOURCE/'enola_settings.json').read_bytes())
    circuit = json.loads((SOURCE/'circuit.json').read_bytes())
    mapping, labels = settings['initial_mapping'], circuit['labels']
    assert circuit['metrics']['num_qubits'] == len(mapping) == len(labels) == 17
    device = canonical_surface17_device()
    slots = device['grouped_profile']['layouts']['patch_home']['slots']
    patches, atoms, factories = [], [], []

    def patch(pid, label, anchor, region, group, **extra):
        patches.append(dict(id=pid, label=label, anchor_um=anchor, region=region,
                            aod_group=group, atom_count=17, **extra))
        for slot, detail in slots.items():
            atoms.append(dict(id=pid+'/'+slot, patch=pid, local_id=slot,
                              role='data' if slot.startswith('d') else slot[0].upper(),
                              aod_group=group, region=region, carrier='SLM',
                              xy_um=[anchor[i]+detail['position_um'][i] for i in (0,1)]))

    for q, (xy, label) in enumerate(zip(mapping, labels, strict=True)):
        patch('q'+str(q), label.split(':')[-1], [100.*xy[0], 450.+100.*xy[1]],
              'compute', 'data', source_qubit=q, source_label=label, source_grid=xy)
    for i in range(4):
        fid = 'F'+str(i)
        origin = [620., 450.+130.*i]
        for j, slot in enumerate(('W0','W1','W2','W3','W4','M','Y')):
            patch(fid+':'+slot, slot, [origin[0]+100.*j, origin[1]], fid, 'magic',
                  factory_id=fid, factory_slot=slot, output_carrier=slot=='W4')
        probe = [origin[0]+700., origin[1]+80.]
        atoms.append(dict(id=fid+':join_probe', patch=None, local_id='probe', role='probe',
                          aod_group='magic', region=fid, carrier='SLM', xy_um=probe))
        factories.append(dict(id=fid, side='right', origin_um=origin, atom_count=120,
                              bounds_um=[600., origin[1]-12., 1360., origin[1]+102.],
                              output_patch=fid+':W4', probe_um=probe,
                              nominal_period_ms=200, rate_source='user_instruction',
                              initial_ready_magic_states=0))
    layout = dict(schema_version='StaticShorFactoryLayout/0.1',
                  title='Shor-17 · 四工厂单侧布局', scope='static_layout_preview_only',
                  source_thread_id='01a0e68e-ada5-7f43-8227-8c99bf052bbd',
                  source_thread_title='用 Enola 编译 15 的分解电路',
                  source_files={name:dict(path=str(SOURCE/name), sha256=hashlib.sha256((SOURCE/name).read_bytes()).hexdigest())
                                for name in ('enola_settings.json','circuit.json')},
                  layout_rule=dict(source_mapping=mapping, source_labels=labels,
                                   source_placement=settings['placement'],
                                   data_anchor_pitch_um=100, data_origin_um=[0,450],
                                   mapping_reoptimized=False, mapping_rotated_or_mirrored=False,
                                   factory_macro_layout='existing seven-patch row plus probe, translation only'),
                  regions=dict(compute=[-20.,430.,500.,950.], magic=[580.,430.,1380.,950.],
                               transfer_corridor=[500.,430.,580.,1000.],
                               measurement=dict(x_range_um=[None,None], y_range_um=[1020.,1220.],
                                                preview_bounds_um=[-40.,1020.,1400.,1220.])),
                  aod_groups=dict(data=dict(resource='aod:data', atom_count=289, region='compute'),
                                  magic=dict(resource='aod:magic', atom_count=480, region='right_magic_all_four_factories')),
                  counts=dict(algorithm_qubits=17, data_patches=17, data_atoms=289,
                              factory_count=4, factory_patches=28, factory_probes=4,
                              magic_atoms=480, all_atoms=769, aod_systems=2),
                  rate_assumption=dict(per_factory_period_ms=200, factories=4,
                                       nominal_states_per_second=20, nominal_mean_spacing_ms=50,
                                       actual_schedule_verified=False, reason='user_requested_layout_sizing'),
                  patches=patches, atoms=atoms, factories=factories,
                  initial_carrier='SLM', aod_active_atoms_at_preview=0,
                  actions=[], circuit_compiled=False, circuit_executed=False,
                  factory_production_executed=False, movement_routed=False,
                  quantum_state_assigned=False, user_layout_acceptance='pending')
    checks = {}
    checks['17_original_qubit_ids_and_labels'] = [p['source_label'] for p in patches[:17]] == labels
    checks['original_placement_mapping_preserved'] = all(p['anchor_um']==[100.*xy[0],450.+100.*xy[1]] for p,xy in zip(patches,mapping))
    checks['four_factories_all_on_right'] = len(factories)==4 and all(f['bounds_um'][0]>layout['regions']['compute'][2] for f in factories)
    checks['two_AOD_groups_only'] = set(a['aod_group'] for a in atoms)=={'data','magic'}
    checks['inventory_289_plus_480_equals_769'] = len(atoms)==769 and Counter(a['aod_group'] for a in atoms)=={'data':289,'magic':480}
    checks['unique_atom_and_site_positions'] = len({a['id'] for a in atoms})==len(atoms)==len({tuple(a['xy_um']) for a in atoms})
    checks['45_nonoverlapping_canonical_patch_cells'] = all(
        not (max(a['anchor_um'][0],b['anchor_um'][0]) < min(a['anchor_um'][0]+80,b['anchor_um'][0]+80) and
             max(a['anchor_um'][1],b['anchor_um'][1]) < min(a['anchor_um'][1]+80,b['anchor_um'][1]+80))
        for a,b in combinations(patches,2))
    checks['canonical_9_data_4_X_4_Z_per_patch'] = all(Counter(a['role'] for a in atoms if a['patch']==p['id'])=={'data':9,'X':4,'Z':4} for p in patches)
    checks['no_initial_atom_in_measurement_or_corridor'] = all(a['xy_um'][1]<1020 and not 500<a['xy_um'][0]<580 for a in atoms)
    checks['region_containment'] = all(
        (lambda b: b[0]<=a['xy_um'][0]<=b[2] and b[1]<=a['xy_um'][1]<=b[3])(
            layout['regions']['compute'] if a['aod_group']=='data' else next(f['bounds_um'] for f in factories if f['id']==a['region']))
        for a in atoms)
    checks['no_motion_compile_or_execution'] = not layout['actions'] and not layout['circuit_executed'] and not layout['circuit_compiled']
    assert all(checks.values()), checks
    write('layout.json', layout)
    write('layout-checks.json', dict(passed=True, scope='static_inventory_mapping_and_geometry_only', checks=checks,
          minimum_initial_atom_distance_um=min(math.dist(a['xy_um'],b['xy_um']) for a,b in combinations(atoms,2)),
          full_pipeline_passed=False, async_schedule_verified=False, user_layout_acceptance='pending'))
    template=(ROOT/'viewer/shor17-layout.html').read_text(encoding='utf-8')
    (OUT/'index.html').write_bytes(template.replace('__LAYOUT_JSON__',json.dumps(layout,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')).encode('utf-8'))
    write('reference-layout.json',dict(source=layout['source_files'],initial_mapping=mapping,labels=labels,
                                     original_placement=settings['placement'],transform=layout['layout_rule']))
    print(json.dumps({'atoms':len(atoms),'patches':len(patches),'static_checks_passed':len(checks),'out':str(OUT)},ensure_ascii=False))


if __name__=='__main__': build()
