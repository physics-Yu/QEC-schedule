"""Export the same embeddable viewer for reports and application pages."""
import json
from pathlib import Path
from neutral_atom_env.replay.serializer import canonical_json


def javascript():
    directory=Path(__file__).parent
    shell=json.dumps((directory/'viewer-shell.html').read_text(encoding='utf-8'),ensure_ascii=False)
    return (directory/'viewer.js').read_text(encoding='utf-8').replace('__SHELL_JSON__',shell)


def write_bundle(directory):
    """Write dependency-free JS; mount any number of isolated viewers in an existing app."""
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/'atom-viewer.js';path.write_text(javascript(),encoding='utf-8')
    return path


def write_html(payload,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    data=canonical_json(payload).replace('<',r'\u003c')
    script=javascript().replace('</script',r'<\/script')
    path.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>原子运动可视化</title><body style="margin:0;background:#f4f6fa"><div id="atom-viewer"></div><script>'
        +script+'\nconst viewer=window.NeutralAtomViewer.mount(document.getElementById("atom-viewer"),'+data+');\n</script></body></html>',encoding='utf-8')
    return path
