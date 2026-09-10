"""One report entry point; failed scenarios never retain an old PASS result."""
import html
import json
from pathlib import Path
from dataclasses import asdict
from .scenarios import SCENARIOS
from .artifacts import page
from .renderer import render_layout, render_dag, write_scene
from .theme import VisualTheme
from neutral_atom_env.replay.serializer import canonical_json, primitive
from neutral_atom_env.domain.errors import ConstraintViolation
from neutral_atom_env.domain.models import Position2D


def _write(path,value):
    Path(path).write_text(canonical_json(value),encoding='utf-8')


def render_report(root, theme=None):
    """Re-render saved evidence only; no simulator or scenario execution."""
    root=Path(root);theme=theme or VisualTheme.load()
    manifest=json.loads((root/'results.json').read_text(encoding='utf-8'))
    sections=[]
    for group in manifest:
        name=group['id'];directory=root/name
        body=f'<p><b>验证问题：</b>{html.escape(group["question"])}</p>'
        if group['passed']:
            body+='<pre style="white-space:pre-wrap;max-height:320px;overflow:auto">'+html.escape(json.dumps(group['checks'],ensure_ascii=False,indent=2))+'</pre>'
            for frame in group['frames']:
                snapshot=(directory/frame['snapshot']).read_text(encoding='utf-8')
                body+=f'<h2>{html.escape(frame["description"])}</h2>'
                if frame['view']!='data':
                    renderer=render_dag if frame['view']=='dag' else render_layout
                    for suffix in ('svg','png'):renderer(snapshot,directory/f'{frame["name"]}.{suffix}',theme)
                    if frame['view']=='layout':write_scene(snapshot,directory/f'{frame["name"]}.scene.json')
                    body+=f'<img src="{name}/{frame["name"]}.svg" alt="{html.escape(frame["description"])}">'
                body+=f'<nav><a href="{name}/{frame["snapshot"]}">快照数据</a>'
                if frame['view']!='data':body+=f'<a href="{name}/{frame["name"]}.svg">放大 SVG</a>'
                body+='</nav>'
            for i,item in enumerate(group['violations']):
                v=ConstraintViolation(**(item|{'atom_ids':tuple(item['atom_ids']),
                    'position':Position2D(**item['position']) if item['position'] else None}))
                base=(directory/'diagnostic_base.json').read_text(encoding='utf-8')
                render_layout(base,directory/f'error_{i}.svg',theme,v)
                body+=f'<details><summary style="color:{theme.failure_color};padding:16px;cursor:pointer">{html.escape(v.code)} · {html.escape(", ".join(v.atom_ids))} · holder {html.escape(str(v.holder_id))}</summary><p>{html.escape(v.message)}</p>'
                body+='<p class="muted">背景是最后一个合法初始布局；红圈指向涉及原子，红叉是验证器返回的非法位置（越界坐标投影至图边界）。非法状态未提交。</p>'
                body+=f'<img src="{name}/error_{i}.svg" alt="{html.escape(v.code)}"></details>'
            body+=f'<nav><a href="{name}/trace.jsonl">事件 / 逻辑 trace</a></nav>'
        else:
            body+=f'<pre style="color:{theme.failure_color}">{html.escape(group["error"])}</pre>'
        status='PASS' if group['passed'] else 'FAIL'
        sections.append(f'<section class="card"><header><h2>{html.escape(group["title"])}</h2><span class="badge {"" if group["passed"] else "fail"}">{status}</span></header><div style="padding:24px">{body}</div></section>')
    machine=root/'machine-tests.json'
    summary=''
    if machine.exists():
        data=json.loads(machine.read_text(encoding='utf-8'))
        passed=sum(t['outcome']=='passed' for t in data['tests']);failed=sum(t['outcome']=='failed' for t in data['tests'])
        summary=f'<p>最近一次机器测试：{passed} passed / {failed} failed；exit status {data["exitstatus"]}。</p><nav><a href="machine-tests.json">机器测试结果（不生成重复图片）</a></nav>'
    body='<h1>Milestone 0 · 基础验收报告</h1><p>场景、机器断言与渲染使用同一份输入。每幅图对应一个明确状态。</p><p class="muted">只验收已实现的初始化、逻辑 DAG、事件提交和快照恢复。逻辑完成序列不代表执行物理 CZ；没有模拟运输、激光或测量设备过程。PNG / SVG 使用同一场景与主题。</p>'+summary+'<nav><a href="results.json">结构化验收结果</a></nav>'+''.join(sections)
    (root/'index.html').write_text(page('Milestone 0 基础验收',body),encoding='utf-8')


def build_report(root='artifacts/acceptance'):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    groups=[]
    # Invalidate the prior report before starting, so an interrupted run cannot look successful.
    (root/'index.html').write_text(page('验收生成中','<h1>验收正在重新生成</h1><p>本轮尚未完成。</p>'),encoding='utf-8')
    for name,title,question,run in SCENARIOS:
        directory=root/name;directory.mkdir(parents=True,exist_ok=True)
        group={'id':name,'title':title,'question':question,'passed':False,'frames':[],'violations':[]}
        try:
            evidence=run();group.update(passed=True,checks=evidence.checks,violations=primitive(evidence.violations))
            for frame in evidence.frames:
                filename=frame.name+'.json';(directory/filename).write_text(frame.snapshot,encoding='utf-8')
                group['frames'].append({'name':frame.name,'description':frame.description,'snapshot':filename,'view':frame.view})
            if evidence.diagnostic_base:(directory/'diagnostic_base.json').write_text(evidence.diagnostic_base,encoding='utf-8')
            (directory/'trace.jsonl').write_text(''.join(canonical_json(e)+'\n' for e in evidence.trace),encoding='utf-8')
        except Exception as error:
            group.update(passed=False,error=f'{type(error).__name__}: {error}')
        groups.append(group)
    _write(root/'results.json',groups)
    render_report(root)
    if root.resolve()==Path('artifacts/acceptance').resolve():
        legacy=Path('artifacts/tests/index.html');legacy.parent.mkdir(parents=True,exist_ok=True)
        legacy.write_text('<meta charset="utf-8"><meta http-equiv="refresh" content="0;url=../acceptance/index.html"><a href="../acceptance/index.html">统一验收入口</a>',encoding='utf-8')
    if not all(g['passed'] for g in groups):raise RuntimeError('Acceptance failed; inspect results.json')
    return groups


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',default='artifacts/acceptance')
    parser.add_argument('--rerender',action='store_true')
    parser.add_argument('--theme')
    args=parser.parse_args()
    if args.rerender:render_report(args.root,VisualTheme.load(args.theme))
    else:build_report(args.root)
