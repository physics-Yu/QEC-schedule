"""User-requested larger measurement region; explicit engineering assumption."""
from .initial import preinitialized_device
from .model import DeviceModelError
from .spec import validate_device
from math import isfinite, isclose


def rigid_readout_device(*, x_range_um=(-100., 200.), y_range_um=(1020., 1220.), readout_capacity=8):
    if readout_capacity is not None and (type(readout_capacity) is not int or readout_capacity <= 0):
        raise DeviceModelError([{'code':'INVALID_CAPACITY','path':'/readout_capacity','message':'Use a positive integer or None for explicitly unlimited parallel readout.'}])
    # Keep the historical eight-site auxiliary port separate from the enlarged
    # rigid MZ lattice, which has its own explicit concurrency contract.
    device = preinitialized_device(readout_capacity=min(8, readout_capacity) if readout_capacity is not None else 8)
    unbounded_x = tuple(x_range_um) == (None, None)
    device['artifact_id'] = ('device:rigid-measurement-v3:' if unbounded_x else 'device:rigid-measurement-v2:')+':'.join(str(x) for x in (*x_range_um, *y_range_um))+':readout-'+str(readout_capacity)
    device['zones']['measurement'].update(x_range_um=list(x_range_um), y_range_um=list(y_range_um))
    device['rigid_readout'] = {'schema_version':'rigid-readout-profile/0.3' if unbounded_x else 'rigid-readout-profile/0.2','bank_id':'rigid-mz',
                              'max_parallel_readouts':readout_capacity,
                              'site_pitch_um':device['geometry']['initial_spacing_um'],
                              'site_origin_um':[0. if unbounded_x else x_range_um[0],y_range_um[0]],
                              'site_policy':'static_lattice_with_shape_preserving_translation',
                              'provenance':{'kind':'project_assumption','calibrated':False,'source_refs':['ADR-0009@1.1.0']}}
    for section in ('/zones', '/slm'):
        record = device['parameter_provenance'][section]
        record['source_refs'] = [*record['source_refs'], 'ADR-0009@1.1.0']
        record['scope'] = ('User-requested rigid-array measurement region. Region dimensions and compile-time static SLM receiver patterns '
                           'are engineering assumptions, not hardware calibration. Concurrency is explicitly configured; None means no readout-channel cap. Timing and movement constraints remain unchanged.')
    errors = validate_device(device)
    if errors:
        raise DeviceModelError(errors)
    return device


def validate_rigid_readout_profile(device):
    p=device.get('rigid_readout');errors=[]
    def fail(message):errors.append({'code':'RIGID_READOUT_PROFILE','path':'/rigid_readout','message':message})
    if not isinstance(p,dict) or p.get('schema_version') not in {'rigid-readout-profile/0.1','rigid-readout-profile/0.2','rigid-readout-profile/0.3'}:
        fail('Explicit supported rigid-readout profile required');return errors
    if p.get('bank_id')!='rigid-mz' or p.get('site_policy')!='static_lattice_with_shape_preserving_translation':fail('Unsupported bank or site policy')
    if p.get('schema_version') in {'rigid-readout-profile/0.2','rigid-readout-profile/0.3'}:
        limit=p.get('max_parallel_readouts')
        if 'max_parallel_readouts' not in p or limit is not None and (type(limit) is not int or limit <= 0):
            fail('Explicit max_parallel_readouts must be a positive integer or null (unlimited).')
    pitch=p.get('site_pitch_um');origin=p.get('site_origin_um')
    if type(pitch) not in (int,float) or not isfinite(pitch) or pitch<=0:fail('Positive finite site pitch required')
    if not isinstance(origin,list) or len(origin)!=2 or any(type(v) not in (int,float) or not isfinite(v) for v in origin):fail('Finite two-coordinate origin required')
    zone=device['zones']['measurement']
    unbounded_x=p.get('schema_version')=='rigid-readout-profile/0.3' and zone['x_range_um']==[None,None]
    if not unbounded_x and any(v is None or not isfinite(v) for v in zone['x_range_um']):fail('Finite x bounds or explicit v3 unbounded x required')
    if any(v is None or not isfinite(v) for v in zone['y_range_um']):fail('Finite measurement y band required')
    expected=[0. if unbounded_x else zone['x_range_um'][0],zone['y_range_um'][0]]
    if not errors and origin!=expected:fail('Lattice origin must bind the declared finite edge or x=0 for unbounded strip')
    if not errors:
        axes=('y',) if unbounded_x else ('x','y')
        span=[zone[a+'_range_um'][1]-zone[a+'_range_um'][0] for a in axes]
        if any(not isclose(s/pitch,round(s/pitch),abs_tol=1e-8) for s in span):fail('Finite sides must span whole lattice intervals')
    return errors


def rigid_site_id(device, point):
    p=device.get('rigid_readout')
    if not p:raise ValueError('Rigid readout needs its declared receiver lattice')
    indices=[(point[k]-p['site_origin_um'][k])/p['site_pitch_um'] for k in (0,1)]
    if any(not isclose(i,round(i),abs_tol=1e-8) or (i<0 and not (k==0 and device['zones']['measurement']['x_range_um']==[None,None])) for k,i in enumerate(indices)):
        raise ValueError('Array does not fit the declared lattice by pure translation')
    for k,axis in enumerate(('x','y')):
        lo,hi=device['zones']['measurement'][axis+'_range_um']
        if lo is not None and point[k]<lo or hi is not None and point[k]>hi:raise ValueError('Rigid site is outside the declared measurement rectangle')
    return 'grid:'+':'.join(str(round(i)) for i in indices)


def rigid_readout_capacity(device):
    """None is explicit unbounded readout concurrency; absent v1 retains its limit."""
    profile=device['rigid_readout']
    if profile['schema_version'] in {'rigid-readout-profile/0.2','rigid-readout-profile/0.3'}:
        return profile['max_parallel_readouts']
    return device['grouped_profile']['readout']['bank_capacity']
