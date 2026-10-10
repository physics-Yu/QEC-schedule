"""Three source-labelled, actually executed parallel examples in the gallery."""
from pathlib import Path
import argparse,json,re,shutil
from build_component_gallery import project,read,write,ROOT
from extend_frame_gallery import packed,script_value
from export_viewer_schedules import lanes,carrier_occupancy


def build(out,allow_partial=False):
    manifest=script_value(out/'manifest.js');schedules=script_value(out/'schedules.js');zones=script_value(out/'regions.js')
    payloads=dict(re.findall(r'id="packed-([^"]+)">([^<]+)</script>',(out/'animation-library.html').read_text(encoding='utf-8')))
    labels={'RAW_A_SINGLE':('原始 A · 单块编码','9 个 CX 的完整相干编码；此片段不包含后续 SE，任意种子带符号映射已检查。'),
            'RAW_A_FOUR':('原始 A · 四块共同编码','四块同时做块内编码，比较每批各块的实际配对和 AOD 抓放。'),
            'RAW_A_WITH_SE':('四块编码 ＋ 另一块 SE','不同逻辑阶段共同选批：四块编码和 W4 一轮 SE；同一全局世界，不分段重置。'),
            'SE_DUAL_SIX':('六块 SE · 两组 AOD','W0–W4 与 D 的两组独立 AOD 同时运输、共同 CZ；48 辅助同波读出，保留全程扫掠证明。')}
    for key,(label,description) in labels.items():
        if allow_partial and not (out/'parallel-examples'/key/'summary.json').exists():continue
        if any(r['id']==key for r in manifest['components']):raise ValueError('PARALLEL_EXTENSION_ALREADY_APPLIED')
        folder=out/'parallel-examples'/key;summary=read(folder/'summary.json');assert summary['status']=='passed'
        atom,trace,device,plan=(read(folder/n) for n in ('atom-program.json','event-trace.json','device.json','physical-plan.json'))
        data=project(key,[(atom,trace)],device,[{'id':key,'label':label,'start_us':0.,'end_us':summary['duration_us'],'note':'同一完整世界中的实际源与事件'}],source_plans=[plan])
        data['modules']=plan['module_composition']['instances']
        events={e['action_id']:e['status'] for e in trace['events']};records=sorted([(a['t_start_us'],a['t_end_us'],a,events[a['id']]) for a in atom['actions']],key=lambda v:(v[0],v[1]))
        tracks={};resources=[];index={}
        for i,(s,e,a,status) in enumerate(records):
            assert data['actions'][i][:3]==[s,e,a['kind']]
            if status!='completed':continue
            for lane,rs in lanes(a).items():
                for r in rs:
                    if r not in index:index[r]=len(resources);resources.append(r)
                tracks.setdefault(lane,[]).append([s,e,i,[index[r] for r in rs]])
        schedule={'schema_version':'ViewerResources/0.1','id':key,'end':data['end'],'resource_names':resources,
            'lanes':[{'id':k,'kind':'activity' if k.startswith('activity:') else 'declared_resources','intervals':v} for k,v in tracks.items()],
            'scope':'actual executed plan'}
        schedule['lanes']+=carrier_occupancy(records,{a[0]:a[5] for a in data['atoms']},data['end'])
        payloads[key]=packed(data);schedules[key]=packed(schedule);cz=device['zones']['storage_entanglement'];mz=device['zones']['measurement']
        zones[key]={'compute':[*cz['x_range_um'],*cz['y_range_um']],'measurement':[*mz['x_range_um'],*mz['y_range_um']]}
        path=(folder/'motion-data.js').relative_to(out).as_posix();(folder/'motion-data.js').write_text('window.COMPONENT_DATA=window.COMPONENT_DATA||{};window.COMPONENT_DATA['+json.dumps(key)+']='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
        manifest['components'].append({'id':key,'data_id':key,'label':label,'description':description,'kind':'parallel_example','category':'块内与块间并行验收',
            'scope':'100 μs 抓放；源依赖深度与实际 CZ 层数分别记录。无量子态/噪声仿真，不宣称全局最优。','data_path':path,
            **{k:summary[k] for k in ('physical_operations','atom_count','action_count','duration_us')},
            'implementation_version':'joint-frontier/1','version_status':'共同前沿重构','module_stats':{},
            'links':[{'label':'每块与每批成本','href':(folder/'summary.json').relative_to(out).as_posix()},
                     {'label':'源物理 DAG','href':(folder/'physical-dag.json').relative_to(out).as_posix()}]})
    for r in manifest['components']:
        if r['id']=='SE_PAIR':r['description']='两块完整 SE 共同编译；五次共同 CZ 广播，16 辅助原子共同运输和读出。'
        if r['id'].startswith('factory.finish_') and r['id']!='factory.finish_14':r['description']+=' 同时制备下一颗原始魔态；消费必须等待真实提交回执。'
        r['version_status']=('当前模块配方 · ' if r.get('implementation_version')=='neutral-modular/1' else '')+'共同前沿重构'
    demos=sum(r['id'] in labels or r['id']=='SE_PAIR' for r in manifest['components'])
    manifest['component_count']=len(manifest['components'])-demos;manifest['demonstration_count']=demos
    for name,var,value in [('manifest.js','COMPONENT_MANIFEST',manifest),('schedules.js','COMPONENT_SCHEDULE_PACKED',schedules),('regions.js','COMPONENT_ZONES',zones)]:
        (out/name).write_text('window.'+var+'='+json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')+';\n',encoding='utf-8')
    shell=(ROOT/'viewer/components.html').read_text(encoding='utf-8').replace('70 组件<br>＋ 1 并行示例',str(len(manifest['components']))+' 动画<br>组件 / 帧 / 并行 / 工厂')
    (out/'index.html').write_text(shell,encoding='utf-8')
    for name in ('components.css','components.js','lab-renderer.js','motion-preview.js','resource-schedule.js'):shutil.copyfile(ROOT/'viewer'/name,out/name)
    shell=shell.replace('<link rel="stylesheet" href="components.css">','<style>'+(out/'components.css').read_text(encoding='utf-8')+'</style>')
    tags=''.join('<script type="application/octet-stream" id="packed-'+k+'">'+v+'</script>' for k,v in payloads.items())
    shell=shell.replace('<script src="manifest.js"></script>',tags+'<script>'+(out/'manifest.js').read_text(encoding='utf-8')+'</script>')
    for name in ('schedules.js','regions.js','motion-preview.js','resource-schedule.js','lab-renderer.js','components.js'):
        shell=shell.replace(f'<script src="{name}"></script>','<script>'+(out/name).read_text(encoding='utf-8')+'</script>')
    for name in ('full-viewer.html','animation-library.html'):(out/name).write_text(shell,encoding='utf-8')
    write(out/'parallel-viewer-receipt.json',{'entries':len(manifest['components']),'examples':list(labels),'source_actions_modified':False,'user_visual_acceptance':'pending'})
    print(json.dumps({'entries':len(manifest['components']),'path':str(out/'animation-library.html')}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--allow-partial',action='store_true');a=p.parse_args();build(a.out,a.allow_partial)
