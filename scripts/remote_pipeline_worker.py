"""Execute a frozen T704 argv in a project-only environment under jobs.py."""
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import sysconfig
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'scripts/outputs/T704'


def save(name,value):
    OUT.mkdir(parents=True,exist_ok=True)
    p=OUT/name
    tmp=p.with_suffix('.tmp')
    tmp.write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    os.replace(tmp,p)


def main():
    spec=json.loads((OUT/'job-spec.json').read_bytes())
    inventory=json.loads((OUT/'source-inventory.json').read_bytes())
    def verify():
        for name,digest in inventory.items():
            path=(ROOT/name).resolve()
            if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError('FROZEN_SOURCE_CHANGED: '+name)
    verify()
    state={'status':'environment_setup','started_at_utc':datetime.now(timezone.utc).isoformat(),'input_snapshot_verified':True,'command':spec['argv'],'budget':spec['budget'],'stage_kind':spec['stage_kind'],'full_program_passed':False}
    save('worker-receipt.json',state)
    try:
        environment=ROOT/'scripts/.venv'
        venv.EnvBuilder(with_pip=False).create(environment)
        python=environment/'bin/python'
        temporary=OUT/'temporary';temporary.mkdir(exist_ok=True)
        # Reuse download bytes only, isolated by lock, interpreter and platform.
        # Each job still gets its own environment, runtime state and validation.
        interpreter=Path(sys.executable).resolve()
        cache_identity={'lock_sha256':hashlib.sha256((ROOT/'third_party/enola/requirements.lock').read_bytes()).hexdigest(),'interpreter_sha256':hashlib.sha256(interpreter.read_bytes()).hexdigest(),'python':sys.version,'platform':platform.platform(),'machine':platform.machine(),'soabi':sysconfig.get_config_var('SOABI')}
        cache_key=hashlib.sha256(json.dumps(cache_identity,sort_keys=True).encode()).hexdigest()
        cache_base=Path.home()/'na-platform-simulation/R7/T704/dependency-cache'
        cache=cache_base/cache_key;cache.mkdir(parents=True,exist_ok=True)
        (cache/'identity.json').write_bytes((json.dumps(cache_identity,indent=2)+'\n').encode())
        save('dependency-cache-receipt.json',{'path':str(cache),'identity':cache_identity,'cache_key':cache_key,'scope':'pip download cache only; require-hashes installation in a fresh per-job venv'})
        os.environ.update(TMPDIR=str(temporary),PIP_CACHE_DIR=str(cache/'pip-cache'))
        url='https://pypi.org/pypi/pip/25.2/json'
        with urllib.request.urlopen(url,timeout=30) as response:metadata=json.load(response)
        wheel=next(f for f in metadata['urls'] if f['filename'].endswith('py3-none-any.whl') and not f['yanked'])
        with urllib.request.urlopen(wheel['url'],timeout=30) as response:raw=response.read()
        if hashlib.sha256(raw).hexdigest()!=wheel['digests']['sha256']:raise ValueError('PIP_BOOTSTRAP_HASH_MISMATCH')
        bootstrap=OUT/wheel['filename'];bootstrap.write_bytes(raw)
        save('bootstrap-receipt.json',{'version':'25.2','url':wheel['url'],'sha256':wheel['digests']['sha256'],'project_only':True})
        pip_code='import sys,runpy;sys.path.insert(0,'+repr(str(bootstrap))+');runpy.run_module("pip",run_name="__main__")'
        subprocess.run([str(python),'-c',pip_code,'install','--only-binary=:all:','--require-hashes','--report',str(OUT/'pip-install.json'),'-r',str(ROOT/'third_party/enola/requirements.lock')],check=True)
        command=[str(python) if arg=='{python}' else arg for arg in spec['argv']]
        state.update(status='running',actual_argv=command)
        save('worker-receipt.json',state)
        result=subprocess.run(command,cwd=ROOT)
        verify()
        state.update(status='command_completed' if result.returncode==0 else 'command_failed_incomplete',returncode=result.returncode,source_snapshot_stable=True,finished_at_utc=datetime.now(timezone.utc).isoformat())
        save('worker-receipt.json',state)
        return result.returncode
    except Exception as exc:
        state.update(status='incomplete',error={'type':type(exc).__name__,'message':str(exc)})
        save('worker-receipt.json',state)
        raise


if __name__=='__main__':raise SystemExit(main())
