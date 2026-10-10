"""Label the frozen gallery as a preview; never compile or modify atom actions."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/demos/joint-factory-accepted-20261008'
NOTICE = '已编译预览 · 并行修复中：部分已选门批次仍被下游拆批；运动与设备时间表来自冻结工件。'


def main():
    manifest_path = OUT / 'manifest.js'
    old_manifest = manifest_path.read_text(encoding='utf-8')
    manifest = json.loads(old_manifest.split('=', 1)[1].strip().removesuffix(';'))
    manifest['release_status'] = 'compiled_preview_parallel_repair_pending'
    manifest['parallel_compilation_goal_met'] = False
    manifest['release_notice'] = NOTICE
    for row in manifest['components']:
        row['version_status'] = ('当前模块配方 · ' if row.get('implementation_version') == 'neutral-modular/1' else '') + '已编译预览'
    new_manifest = 'window.COMPONENT_MANIFEST=' + json.dumps(manifest, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c') + ';\n'
    manifest_path.write_text(new_manifest, encoding='utf-8')
    js_path = OUT / 'components.js'
    old_js = js_path.read_text(encoding='utf-8')
    new_js = old_js.replace(' · 工程检查通过 · 视觉待验', ' · 几何/事件已检查 · 并行修复中 · 视觉待验')
    js_path.write_text(new_js, encoding='utf-8')
    banner = '<aside data-release-preview="true" style="padding:8px 24px;background:#f1f4f2;color:#496055;border-bottom:1px solid #dce4df;font-size:12px;line-height:1.6">' + NOTICE + '</aside>'
    files = {}
    for name in ('index.html', 'full-viewer.html', 'animation-library.html'):
        path = OUT / name
        before = path.read_text(encoding='utf-8')
        packed_before = re.findall(r'id="packed-([^\"]+)">([^<]+)</script>', before)
        after = before.replace(old_manifest, new_manifest).replace(old_js, new_js)
        if 'data-release-preview="true"' not in after:
            after = after.replace('</header>', '</header>' + banner, 1)
        assert re.findall(r'id="packed-([^\"]+)">([^<]+)</script>', after) == packed_before
        path.write_text(after, encoding='utf-8')
        files[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
    result = {'schema_version': 'FrozenPreviewRelease/0.1', 'entries': len(manifest['components']),
              'status': manifest['release_status'], 'compiled_actions_modified': False,
              'embedded_motion_payloads_unchanged': True, 'new_compilation_performed': False,
              'parallel_compilation_goal_met': False, 'browser_verified': False,
              'user_visual_acceptance': 'pending', 'files': files,
              'known_issue': {'stage': 'T/e0-initialize', 'module': 'module:6',
                              'code': 'POST_SELECTION_RESERIALIZED', 'selected_pairs': 12, 'actual_CZ_batches': 2},
              'compiled_run': '20261008T074911655280Z-t044-joint-factory-frontier-v3',
              'proof_seal_run': '20261008T084526491733Z-t044-joint-factory-proof-seal'}
    (OUT / 'preview-release.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    standalone_receipt = {'components': result['entries'], 'file': 'full-viewer.html',
                          **files['full-viewer.html'], 'embedded_motion_datasets': result['entries'],
                          'external_display_assets_required': False,
                          'evidence_links_require_original_directory': True,
                          'browser_verified': False, 'user_visual_acceptance': 'pending',
                          'release_status': result['status'], 'release_receipt': 'preview-release.json'}
    (OUT / 'standalone-receipt.json').write_text(json.dumps(standalone_receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'entries': result['entries'], 'status': result['status'], 'motion_unchanged': True}))


if __name__ == '__main__':
    main()
