"""Project named regions from each frozen device file, without compilation."""
from pathlib import Path
import json
import hashlib


def export(out):
    out=Path(out)
    manifest=json.loads((out/'manifest.js').read_text(encoding='utf-8').split('=',1)[1].strip().removesuffix(';'))
    regions={}
    for row in manifest['components']:
        key=row['id']
        folder=out/row.get('source_directory',key) if row['kind']=='physical' else out/'protocols'/('T' if key in ('FACTORY_READY','RESERVE_DELIVERY') else key)
        source=folder/'device.json';device=json.loads(source.read_bytes())
        compute=device['zones']['storage_entanglement'];measurement=device['zones']['measurement']
        regions[key]={'compute':[*compute['x_range_um'],*compute['y_range_um']],
                      'measurement':[*measurement['x_range_um'],*measurement['y_range_um']],
                      'source':source.relative_to(out).as_posix(),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                      'compute_source_zone':'storage_entanglement'}
    (out/'regions.js').write_text('window.COMPONENT_ZONES='+json.dumps(regions,separators=(',',':'))+';\n',encoding='utf-8')
    (out/'viewer-regions.json').write_text(json.dumps({'schema_version':'ViewerRegions/0.1','compiler_invoked':False,'regions':regions},indent=2),encoding='utf-8')
    return regions
