"""Display-only projection of compiled actions and actual event receipts."""
from pathlib import Path
import argparse,base64,gzip,hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]

def read(path):
    raw=Path(path).read_bytes();return json.loads(gzip.decompress(raw) if str(path).endswith('.gz') else raw)
def write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def wait_diagnostics(atom,dags):
    """Recompute diagnostic waits without modifying frozen plans or receipts."""
    dags=dags if isinstance(dags,list) else [dags]
    source_groups={g['group_id']:g for d in dags for g in d['groups']}
    ends={a['id']:a['t_end_us'] for a in atom['actions']}
    done={s:max(ends[a] for a in aids) for s,aids in atom['source_map'].items()}
    qids={a['qubit_id']:a['atom_id'] for a in atom['initial_state']['atoms']}
    result=[]
    for group in atom.get('groups',[]):
        if group['group_id'] not in source_groups:continue
        source=source_groups[group['group_id']];depart=group['outbound']['start_us']
        waits={qids[m['physical_qubit_id']]:depart-max(done[s] for s in m['transport_after_op_ids']) for m in source['members']}
        assert all(v>=-1e-8 for v in waits.values())
        result.append({'group_id':group['group_id'],'departure_us':depart,'action_end_based_pre_transport_wait_us':waits})
    return {'schema_version':'readout-wait-diagnostic/0.1','groups':result,
            'scope':'Derived from preserved action endpoints and original source dependencies. Frozen v1 pre_transport_wait_us placeholders are not qualified waiting evidence.',
            'original_actions_and_event_receipts_modified':False}

def project(key,entries,device,phases,source_plans=()):
    initial=entries[0][0]['initial_state']['atoms'];ids={a['atom_id']:i for i,a in enumerate(initial)}
    atoms=[[a['atom_id'],a['qubit_id'],*a['position_um'],a['carrier'],a['aod_group'],a.get('site_id',a['qubit_id'])] for a in initial]
    actions=[];source_ids={};sources=[];results=[];points=[a['position_um'] for a in initial];raw_count=0;final=None
    for atom,trace in entries:
        for rid,r in trace['results'].items():
            assert r['origin']=='fake'
            results.append({'id':rid,'value':r['value'],'ready_us':r['ready_us']})
        events={e['action_id']:e for e in trace['events']}
        assert set(events)=={a['id'] for a in atom['actions']},'Every animation action needs its matching actual event'
        assert {a['atom_id'] for a in atom['initial_state']['atoms']}==set(ids),'Continuous component changed carriers'
        for a in atom['actions']:
            raw_count+=1;p=a['payload'];event=events[a['id']]
            assert event['status'] in ('completed','skipped')
            assert event['t_start_us']==a['t_start_us'] and event['t_end_us']==a['t_end_us']
            indices=[]
            for sid in a['source_ids']:
                if sid not in source_ids:source_ids[sid]=len(sources);sources.append(sid)
                indices.append(source_ids[sid])
            moves=[[ids[t['atom_id']],*t['from_um'],*t['to_um']] for t in p.get('trajectories',[])]
            for tr in moves:points.extend([tr[1:3],tr[3:5]])
            actions.append([a['t_start_us'],a['t_end_us'],a['kind'],[ids[x] for x in a['atoms']],moves,
                            [[ids[x] for x in pair] for pair in p.get('pairs',[])],p.get('name',''),event['status'],indices,[[ids[b['atom_id']],b['from_site_id'],b['to_site_id']] for b in p.get('site_bindings',[])]])
        final=trace['final_state']['atoms']
    actions.sort(key=lambda a:(a[0],a[1]))
    patches={}
    for a in initial:
        if '/d' in a['qubit_id']:
            pid=a['qubit_id'].rsplit('/',1)[0];patches.setdefault(pid,[]).append(a['position_um'])
    labels=[[k.replace('factory0:',''),sum(p[0] for p in ps)/len(ps),min(p[1] for p in ps)-10] for k,ps in patches.items()]
    end=max([a[1] for a in actions]+[p['end_us'] for p in phases]);mz=device['zones']['measurement']
    data={'id':key,'atoms':atoms,'actions':actions,'sources':sources,'results':sorted(results,key=lambda r:(r['ready_us'],r['id'])),'end':end,'phases':phases,'patches':labels,
          'bounds':[min(p[0] for p in points)-20,max(p[0] for p in points)+20,min(p[1] for p in points)-25,max(p[1] for p in points)+25],
          'measurement':[*mz['x_range_um'],*mz['y_range_um']],'readout_capacity':device.get('rigid_readout',{}).get('max_parallel_readouts',device['grouped_profile']['readout']['bank_capacity']),
          'raw_action_count':raw_count,'fake_scenario':True}
    # Independently evaluate every completed displacement; reject animation data
    # that would finish at a different position than the recorded event world.
    actual={a['atom_id']:a for a in final} if isinstance(final,list) else final
    coords={a[0]:a[2:4] for a in atoms};carrier={a[0]:a[4] for a in atoms};sites={a[0]:a[6] for a in atoms}
    for a in actions:
        if a[7]!='completed':continue
        for tr in a[4]:coords[atoms[tr[0]][0]]=tr[3:5]
        for i,old,new in a[9]:
            assert sites[atoms[i][0]]==old
            sites[atoms[i][0]]=new
        if a[2] in ('pickup','drop'):
            for i in a[3]:carrier[atoms[i][0]]='AOD' if a[2]=='pickup' else 'SLM'
    for aid,xy in coords.items():
        assert all(abs(x-y)<1e-8 for x,y in zip(xy,actual[aid]['position_um'])),(key,aid)
        assert carrier[aid]==actual[aid]['carrier']
        assert sites[aid]==actual[aid].get('site_id',actual[aid]['qubit_id'])
    phase_names={'raw_encoding':'原始 A 编码','SE':'SE 综合征提取','logical_CNOT':'逻辑 CNOT',
                 'stabilizer_preparation':'稳定子投影制备'}
    meta={}
    for plan in source_plans:
        for d in plan.get('physical_dags', []):
            for o in d['nodes']:
                m=o.get('metadata',{});phase=m.get('phase')
                if m.get('protocol')=='surface17-neutral-s-se/1':label='S-SE · '+('半轮折叠' if m.get('se_stage') else '综合征耦合/读出')
                elif phase:label=phase_names.get(phase,phase)
                elif m.get('preparation'):label='稳定子投影制备'
                elif 'syndrome_layer' in m:label='SE 综合征耦合'
                elif 'magic_read' in o['id'] or 'consume_output' in o['id']:label='魔态逻辑读出'
                elif 'cleanup' in o['id']:label='清理 / 复位'
                elif 'terminal_' in o['id']:label='蒸馏终端检查'
                else:label={'measure':'测量','classical':'经典处理','reset':'复位','permute':'物理置换'}.get(o['kind'],d.get('operation','物理门'))
                if phase=='logical_CNOT':
                    label=('反计算 CNOT' if 'uncompute' in o['id'] else '奇偶汇聚 CNOT' if 'fanin' in o['id'] else '魔态注入 CNOT' if 'inject' in o['id'] or 'consume_cnot' in o['id'] else label)
                meta[o['id']]={'label':label,'phase':phase,'blocks':list(dict.fromkeys(q.rsplit('/',1)[0] for q in o['qubits'])),
                               'source_gate':o['params'].get('name',o['kind']),'round':m.get('se_round')}
    data['source_meta']=[meta.get(s) for s in sources]
    data['joint_frontiers']=[f for p in source_plans for f in p.get('module_composition',{}).get('dependency_graph',{}).get('joint_frontiers',[])]
    return data

DESCRIPTIONS={
 'SE_PAIR':'两个 canonical patch 的完整 SE 联合编译；真实 CZ 广播合并两块配对，八路读出按容量分批。',
 'X':'在逻辑 X 支撑链上执行三个物理 X 门；本组件无需运输，画面标出实际受门作用的原子。',
 'Z':'在逻辑 Z 支撑链上执行三个物理 Z 门；本组件无需运输，画面标出实际受门作用的原子。',
 'SE':'完整一轮综合征提取：辅助复位 → 基变换 → 稳定子耦合 → 八辅助共同测量、复位与返回。',
 'H':'九个物理 H 同时执行，随后以真实原子搬运完成 90° 数据位置置换。无 SWAP 门、无 CZ；原子身份固定，数据位映射在到达后提交。',
 'CZ':'完整逻辑 CZ：目标块基变换、横向逻辑 CX、目标块基变换。',
 'CX':'两个完整编码块之间的九对横向 CX；方向由源电路保留。',
 'S':'Y+ 辅助制备、联合 ZZ、辅助 X 读出和条件逻辑 Z 修正。',
 'SDG':'Y− 辅助制备、联合 ZZ、辅助 X 读出和条件逻辑 Z 修正。',
 'MEASURE_Z':'九个数据原子保持阵列形状，一次移入测量区、同时 Z 读出、统一返回；逻辑结果取 Z 支撑链奇偶。',
 'MEASURE_X':'九个并行物理 H 后整体送入测量区，九个数据同时读出并求逻辑 X 奇偶；无需 H 的位置置换。',
 'READ_Z_CLEANUP':'九个 data 同批 Z 读出、计算逻辑 Z 奇偶，保留源电路明确要求的数据与辅助复位清理。',
 'READ_X_CLEANUP':'九个 data 经物理 H 基变换后同批读出，计算逻辑 X 奇偶并完成源电路要求的复位清理。',
 'RESET_Z':'重新构造编码 |0〉：数据复位、完整综合征提取与显式符号修正。',
 'JOINT_ZZ':'完整合并 / 分离联合 ZZ 电路，包含测量、反馈与后续 SE。',
 'T':'连续 15→1 蒸馏、同载体转换和交接、T 消费、条件 S 修正与清理。',
 'TDG':'连续 15→1 蒸馏、同载体交接、T† 消费、条件 S† 修正与清理。',
 'REJECT_RETRY':'终端检查触发拒收 → 实际清理 → 释放资源 → 相同载体启动下一 epoch 的初始化。',
 'FACTORY_READY':'定位到 T 连续协议的输出转换末端；READY 发布是控制事件，本身不新增原子移动。',
 'RESERVE_DELIVERY':'定位到同载体预约交接与随后消费；交接本身不把状态或原子瞬移。',
 'CLASSICAL_POSTPROCESS':'先显示八个演示输入位的读出，再按 MSB 顺序执行 N=15、a=2 的经典后处理。',
 'PARITY':'先产生演示输入测量位，再执行 XOR；经典计算本身没有原子位移。',
 'ACCEPT':'先产生演示输入测量位，再执行 all_zero；这只演示接受判定组件。'}

def stage_label(stage,gate='T'):
    if stage.startswith(('rotate_','correct_','finish_')):
        kind,index=stage.rsplit('_',1)
        return f"第 {int(index)+1} 项"+{'rotate':'相位注入','correct':'条件 S 修正','finish':'反计算与 SE'}[kind]
    return {'initialize':'原始 A 态与工作块制备','terminal_checks':'四个末端 X 检查','convert_output':'同载体输出转换',
            'consume':'数据块 '+('T†' if gate=='TDG' else 'T')+' 消费','consume_correction':'消费条件 '+('S†' if gate=='TDG' else 'S')+' 修正',
            'consume_cleanup':'工厂清理与数据块 SE','reject_cleanup':'拒收清理'}.get(stage,stage)

MODULAR_DESCRIPTIONS={
 'SE_PAIR':'两个 canonical patch 的完整 SE 由已编译层组合；耦合按整组候选选批，读出通道无上限。',
 'CX':'九对 transversal CX 下降为并行基变换、一次原生 CZ 广播和真实整阵列往返。',
 'CZ':'消去相邻物理 H：实际代码位运输置换 → 九对原生 CZ → 实际运输置换；保留逻辑编码语义。',
 'S':'S-SE：前半轮 SE → 镜像配对 CZ 与指定位置 S/S† → 后半轮 SE 和读出；仅使用当前17原子码块。',
 'SDG':'逆相位 S-SE；反转折叠层单比特相位，保持CZ配对、完整SE及辅助读出。',
 'PREPARE_ZERO':'物理零态初始化、并行稳定子投影与测量条件符号修正；物理全零不直接等同逻辑零。',
 'PREPARE_PLUS':'物理加态初始化、并行稳定子投影与测量条件符号修正。',
 'PREPARE_Y_PLUS':'编码加态制备 → 已编译 S-SE 模块；不再经过旧38-CX通用编码器和额外Y消费回路。',
 'PREPARE_Y_MINUS':'编码加态制备 → 已编译逆相位 S-SE 模块。',
 'PREPARE_A':'物理 T 种子与9-CX编码网络，再接显式SE；编码与SE分别标注，原生2Q为CZ。原始注入未声明容错。',
 'JOINT_ZZ':'在保持逻辑ZZ的上下边代表链中按距离选变体，并分配邻近辅助；完整保留合并、拆分和修正。',
 'T':'等待模块依赖构建完成后，纯组合15→1工厂、同载体交接、T消费与反馈；此任务不重新搜索布局路由。',
 'TDG':'复用相同模块库组合T†完整协议，保留不同的条件S†分支与同载体消费。'}

def build(out,allow_partial=False):
    out=Path(out);catalog=read(out/'catalog.json');rows=[];receipts=[];packed={}
    if (out/'SE_PAIR/summary.json').is_file():
        catalog['components'].insert(1,{'id':'SE_PAIR','label':'SE × 2 · 同层并行示例','category':'逻辑原语','kind':'physical'})
    def emit_data(key,data,directory):
        relative=directory/'motion-data.js';dest=out/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        raw=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
        packed[key]=base64.b64encode(gzip.compress(raw.encode('utf-8'),compresslevel=1,mtime=0)).decode('ascii')
        dest.write_text('window.COMPONENT_DATA=window.COMPONENT_DATA||{};window.COMPONENT_DATA['+json.dumps(key)+']='+raw+';\n',encoding='utf-8')
        write(dest.with_suffix('.receipt.json'),{'all_actions_preserved':True,'action_count':len(data['actions']),'sha256':sha(dest),'all_final_positions_match':True})
        return str(relative).replace('\\','/')
    for row in catalog['components']:
        r=dict(row);key=row['id'];folder=out/key
        if key.startswith('factory.'):
            r['label']='15→1 · '+stage_label(row['stage_id'],row.get('gate','T'))
        if row['kind']=='physical':
            if not (folder/'summary.json').is_file():
                if allow_partial:continue
                raise ValueError('MISSING_COMPONENT '+key)
            summary=read(folder/'summary.json');assert summary['status']=='passed'
            atom,trace=read(folder/'atom-program.json'),read(folder/'event-trace.json');device=read(folder/'device.json')
            diagnostic=wait_diagnostics(atom,read(folder/'physical-dag.json'));write(folder/'readout-wait-diagnostic.json',diagnostic)
            plan=read(folder/'physical-plan.json')
            data=project(key,[(atom,trace)],device,[{'id':key,'label':r['label'],'start_us':0,'end_us':summary['duration_us'],'note':'实际完整编译片段'}],source_plans=[plan])
            data['modules']=plan.get('module_composition',{}).get('instances',[])
            data['geometry_variants']=plan['physical_dags'][0].get('geometry_variant_selection',[]) if plan.get('physical_dags') else []
            r.update(summary);r['data_id']=key;r['data_path']=emit_data(key,data,Path(key))
            r['links']=[{'label':'完整电路与动作查看器','href':key+'/full-viewer.html'},{'label':'源物理 DAG','href':key+'/physical-dag.json'},{'label':'检查报告','href':key+'/validation.json'},{'label':'场景输入','href':key+'/scenario.json'}]
            if key=='CLASSICAL_POSTPROCESS' and (folder/'negative-check.json').is_file():
                r['links'].append({'label':'零相位失败反例','href':key+'/negative-check.json'})
            if (folder/'source-semantics.json').is_file():
                r['links'].append({'label':'源电路语义检查','href':key+'/source-semantics.json'})
            if diagnostic['groups']:r['links'].append({'label':'动作导出的读出等待','href':key+'/readout-wait-diagnostic.json'})
            r['scope']='此组件采用 canonical 入口几何。独立蒸馏阶段的量子输入条件由协议声明；完整连续消费见 T / T†。测量值为显式 fake 场景。'
            if summary.get('preview_input_operations'):r['scope']+=' 前置演示测量用于提供外部输入位，未计入该组件本体的物理操作数。'
            receipts.append({'id':key,'atom_sha256':sha(folder/'atom-program.json'),'trace_sha256':sha(folder/'event-trace.json'),'actions':len(data['actions'])})
        else:
            target='T' if key in ('FACTORY_READY','RESERVE_DELIVERY') else key;pf=out/'protocols'/target
            if not (pf/'summary.json').is_file():
                if allow_partial:continue
                raise ValueError('MISSING_CONTINUOUS_COMPONENT '+key)
            summary=read(pf/'summary.json');assert summary['status']=='passed'
            phases=[dict(p,label=f"epoch {p['epoch']} · {stage_label(p['stage_id'],target)}",note=p['stage_id']+' · 同一事件会话') for p in summary['phases']]
            if key in ('FACTORY_READY','RESERVE_DELIVERY'):
                stage='convert_output' if key=='FACTORY_READY' else 'consume'
                phases=[p for p in phases if p['stage_id']==stage]
            entries=[]
            diagnostics=[]
            modules=[];source_plans=[]
            for p in phases:
                raw=read(pf/p['artifact']);entries.append((raw['atom_program'],raw['trace']));source_plans.append(raw['physical_plan'])
                for m in raw['physical_plan'].get('module_composition',{}).get('instances',[]):
                    modules.append({**m,'stage_id':p['stage_id'],'start_us':m['start_us']+p['start_us'],'end_us':m['end_us']+p['start_us']})
                diagnostics.append({'stage':p['id'],**wait_diagnostics(raw['atom_program'],raw['physical_plan']['physical_dags'])})
            write(pf/(key+'-readout-wait-diagnostic.json'),{'stages':diagnostics,'original_actions_and_event_receipts_modified':False})
            # Lifecycle viewers replay only the physically relevant same-session
            # segment, preserving model time with a uniform display time origin.
            if key in ('FACTORY_READY','RESERVE_DELIVERY'):
                origin=phases[0]['start_us']
                for atom,trace in entries:
                    for a in atom['actions']:a['t_start_us']-=origin;a['t_end_us']-=origin
                    for e in trace['events']:e['t_start_us']-=origin;e['t_end_us']-=origin
                    for r in trace['results'].values():r['ready_us']-=origin
                for p in phases:p['start_us']-=origin;p['end_us']-=origin;p['note']='显示相对阶段时间；控制交接本身无虚构运动'
                for m in modules:m['start_us']-=origin;m['end_us']-=origin
            data=project(key,entries,read(pf/'device.json'),phases,source_plans=source_plans)
            data['modules']=modules
            r.update(summary,id=key,label=row['label'],category=row['category'],kind=row['kind'],component_id=key,
                     physical_operations=sum(p['physical_operations'] for p in phases),action_count=len(data['actions']),duration_us=data['end'])
            r['data_id']=key;r['data_path']=emit_data(key,data,Path('protocols')/key)
            r['links']=[{'label':'连续协议与分支记录','href':'protocols/'+target+'/controller.json'},{'label':'阶段验收与时序','href':'protocols/'+target+'/summary.json'},{'label':'资源生命周期','href':'protocols/'+target+'/pool.json'}]
            r['links'].append({'label':'动作导出的读出等待','href':'protocols/'+target+'/'+key+'-readout-wait-diagnostic.json'})
            r['scope']='动画来自同一持续 EventSession 的实际完成/跳过事件；保留原子身份、分支结果和资源生命周期。不是完整 Shor 算法运行或量子态模拟。'
            receipts.append({'id':key,'summary_sha256':sha(pf/'summary.json'),'actions':len(data['actions'])})
        r['executed_action_count']=sum(a[7]=='completed' for a in data['actions'])
        r['skipped_action_count']=sum(a[7]=='skipped' for a in data['actions'])
        if r['skipped_action_count']:r['scope']+=f" 本场景有{r['skipped_action_count']}个条件动作跳过；计划和事件记录完整保留。"
        r['description']=(MODULAR_DESCRIPTIONS.get(key) if r.get('implementation_version')=='neutral-modular/1' else None) or DESCRIPTIONS.get(key,'完整源组件展开、物理编译及原子事件回放。')
        r['version_status']='当前模块配方' if r.get('implementation_version')=='neutral-modular/1' else '历史冻结工件'
        if r.get('implementation_version')=='neutral-modular/1':r['scope']+=' 模块来源、依赖与搜索计数可在模块面板查看；原始A注入与联合ZZ未声明噪声容错资格。'
        if any(a[2]=='measure' for a in data['actions']):r['scope']+=' 读出并行数：'+('无上限（本次用户指定模型）' if data['readout_capacity'] is None else str(data['readout_capacity'])+'（该工件冻结配置）')+'。'
        rows.append(r)
    coverage=read(out/'shor-coverage.json')
    manifest={'schema_version':'component-gallery/0.1','components':rows,'component_count':sum(r['id']!='SE_PAIR' for r in rows),
              'demonstration_count':sum(r['id']=='SE_PAIR' for r in rows),'coverage':{k:v for k,v in coverage.items() if k!='logical_node_components'},'user_visual_acceptance':'pending','browser_verified':False}
    (out/'manifest.js').write_text('window.COMPONENT_MANIFEST='+json.dumps(manifest,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')+';\n',encoding='utf-8')
    write(out/'gallery-receipt.json',{'components':len(rows),'projection_receipts':receipts,'browser_verified':False,'user_visual_acceptance':'pending'})
    for name in ['components.html','components.js','components.css','motion-preview.js','resource-schedule.js','lab-renderer.js']:shutil.copyfile(ROOT/'viewer'/name,out/('index.html' if name.endswith('.html') else name))
    standalone=(out/'index.html').read_text(encoding='utf-8')
    standalone=standalone.replace('<link rel="stylesheet" href="components.css">','<style>'+ (out/'components.css').read_text(encoding='utf-8')+'</style>')
    data_tags=''.join('<script type="application/octet-stream" id="packed-'+key+'">'+value+'</script>' for key,value in packed.items())
    standalone=standalone.replace('<script src="manifest.js"></script>',data_tags+'<script>'+(out/'manifest.js').read_text(encoding='utf-8')+'</script>')
    standalone=standalone.replace('<script src="motion-preview.js"></script>','<script>'+(out/'motion-preview.js').read_text(encoding='utf-8')+'</script>')
    standalone=standalone.replace('<script src="components.js"></script>','<script>'+(out/'components.js').read_text(encoding='utf-8')+'</script>')
    (out/'full-viewer.html').write_text(standalone,encoding='utf-8')
    # Display resource schedules read frozen actions; this does not invoke compilation.
    from export_viewer_schedules import export as export_schedules
    export_schedules(out)
    from export_viewer_regions import export as export_regions
    export_regions(out)
    for name in ('resource-schedule.js','schedules.js','regions.js','lab-renderer.js'):
        standalone=standalone.replace(f'<script src="{name}"></script>', '<script>'+(out/name).read_text(encoding='utf-8')+'</script>')
    (out/'full-viewer.html').write_text(standalone,encoding='utf-8')
    write(out/'standalone-receipt.json',{'components':len(rows),'file':'full-viewer.html','bytes':(out/'full-viewer.html').stat().st_size,
           'sha256':sha(out/'full-viewer.html'),'embedded_motion_datasets':len(packed),'external_display_assets_required':False,
           'evidence_links_require_original_directory':True,'browser_verified':False})
    print(json.dumps({'components':len(rows),'path':str((out/'index.html').resolve())},ensure_ascii=False))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='artifacts/demos/logical-components-20261007');ap.add_argument('--allow-partial',action='store_true');args=ap.parse_args();build(ROOT/args.out,args.allow_partial)
