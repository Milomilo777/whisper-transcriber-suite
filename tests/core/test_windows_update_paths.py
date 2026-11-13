"""Run the real updater against a synthetic, network-free source layout."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

import pytest

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows command interpreter')
@pytest.mark.parametrize('name',['Space Path','Amp&ersand','bang!folder'])
def test_source_updater_uses_the_project_interpreter_in_special_paths(tmp_path,name):
    source=tmp_path/name
    script=source/'platform/windows/update.bat'
    script.parent.mkdir(parents=True)
    shutil.copyfile(ROOT/'platform/windows/update.bat',script)
    (source/'gui.py').write_text('',encoding='utf-8')
    (source/'requirements.txt').write_text('',encoding='utf-8')
    (source/'core').mkdir()
    (source/'core/__init__.py').write_text("__version__='fixture'",encoding='utf-8')
    # -m pip resolves the private module beside the script's repository root.
    # No package installer or network request can run in this fixture.
    (source/'pip.py').write_text("from pathlib import Path\nimport json,sys\n"
        "with Path('pip-calls.jsonl').open('a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')\n",encoding='utf-8')
    venv.EnvBuilder(with_pip=False,clear=False,symlinks=False).create(source/'.venv')
    env=os.environ.copy()
    env.pop('PYTHONPATH',None)
    command=subprocess.list2cmdline([os.environ.get('COMSPEC','cmd.exe')])+f' /d /s /c ""{script}""'
    result=subprocess.run(command,
                          cwd=source,env=env,capture_output=True,timeout=40,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace')
    calls=[json.loads(line) for line in (source/'pip-calls.jsonl').read_text().splitlines()]
    assert len(calls)==2
    assert calls[0]==['install','--upgrade','pip','wheel']
    assert calls[1]==['install','--upgrade','-r',str(source/'requirements.txt')]


def test_uninstaller_preserves_untracked_application_subdirectories():
    text=(ROOT/'installer_embed.iss').read_text(encoding='utf-8')
    section=text.split('[UninstallDelete]',1)[1].split('[InstallDelete]',1)[0]
    recursive=[line for line in section.splitlines() if line.startswith('Type: filesandordirs;')]
    assert recursive==['Type: filesandordirs; Name: "{app}\\__pycache__"']
