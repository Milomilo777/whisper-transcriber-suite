"""Hardware review regressions: native liveness and safe persisted CPU choices."""
import ctypes
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from core import hardware as hw
from app.widgets import hardware_wizard as ui

@pytest.mark.parametrize('config',[{'device':'auto','compute_type':'float16'},{'device':'auto','compute_type':'int8_float16'},{'device':'cpu','compute_type':'float16'}])
def test_cpu_route_never_inherits_gpu_only_precision(monkeypatch,config):
 monkeypatch.setattr(hw,'device_choice_from_hardware_file',lambda:None)
 monkeypatch.setattr(hw,'cuda_status',lambda:hw.CudaStatus(False,False))
 assert hw.detect_device_for(config)==('cpu','int8')

@pytest.mark.parametrize('compute_type',['int8','int8_float32','float32','auto','default'])
def test_cpu_route_preserves_portable_precision(monkeypatch,compute_type):
 assert hw.detect_device_for({'device':'cpu','compute_type':compute_type})==('cpu',compute_type)

@pytest.mark.parametrize('status',[None,SimpleNamespace(gpu_present=False,inconclusive=True)])
def test_unpicked_cpu_after_unknown_probe_is_not_persisted(monkeypatch,status):
 saved=[];closed=[]
 monkeypatch.setattr(hw,'save_hardware_choice',lambda tier:saved.append(tier))
 wizard=SimpleNamespace(_selected_idx=0,_tiers=[hw.Tier('cpu_int8','CPU','cpu','int8')],_cuda_status=status,_user_picked=False,app=None,_on_close=lambda:closed.append(True))
 ui.HardwareWizard._save_and_close(wizard)
 assert saved==[] and closed==[True]

def test_explicit_cpu_after_unknown_probe_is_kept(monkeypatch):
 saved=[]
 monkeypatch.setattr(hw,'save_hardware_choice',lambda tier:saved.append(tier))
 wizard=SimpleNamespace(_selected_idx=0,_tiers=[hw.Tier('cpu_int8','CPU','cpu','int8')],_cuda_status=None,_user_picked=True,app=None,_on_close=lambda:None)
 ui.HardwareWizard._save_and_close(wizard)
 assert len(saved)==1

def test_status_exception_stays_inconclusive(monkeypatch):
 def explode():raise RuntimeError('synthetic diagnostic failure')
 monkeypatch.setattr(hw,'_cuda_status',explode)
 assert getattr(hw.cuda_status(),'inconclusive',False) is True

def test_wizard_native_probe_is_not_executed_in_parent(monkeypatch):
 status=hw.CudaStatus(False,False)
 monkeypatch.setattr(hw,'probe_hardware_snapshot',lambda:([hw.Tier('cpu_int8','CPU','cpu','int8')],status),raising=False)
 def native_block():
  if sys.platform=='win32':ctypes.PyDLL('kernel32').Sleep(1000)
  else:ctypes.PyDLL(None).sleep(1)
  return status
 monkeypatch.setattr(hw,'cuda_status',native_block)
 monkeypatch.setattr(hw,'probe_tiers',lambda *_:[])
 wizard=SimpleNamespace(_probe_lock=threading.Lock(),_probe_seq=1,_probe_result=None)
 started=time.monotonic();ui.HardwareWizard._reprobe_worker(wizard,1)
 assert time.monotonic()-started<0.5,'A parent GIL-holding native probe bypassed the child boundary'
 assert wizard._probe_result[2] is status


def test_disposable_child_bounds_native_gil_hold(tmp_path):
 import subprocess
 from core import hardware_probe as probe
 code=("import ctypes;ctypes.PyDLL('kernel32').Sleep(3000)" if sys.platform=='win32' else "import ctypes;ctypes.PyDLL(None).sleep(3)")
 started=time.monotonic()
 with pytest.raises(subprocess.TimeoutExpired):
  probe._run_command([sys.executable,'-c',code],tmp_path/'result.json',0.05)
 assert time.monotonic()-started<1.5

def test_child_failure_is_not_a_cpu_verdict(tmp_path):
 from core import hardware_probe as probe
 with pytest.raises(RuntimeError):probe._run_command([sys.executable,'-c','raise SystemExit(3)'],tmp_path/'result.json',2)

def test_missing_child_result_is_not_a_cpu_verdict(tmp_path):
 from core import hardware_probe as probe
 with pytest.raises(FileNotFoundError):probe._run_command([sys.executable,'-c','pass'],tmp_path/'result.json',2)

def test_isolated_timeout_is_inconclusive_and_cpu_opt_in(monkeypatch):
 from core import hardware_probe as probe
 def fail(*args,**kwargs):raise TimeoutError('synthetic stall')
 monkeypatch.setattr(probe,'query',fail)
 tiers,status=hw.probe_hardware_snapshot()
 assert [tier.device for tier in tiers]==['cpu'] and status.inconclusive
 assert hw.isolated_cuda_status().inconclusive

def test_saved_cpu_precision_is_normalized_before_loading(monkeypatch):
 monkeypatch.setattr(hw,'device_choice_from_hardware_file',lambda:('cpu','float16'))
 assert hw.detect_device_for({'device':'auto'})==('cpu','int8')


def test_failed_child_kill_has_no_implicit_unbounded_wait(monkeypatch,tmp_path):
 import subprocess
 from core import hardware_probe as probe
 from core import _proc
 class Child:
  pid=123
  def __enter__(self):return self
  def __exit__(self,*args):raise AssertionError('Popen context would wait without a deadline')
  def wait(self,timeout=None):
   assert timeout is not None
   raise subprocess.TimeoutExpired('synthetic',timeout)
  def poll(self):return None
 child=Child()
 monkeypatch.setattr(probe,'_UNREAPED_PROCESS',None,raising=False)
 monkeypatch.setattr(probe.subprocess,'Popen',lambda *args,**kw:child)
 monkeypatch.setattr(_proc,'kill_process_tree',lambda *args,**kw:None)
 with pytest.raises(subprocess.TimeoutExpired):probe._run_command(['synthetic'],tmp_path/'result',0.01)
 assert probe._UNREAPED_PROCESS is child
 with pytest.raises(RuntimeError,match='finishing'):probe.query('cuda')
