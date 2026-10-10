"""Project committed frame sessions into the existing light canvas viewer."""
from pathlib import Path
import argparse, base64, gzip, hashlib, json, re, shutil
from build_component_gallery import project, read, write, ROOT
from export_viewer_schedules import lanes, carrier_occupancy


def packed(value):
    return base64.b64encode(gzip.compress(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode(),mtime=0)).decode()


def script_value(path):
    return json.loads(path.read_text(encoding='utf-8').split('=',1)[1].strip().removesuffix(';'))


def frame_data(key,raw):
    events=raw['frame_context']['events'];entries=[(e['atom_program'],e['trace']) for e in raw['entries']]
    phases=raw['phases'] or [{'id':str(i),'label':e['requested_gate'],'start_us':e['time_us'],
        'end_us':e['end_us'],'note':'软件帧，无硬件动作' if e['software_only'] else '同一事件会话'} for i,e in enumerate(events)]
    if raw['phases']:
        phases=[{'id':'materialize-'+str(i),'label':e['component_id']+' · 显式物理兑现',
                 'start_us':e['atom_program']['stats']['t_start_us'],'end_us':e['atom_program']['stats']['t_end_us'],
                 'note':'同一数据载体；兑现动作和费用已计入'}
                for i,e in enumerate(raw['entries']) if not e['component_id'].startswith('T:')]+phases
    if entries:
        data=project(key,entries,raw['device'],phases,source_plans=[e['physical_plan'] for e in raw['entries']])
    else:
        atoms=raw['initial_state']['atoms'];xy=[a['position_um'] for a in atoms]
        data={'id':key,'atoms':[[a['atom_id'],a['qubit_id'],*a['position_um'],a['carrier'],a['aod_group'],a.get('site_id',a['qubit_id'])] for a in atoms],
              'actions':[],'sources':[],'results':[],'end':0.,'phases':phases,'patches':[],
              'bounds':[min(x[0] for x in xy)-20,max(x[0] for x in xy)+20,min(x[1] for x in xy)-25,max(x[1] for x in xy)+25],
              'measurement':[None,None,1020,1220],'readout_capacity':None,'raw_action_count':0,'fake_scenario':True}
    data['frame_events']=events
    data['modules']=[{**m,'start_us':m['start_us']+e['atom_program']['stats']['t_start_us'],
                     'end_us':m['end_us']+e['atom_program']['stats']['t_start_us']}
                    for e in raw['entries'] for m in e['physical_plan'].get('module_composition',{}).get('instances',[])]
    records=[]
    for atom,trace in entries:
        statuses={e['action_id']:e['status'] for e in trace['events']}
        records.extend((a['t_start_us'],a['t_end_us'],a,statuses[a['id']]) for a in atom['actions'])
    records.sort(key=lambda x:(x[0],x[1]));tracks={};resource_names=[];rindex={}
    for i,(start,end,a,status) in enumerate(records):
        assert data['actions'][i][:3]==[start,end,a['kind']]
        if status!='completed':continue
        for lane,resources in lanes(a).items():
            ids=[]
            for r in resources:
                if r not in rindex:rindex[r]=len(resource_names);resource_names.append(r)
                ids.append(rindex[r])
            tracks.setdefault(lane,[]).append([start,end,i,ids])
    schedule={'schema_version':'ViewerResources/0.1','id':key,'end':data['end'],'resource_names':resource_names,
              'lanes':[{'id':k,'kind':'activity' if k.startswith('activity:') else 'declared_resources','intervals':v} for k,v in tracks.items()],
              'scope':'actual committed atom actions; software frames occupy no device resource'}
    schedule['lanes']+=carrier_occupancy(records,{a[0]:a[5] for a in data['atoms']},data['end'])
    return data,schedule


def build(out,frames):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if (out/'manifest.js').is_file():
        manifest=script_value(out/'manifest.js');schedules=script_value(out/'schedules.js');zones=script_value(out/'regions.js')
        payloads=dict(re.findall(r'id="packed-([^"]+)">([^<]+)</script>',(out/'full-viewer.html').read_text(encoding='utf-8')))
        if any(r['id']=='H_PHYSICAL' for r in manifest['components']):raise ValueError('FRAME_EXTENSION_ALREADY_APPLIED')
        h=next(r for r in manifest['components'] if r['id']=='H');h.update(id='H_PHYSICAL',data_id='H_PHYSICAL',label='H · 显式物理兑现',description='仅在需要把帧兑现为真实逻辑操作时使用；九个物理 H 与已验证原子位置置换，费用完整计入。')
        old=json.loads(gzip.decompress(base64.b64decode(payloads.pop('H'))));old['id']='H_PHYSICAL';payloads['H_PHYSICAL']=packed(old)
        physical_folder=out/'H_PHYSICAL';physical_folder.mkdir(exist_ok=True)
        (physical_folder/'motion-data.js').write_text('window.COMPONENT_DATA=window.COMPONENT_DATA||{};window.COMPONENT_DATA.H_PHYSICAL='+json.dumps(old,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
        h.update(data_path='H_PHYSICAL/motion-data.js',source_directory='H')
        sched=json.loads(gzip.decompress(base64.b64decode(schedules.pop('H'))));sched['id']='H_PHYSICAL';schedules['H_PHYSICAL']=packed(sched)
        zones['H_PHYSICAL']=zones.pop('H')
    else:
        manifest={'schema_version':'component-gallery/0.1','components':[],'coverage':{},'user_visual_acceptance':'pending','browser_verified':False};payloads={};schedules={};zones={}
    descriptions={
        'H_VIRTUAL':('H','H · 软件 Clifford 帧','逻辑 H 只更新带符号的观测量映射；原子保持原位，硬件耗时为 0。'),
        'H_THEN_H':('H_THEN_H','H → H · 帧抵消','两次软件 H 抵消，不产生原子动作。'),
        'H_THEN_Z':('H_THEN_Z','H → Z 读出','保留实际码，算法 Z 改为测量物理逻辑 X。'),
        'H_THEN_SE':('H_THEN_SE','H → SE','软件 H 后维护实际码的原稳定子，保留 H 帧。'),
        'H_THEN_CZ':('H_THEN_CZ','H → CZ','一侧 H 帧将请求的 CZ 改写为反向逻辑 CNOT；物理 H–CZ–H 层保留。'),
        'H_THEN_T':('H_THEN_T','H → 完整 T 协议','当前实现先显式物理兑现 H 帧，再在同一载体和会话完成 CNOT 注入蒸馏与 T 消费。兑现动作和费用全部显示。'),
        'CZ_THEN_CX_SE':('CZ_THEN_CX_SE','CZ → CX → SE → Z 读出','B 码块只在 t=0 采用旋转初始布局；后续 CX、SE 和读出沿同一世界继续，不重置布局。')}
    receipts=[]
    for folder in sorted(Path(frames).iterdir()):
        if folder.name not in descriptions or not (folder/'frame-session.json.gz').is_file():continue
        key,label,description=descriptions[folder.name];raw=read(folder/'frame-session.json.gz');summary=read(folder/'summary.json')
        assert summary['status']=='passed'
        data,schedule=frame_data(key,raw)
        target=out/'frame-examples'/folder.name;target.mkdir(parents=True,exist_ok=True)
        for name in ('frame-session.json.gz','summary.json'):shutil.copyfile(folder/name,target/name)
        write(target/'frame-events.json',raw['frame_context'])
        (target/'motion-data.js').write_text('window.COMPONENT_DATA=window.COMPONENT_DATA||{};window.COMPONENT_DATA['+json.dumps(key)+']='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
        payloads[key]=packed(data);schedules[key]=packed(schedule)
        device=raw['device'];cz=device['zones']['storage_entanglement'];mz=device['zones']['measurement']
        zones[key]={'compute':[*cz['x_range_um'],*cz['y_range_um']],'measurement':[*mz['x_range_um'],*mz['y_range_um']]}
        manifest['components'].append({'id':key,'data_id':key,'label':label,'category':'逻辑帧与持续接续','kind':'frame_session',
            'description':description,'scope':'软件帧与实际码/载体分别记录；物理步骤经过源、几何与事件检查。无量子态或噪声仿真。',
            'data_path':(target/'motion-data.js').relative_to(out).as_posix(),'physical_operations':sum(len(d['nodes']) for e in raw['entries'] for d in e['physical_plan']['physical_dags']),
            'duration_us':summary['duration_us'],'action_count':summary['action_count'],'executed_action_count':sum(a[7]=='completed' for a in data['actions']),
            'atom_count':summary['atom_count'],'implementation_version':'frame-cnot/1','version_status':'当前帧与接续实现','module_stats':summary['module_stats'],
            'links':[{'label':'实时帧与控制事件','href':(target/'frame-events.json').relative_to(out).as_posix()},{'label':'实际执行摘要','href':(target/'summary.json').relative_to(out).as_posix()}]})
        receipts.append({'id':key,'events':len(data['frame_events']),'actions':len(data['actions']),
                         'source_sha256':hashlib.sha256((folder/'frame-session.json.gz').read_bytes()).hexdigest()})
    for r in manifest['components']:
        if r['id']=='CZ':r['description']='正确 90°数据配对的九对原生 CZ。此单脉冲示例在 t=0 旋转目标块几何；持续布局的代价另见 CZ→CX→SE。'
        if r['id'] in ('T','TDG'):r['description']='完整 15→1 连续协议：编码 CNOT → 魔态逻辑 Z 读出 → 条件 S/S†；保留接受、同载体转换与消费清理。'
        if r['id']=='JOINT_ZZ':r['description']='独立联合 ZZ 的逐检查参考配方，仍存在串行开销。本次 CNOT 注入蒸馏不调用它；不作为并行优化完成证据。'
    manifest['component_count']=len(manifest['components'])-sum(r['id']=='SE_PAIR' for r in manifest['components'])
    if any(r['id']=='H_PHYSICAL' for r in manifest['components']):
        physical=next(r for r in manifest['components'] if r['id']=='H_PHYSICAL')
        virtual=next(r for r in manifest['components'] if r['id']=='H')
        index=manifest['components'].index(physical)
        manifest['components'].remove(physical);manifest['components'].remove(virtual)
        virtual['category']='逻辑原语';manifest['components'].insert(index,virtual)
        physical['category']='逻辑帧与持续接续';manifest['components'].append(physical)
    manifest['demonstration_count']=sum(r['id']=='SE_PAIR' for r in manifest['components'])
    for name,var,value in [('manifest.js','COMPONENT_MANIFEST',manifest),('schedules.js','COMPONENT_SCHEDULE_PACKED',schedules),('regions.js','COMPONENT_ZONES',zones)]:
        (out/name).write_text('window.'+var+'='+json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')+';\n',encoding='utf-8')
    shell=(ROOT/'viewer/components.html').read_text(encoding='utf-8').replace('70 组件<br>＋ 1 并行示例',str(len(manifest['components']))+' 动画<br>组件 / 帧 / 连续协议')
    (out/'index.html').write_text(shell,encoding='utf-8')
    for name in ('components.css','components.js','lab-renderer.js','motion-preview.js','resource-schedule.js'):shutil.copyfile(ROOT/'viewer'/name,out/name)
    shell=shell.replace('<link rel="stylesheet" href="components.css">','<style>'+(out/'components.css').read_text(encoding='utf-8')+'</style>')
    tags=''.join('<script type="application/octet-stream" id="packed-'+k+'">'+v+'</script>' for k,v in payloads.items())
    shell=shell.replace('<script src="manifest.js"></script>',tags+'<script>'+(out/'manifest.js').read_text(encoding='utf-8')+'</script>')
    for name in ('schedules.js','regions.js','motion-preview.js','resource-schedule.js','lab-renderer.js','components.js'):
        shell=shell.replace(f'<script src="{name}"></script>','<script>'+(out/name).read_text(encoding='utf-8')+'</script>')
    for name in ('full-viewer.html','animation-library.html'):(out/name).write_text(shell,encoding='utf-8')
    write(out/'frame-viewer-receipt.json',{'components':len(manifest['components']),'frame_sessions':receipts,'source_actions_modified':False,'user_visual_acceptance':'pending','browser_verified':False})
    print(json.dumps({'components':len(manifest['components']),'path':str(out/'animation-library.html')}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--frames',required=True);a=p.parse_args();build(ROOT/a.out,ROOT/a.frames)
