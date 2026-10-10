"""Read-only projection of bounded interface calls into the existing lab viewer."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys,shutil
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from build_component_gallery import project
from extend_frame_gallery import packed
from export_viewer_schedules import lanes,carrier_occupancy
from na_pipeline.device import canonical_surface17_device


def export(root,cx_root):
    out=root/'viewer';out.mkdir(exist_ok=True);(out/'data').mkdir(exist_ok=True)
    acceptance=json.loads((root/'acceptance.json').read_bytes());assert acceptance['passed']
    entries=[]
    for case,label in [('horizontal','CNOT · 横向'),('vertical','CNOT · 纵向'),('diagonal','CNOT · 斜向'),('distant_spectator','CNOT · 加入旁观码块')]:
        entries.append((case,label,'同一模板，不同位置',cx_root/case))
    for i,row in enumerate(acceptance['continuous_gate_calls']):
        entries.append(('GATE_'+str(i),str(i+1)+' · '+row['component']+' · 连续调用','同一现场，连续调用',root/('gate-'+str(i))))
    for target in ('w1','w3'):
        entries.append(('CONSUME_'+target,'消费接口 → '+target,'同一消费组件，不同 data 目标',root/('consumer-'+target)))
    device=canonical_surface17_device();rows=[];data_packed={};schedules={};zones={}
    for key,label,category,folder in entries:
        plan=json.loads((folder/'physical-plan.json').read_bytes())
        atom=json.loads((folder/'atom-program.json').read_bytes()) if (folder/'atom-program.json').exists() else plan['atom_program']
        trace=json.loads((folder/'event-trace.json').read_bytes())
        origin=min(a['t_start_us'] for a in atom['actions']);end=trace['stats']['t_end_us']
        data=project(key,[(atom,trace)],device,[{'id':key,'label':label,'start_us':origin,'end_us':end,
            'note':'从实际接口调用工件投影；不是新的整厂运行'}],source_plans=[plan])
        for a in data['actions']:a[0]-=origin;a[1]-=origin
        for r in data['results']:r['ready_us']-=origin
        for p in data['phases']:p['start_us']-=origin;p['end_us']-=origin
        data['end']-=origin;data['modules']=[]
        events={e['action_id']:e for e in trace['events']}
        records=sorted([(a['t_start_us']-origin,a['t_end_us']-origin,a,events[a['id']]['status']) for a in atom['actions']],key=lambda t:(t[0],t[1]))
        resources=[];rids={};tracks={}
        for i,(begin,finish,action,status) in enumerate(records):
            assert data['actions'][i][:3]==[begin,finish,action['kind']]
            if status!='completed':continue
            for lane,rs in lanes(action).items():
                for r in rs:
                    if r not in rids:rids[r]=len(resources);resources.append(r)
                tracks.setdefault(lane,[]).append([begin,finish,i,[rids[r] for r in rs]])
        schedule={'schema_version':'ViewerResources/0.1','id':key,'end':data['end'],'resource_names':resources,
            'lanes':[{'id':k,'kind':'activity' if k.startswith('activity:') else 'declared_resources','intervals':v} for k,v in tracks.items()]}
        schedule['lanes']+=carrier_occupancy(records,{a[0]:a[5] for a in data['atoms']},data['end'])
        receipt=plan['parametric_component_instance']
        consumer=key.startswith('CONSUME_')
        rows.append({'id':key,'data_id':key,'data_path':'data/'+key+'.js','label':label,'category':category,'kind':'physical',
            'description':('目标由 data 端口绑定；完整205原子现场。' if consumer else '同一份内部操作和批次，实际位置在调用时绑定。'),
            'scope':('消费组件的几何/源操作检查；魔态为测试输入契约，本次没有启动蒸馏，也没有发布 ready token。' if consumer else '接口调用的实际 fake 事件，原子身份和当前码位连续。')+
                '模板 '+receipt['component_template_id']+'；内部重建/重新选批次均为0；连接工作 '+json.dumps(receipt['connection_work'],ensure_ascii=False),
            'atom_count':len(data['atoms']),'action_count':len(data['actions']),'duration_us':data['end'],
            'physical_operations':sum(len(d['nodes']) for d in plan['physical_dags']),
            'version_status':'接口局部验收','links':[{'label':'本次接口验收','href':'../acceptance.json'},
                {'label':'接口使用说明','href':'../../../../knowledge/interfaces/component-data-ports.md'}]})
        data_packed[key]=packed(data);schedules[key]=packed(schedule)
        (out/'data'/(key+'.js')).write_text('window.COMPONENT_DATA=window.COMPONENT_DATA||{};window.COMPONENT_DATA['+json.dumps(key)+']='+json.dumps(data,ensure_ascii=False).replace('<','\\u003c')+';',encoding='utf-8')
        cz=device['zones']['storage_entanglement'];mz=device['zones']['measurement']
        zones[key]={'compute':[*cz['x_range_um'],*cz['y_range_um']],'measurement':[*mz['x_range_um'],*mz['y_range_um']]}
    manifest={'schema_version':'component-gallery/0.1','components':rows,'component_count':len(rows),'demonstration_count':0,
              'coverage':{'logical_nodes':0},'user_visual_acceptance':'pending','browser_verified':False}
    for name,value in [('manifest',manifest),('schedules',schedules),('regions',zones)]:
        var={'manifest':'COMPONENT_MANIFEST','schedules':'COMPONENT_SCHEDULE_PACKED','regions':'COMPONENT_ZONES'}[name]
        (out/(name+'.js')).write_text('window.'+var+'='+json.dumps(value,ensure_ascii=False).replace('<','\\u003c')+';',encoding='utf-8')
    for name in ('components.js','components.css','motion-preview.js','resource-schedule.js','lab-renderer.js'):
        shutil.copyfile(ROOT/'viewer'/name,out/name)
    html=(ROOT/'viewer/components.html').read_text(encoding='utf-8')
    html=html.replace('选择一段原子运动','接口验收 · 同一组件，不同实例').replace('70 组件<br>＋ 1 并行示例','12 项局部调用')
    html=html.replace('从逻辑门到辅助制备、蒸馏和连续协议。进入后查看运动、设备占用与执行记录。',
        '横向、纵向、斜向 CNOT；同一现场连续调用；切换 data 消费目标。本次未运行整个工厂。')
    (out/'index.html').write_text(html,encoding='utf-8')
    html=html.replace('<link rel="stylesheet" href="components.css">','<style>'+(out/'components.css').read_text(encoding='utf-8')+'</style>')
    html=html.replace('<script src="manifest.js"></script>',''.join('<script type="application/octet-stream" id="packed-'+key+'">'+value+'</script>' for key,value in data_packed.items())+'<script>'+(out/'manifest.js').read_text(encoding='utf-8')+'</script>')
    for name in ('schedules.js','regions.js','motion-preview.js','resource-schedule.js','lab-renderer.js','components.js'):
        html=html.replace('<script src="'+name+'"></script>','<script>'+(out/name).read_text(encoding='utf-8')+'</script>')
    (out/'full-viewer.html').write_text(html,encoding='utf-8')
    (out/'animation-library.html').write_text(html,encoding='utf-8')
    print(json.dumps({'viewer':str((out/'animation-library.html').resolve()),'calls':len(rows),'compiler_invoked':False},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--cx',type=Path,required=True)
    args=p.parse_args();export(args.out,args.cx)
