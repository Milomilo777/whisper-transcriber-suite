"""Pure guards shared by the QA-only native probe and headless tests."""
import hashlib,json,os,subprocess,tempfile
import unicodedata
from pathlib import Path
PIN='3adf5845e3d28d131dcb3cb78572c12de5fe5cf4'
class GuardError(RuntimeError):pass

def verify_source(source,manifest):
 source=Path(source)
 if manifest.get('commit')!=PIN:raise GuardError('Manifest commit differs from reviewed PIN')
 expected=manifest['files']
 actual={str(p.relative_to(source)).replace('\\','/') for part in ('app','core') for p in (source/part).rglob('*.py')}
 if actual!=set(expected):raise GuardError('Project Python source closure differs')
 for name,value in expected.items():
  raw=(source/name).read_bytes()
  if hashlib.sha256(raw.replace(bytes((13,10)),bytes((10,)))).hexdigest()!=value:raise GuardError('Project source bytes differ: '+name)
 if (source/'.git').exists():
  head=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
  if head!=PIN:raise GuardError('Checkout HEAD differs from reviewed PIN')
 return {'commit':PIN,'verified_project_python_files':len(expected),'content_normalization':'CRLF to LF','archive_friendly':True}

class Receipt:
 def __init__(self,path):
  self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
  self.data={'pin':PIN,'status':'STARTED_NATIVE_NOT_COMPLETE','rows':[],'errors':[]}
  with self.path.open('x',encoding='utf-8') as f:json.dump(self.data,f);f.flush();os.fsync(f.fileno())
 def checkpoint(self):
  fd,name=tempfile.mkstemp(prefix=self.path.name+'.',suffix='.tmp',dir=self.path.parent)
  with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(self.data,f,indent=2);f.flush();os.fsync(f.fileno())
  os.replace(name,self.path)
 def error(self,case,error):
  self.data['errors'].append({'case':case,'status':'OPEN_FAULT','error_type':type(error).__name__});self.checkpoint()

def guarded_chord(api,vk):
 # Cleanup is key-UP only for keys proved initially up and attempted by this
 # probe. It must run even if focus is lost after submission; no new key-down
 # may be issued to an unowned foreground window.
 keys=(0x11,0xA5,vk)
 if not api.owns():raise GuardError('Foreground/PID/native+Tk focus is not owned')
 if any(api.down(key) for key in keys):raise GuardError('A chord key is already held; no input admitted')
 primary=None;attempted=False
 try:
  if not api.owns():raise GuardError('Foreground ownership changed before input')
  try:
   attempted=True
   sent=api.send([(0x11,0),(0xA5,1),(vk,0),(vk,2),(0xA5,3),(0x11,2)])
   if sent!=6:raise GuardError('Partial native input; abort remaining cases')
  except Exception as e:primary=e
 finally:
  if attempted:
   released=api.send([(vk,2),(0xA5,3),(0x11,2)])
   if released!=3:raise GuardError('Probe-owned key release incomplete; stop')
 if primary is not None:raise primary
 if not api.owns():raise GuardError('Foreground changed during input; remaining cases aborted')
 return {'sent_events':6,'cleanup_keyups':3}



def ownership_allowed(proof):
    fields=('foreground_hwnd','expected_top_hwnd','foreground_pid','expected_pid',
            'native_focus_hwnd','expected_widget_hwnd','native_focus_pid','native_focus_root_hwnd')
    if any(type(proof.get(k)) is not int or proof[k]<=0 for k in fields):
        return False
    return (proof['foreground_hwnd']==proof['expected_top_hwnd']
            and proof['foreground_pid']==proof['expected_pid']
            and proof['native_focus_pid']==proof['expected_pid']
            and proof['native_focus_root_hwnd']==proof['expected_top_hwnd']
            and proof.get('tk_focus_matches') is True)



def is_altgr_text(value):
    # E1 maps AltGr+C to U+202F. Unicode space separators are real text,
    # unlike control characters, format characters or unpaired surrogates.
    return bool(value) and all(ch.isprintable() or unicodedata.category(ch) == 'Zs' for ch in value)


def select_loaded_layout(api):
    current=api.current();loaded=list(api.loaded())
    if len(loaded)>32 or any(type(hkl) is not int or hkl<=0 for hkl in loaded):
        raise GuardError('Loaded-layout enumeration is invalid or over bound')
    if type(current) is not int or current<=0:
        raise GuardError('Current fixture-thread layout is unknown')
    considered=list(dict.fromkeys([current]+loaded))
    if len(considered)>32:raise GuardError('Current plus loaded layouts exceeds finite bound')
    probes=[];selected=None
    for hkl in considered:
        rows=[]
        for vk in (65,67,88,86):
            plain=api.translate(hkl,vk,False);alt=api.translate(hkl,vk,True)
            eligible=is_altgr_text(alt) and alt!=plain
            rows.append({'vk':vk,'plain':plain,'altgr':alt,'eligible':eligible})
        probes.append({'hkl':hex(hkl),'keys':rows})
        if selected is None and any(row['eligible'] for row in rows):selected=hkl
    eligible_keys=next(([row['vk'] for row in probe['keys'] if row['eligible']] for probe in probes if selected is not None and probe['hkl']==hex(selected)),[])
    return {'current':current,'loaded':loaded,'considered':considered,'selected':selected,'eligible_keys':eligible_keys,'probes':probes}

from contextlib import contextmanager
@contextmanager
def temporary_layout(api,target):
    original=api.current();loaded=list(api.loaded())
    if type(original) is not int or original<=0 or type(target) is not int or target<=0:
        raise GuardError('Original/target layout identity is unknown')
    if len(loaded)>32 or any(type(hkl) is not int or hkl<=0 for hkl in loaded):
        raise GuardError('Loaded-layout identity is invalid')
    if not api.owns_thread():raise GuardError('Layout activation is outside the owned fixture thread')
    if target not in loaded and target!=original:raise GuardError('Layout is not already loaded')
    state={'original':hex(original),'selected':hex(target),'activation_flags':0,'restored':False}
    attempted=False
    try:
        if target!=original:
            attempted=True
            previous=api.activate(target,0)
            if previous!=original or api.current()!=target:raise GuardError('Thread-local layout activation failed')
        yield state
    finally:
        if not api.owns_thread():raise GuardError('Owned fixture thread changed before layout restoration')
        if attempted or api.current()!=original:
            if not api.activate(original,0):raise GuardError('Original thread layout could not be restored')
        if api.current()!=original:raise GuardError('Original thread layout restoration is unverified')
        state['restored']=True
