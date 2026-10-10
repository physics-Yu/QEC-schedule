"""Read-only projection of existing device resource intervals for the viewer."""
from pathlib import Path
import argparse, base64, gzip, hashlib, json, re


def read(path):
    raw = Path(path).read_bytes()
    return json.loads(gzip.decompress(raw) if str(path).endswith('.gz') else raw)


def lanes(action):
    result = {}
    for resource in action['resources']:
        if resource.startswith('aod:'):
            key = ':'.join(resource.split(':')[:2])
        elif resource.startswith('trap:aod:'):
            key = ':'.join(resource.split(':')[1:3])
        elif resource.startswith('trap:slm:'):
            key = 'slm:ports'
        elif resource.startswith('readout'):
            key = 'readout:array'
        elif resource.startswith('rydberg:'):
            key = resource
        elif resource.startswith('atom:'):
            continue
        else:
            key = resource
        result.setdefault(key, []).append(resource)
    kind = action['kind']
    if kind == 'gate' and action['payload'].get('name') != 'CZ':
        result['activity:1q'] = []
    elif kind in ('reset', 'classical'):
        result['activity:' + kind] = []
    return result


def carrier_occupancy(records, groups, end_us):
    """Occupancy from committed carrier transitions, including idle AOD holds."""
    loaded={};spans={}
    for i,(start,end,action,status) in enumerate(records):
        if status!='completed':continue
        if action['kind']=='pickup':
            for atom in action['atoms']:loaded[atom]=(end,i)
        elif action['kind']=='drop':
            for atom in action['atoms']:
                begin,index=loaded.pop(atom)
                spans.setdefault('occupancy:aod:'+groups[atom],set()).add((begin,end,index))
    for atom,(begin,index) in loaded.items():spans.setdefault('occupancy:aod:'+groups[atom],set()).add((begin,end_us,index))
    return [{'id':key,'kind':'carrier_occupancy','intervals':[[start,end,index,[]] for start,end,index in sorted(items)]} for key,items in spans.items()]


def export(out):
    out = Path(out)
    html = (out / 'full-viewer.html').read_text(encoding='utf-8')
    packed = dict(re.findall(r'id="packed-([^"]+)">([^<]+)</script>', html))
    packed = {k:v for k,v in packed.items() if not k.startswith('schedule-')}
    manifest = json.loads((out / 'manifest.js').read_text(encoding='utf-8').split('=', 1)[1].strip().removesuffix(';'))
    outputs, receipts = {}, []
    for row in manifest['components']:
        key = row['id']; data = json.loads(gzip.decompress(base64.b64decode(packed[key])))
        sources = []; records = []
        if row['kind'] == 'physical':
            directory=row.get('source_directory',key)
            entries = [(out/directory/'atom-program.json', out/directory/'event-trace.json', 0)]
        else:
            target = 'T' if key in ('FACTORY_READY', 'RESERVE_DELIVERY') else key
            folder = out/'protocols'/target
            original = {p['id']: p for p in read(folder/'summary.json')['phases']}
            entries = [(folder/p['artifact'], None, original[p['id']]['start_us']-p['start_us']) for p in data['phases']]
        for source, trace_path, origin in entries:
            raw = read(source)
            program = raw if trace_path else raw['atom_program']
            trace = read(trace_path) if trace_path else raw['trace']
            events = {e['action_id']:e for e in trace['events']}
            sources.append({'path':source.relative_to(out).as_posix(),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
            for a in program['actions']:
                e = events[a['id']]
                assert (a['t_start_us'],a['t_end_us']) == (e['t_start_us'],e['t_end_us'])
                records.append((a['t_start_us']-origin, a['t_end_us']-origin, a, e['status']))
        records.sort(key=lambda r:(r[0],r[1]))
        assert len(records) == len(data['actions']),key
        atom_ids = {a[0]:i for i,a in enumerate(data['atoms'])}
        resource_names = []; resource_index = {}; tracks = {}
        for i, (start,end,a,status) in enumerate(records):
            shown = data['actions'][i]
            assert [start,end,a['kind'],[atom_ids[x] for x in a['atoms']]] == shown[:4],(key,i)
            assert status == shown[7]
            if status != 'completed':
                continue
            for lane, resources in lanes(a).items():
                ids = []
                for r in resources:
                    if r not in resource_index:
                        resource_index[r] = len(resource_names); resource_names.append(r)
                    ids.append(resource_index[r])
                tracks.setdefault(lane,[]).append([start,end,i,ids])
        value = {'schema_version':'ViewerResources/0.1','id':key,'end':data['end'],'resource_names':resource_names,
                 'lanes':[{'id':k,'kind':'activity' if k.startswith('activity:') else 'declared_resources','intervals':v} for k,v in tracks.items()],
                 'sources':sources,'scope':'completed action resource use; activity lanes do not imply an exclusive device lock'}
        value['lanes']+=carrier_occupancy(records,{a[0]:a[5] for a in data['atoms']},data['end'])
        raw = json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
        outputs[key] = base64.b64encode(gzip.compress(raw,mtime=0)).decode()
        receipts.append({'id':key,'actions_matched':len(records),'lanes':len(tracks),'intervals':sum(len(v) for v in tracks.values()),'sha256':hashlib.sha256(raw).hexdigest()})
    (out/'schedules.js').write_text('window.COMPONENT_SCHEDULE_PACKED='+json.dumps(outputs,separators=(',',':'))+';\n',encoding='utf-8')
    receipt = {'schema_version':'ViewerResourceExport/0.1','components':receipts,'compiler_invoked':False,'source_artifacts_modified':False}
    (out/'viewer-resource-export.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'components':len(receipts),'intervals':sum(r['intervals'] for r in receipts),'compiler_invoked':False}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True)
    export(parser.parse_args().out)
