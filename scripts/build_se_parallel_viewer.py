"""Package only newly qualified SE/shared-consumer examples with the current UI."""
from pathlib import Path
import argparse,json,shutil,hashlib
from build_component_gallery import build


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();out=Path(a.out)
    build(out)
    original=(out/'manifest.js').read_text(encoding='utf-8')
    manifest=json.loads(original.split('=',1)[1].strip().removesuffix(';'))
    stats={}
    for row in manifest['components']:
        atom=json.loads((out/row['id']/'atom-program.json').read_bytes())
        cz=[x for x in atom['actions'] if x['payload'].get('name')=='CZ']
        resets=[x for x in atom['actions'] if x['kind']=='reset' and 'AOD' in x['payload'].get('carrier_at_reset',{}).values()]
        stats[row['id']]={'cz_pulses':len(cz),'pairs_per_pulse':[len(x['payload']['pairs']) for x in cz],
            'aod_reset_actions':len(resets),'duration_us':row['duration_us']}
        if row['id']=='SE':
            row['description']=f"24 对耦合合并为 {len(cz)} 批 CZ；8 辅助在 AOD 内直接 reset；抓取、放回各 100 μs。"
        if row['id']=='SE_PAIR':
            row['description']=f"两个码块同层编译：{len(cz)} 批 CZ 共 48 对耦合；保留完整世界约束与原子身份。"
    new='window.COMPONENT_MANIFEST='+json.dumps(manifest,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')+';\n'
    (out/'manifest.js').write_text(new,encoding='utf-8')
    for name in ('index.html','full-viewer.html'):
        text=(out/name).read_text(encoding='utf-8').replace(original,new)
        text=text.replace('70 组件<br>＋ 1 并行示例',f"{manifest['component_count']} 组件<br>＋ 1 并行示例")
        text=text.replace('选择一段原子运动','SE 并行优化验收')
        text=text.replace('从逻辑门到辅助制备、蒸馏和连续协议。进入后查看运动、设备占用与执行记录。',
            'SE：5 批 CZ，24 对耦合；100 μs 交接；AOD 内直接 reset。另含双码块与 S/制备/蒸馏阶段的共享调用验证。')
        (out/name).write_text(text,encoding='utf-8')
    shutil.copyfile(out/'full-viewer.html',out/'animation-library.html')
    receipt={'schema_version':'SEParallelViewer/0.1','components':len(manifest['components']),'statistics':stats,
        'window':'animation-library.html','window_sha256':hashlib.sha256((out/'animation-library.html').read_bytes()).hexdigest(),
        'compiler_invoked_by_packager':False,'browser_rendering_verified':False,'user_visual_acceptance':'pending'}
    (out/'se-viewer-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'components':receipt['components'],'SE':stats['SE'],'SE_PAIR':stats['SE_PAIR']}))


if __name__=='__main__':main()
