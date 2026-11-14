"""Actual dialog contracts for native-confirmed hidden-parent/popup schedules."""
import tkinter as tk
from types import SimpleNamespace
import pytest
from app.widgets import error_dialog
from tests.core.test_error_dialog_grab_lookup import display


def ok_button(display):
 return next(widget for widget in display.widgets if widget.options.get('text')=='OK')


@pytest.mark.parametrize('detail',[None,'diagnostic detail'])
def test_hidden_owner_map_reattaches_recenters_and_focuses_once(display,monkeypatch,detail):
 owner=display.root;visible=[False]
 monkeypatch.setattr(owner,'winfo_viewable',lambda:visible[0])
 error_dialog.show_error(owner,'Background failure','Message',detail)
 error=display.windows[-1]
 assert '<Map>' in owner.bindings
 callback=owner.bindings['<Map>']
 callback(SimpleNamespace(widget=error)) # Child mapping is not owner restoration.
 assert '<Map>' in owner.bindings and error.raised==0
 visible[0]=True
 monkeypatch.setattr(owner,'winfo_rootx',lambda:300)
 monkeypatch.setattr(owner,'winfo_rooty',lambda:200)
 callback(SimpleNamespace(widget=owner))
 assert error.transient_parent is owner and error.geometry_value=='+300+200'
 assert error.raised==1 and display.focus is ok_button(display)
 assert '<Map>' not in owner.bindings and owner.grab_current() is error
 callback(SimpleNamespace(widget=owner))
 assert error.raised==1


@pytest.mark.parametrize('close',['command','destroy'])
def test_closing_unmapped_error_removes_only_its_owner_map_binding(display,monkeypatch,close):
 owner=display.root
 other=lambda event:None
 other_id=owner.bind('<Map>',other,add='+')
 monkeypatch.setattr(owner,'winfo_viewable',lambda:False)
 error_dialog.show_error(owner,'Background failure','Message')
 error=display.windows[-1]
 assert len([pair for pair in owner.binding_tokens.values() if pair[0]=='<Map>'])==2
 if close=='command':error.protocols['WM_DELETE_WINDOW']()
 else:
  callback=error.bindings['<Destroy>'];error.destroy();callback(SimpleNamespace(widget=error))
 assert owner.binding_tokens[other_id]==('<Map>',other)
 assert len([pair for pair in owner.binding_tokens.values() if pair[0]=='<Map>'])==1


def test_actual_tkinter_binding_scripts_and_commands_survive_owned_cleanup(display,monkeypatch):
 owner=display.root
 raw='set unrelated_map_observer 1\n'
 owner.tk.call('bind',str(owner),'<Map>',raw)
 other=lambda event:None
 other_id=owner.bind('<Map>',other,add='+')
 before=owner.tk.call('bind',str(owner),'<Map>')
 monkeypatch.setattr(owner,'winfo_viewable',lambda:False)
 error_dialog.show_error(owner,'Background failure','Message')
 error=display.windows[-1]
 error.protocols['WM_DELETE_WINDOW']()
 assert owner.tk.call('bind',str(owner),'<Map>')==before
 assert owner.registered_commands=={other_id:other}


def test_closing_older_hidden_error_preserves_newer_owner_map_callback(display,monkeypatch):
 owner=display.root;visible=[False]
 monkeypatch.setattr(owner,'winfo_viewable',lambda:visible[0])
 error_dialog.show_error(owner,'Older failure','Message');older=display.windows[-1]
 error_dialog.show_error(owner,'Newer failure','Message');newer=display.windows[-1]
 older.protocols['WM_DELETE_WINDOW']()
 assert '<Map>' in owner.bindings and owner.grab_current() is newer
 visible[0]=True;owner.bindings['<Map>'](SimpleNamespace(widget=owner))
 assert newer.transient_parent is owner and newer.raised==1
 assert owner.grab_current() is newer and '<Map>' not in owner.bindings


def test_unmapped_frame_uses_visible_toplevel_as_error_owner(display):
 owner=display.root
 class Frame(tk.Misc):
  master=owner;tk=owner.tk;children={};_w='.hiddenframe'
  def winfo_toplevel(self):return owner
  def winfo_viewable(self):return False
 frame=Frame()
 error_dialog.show_error(frame,'Frame error','Message')
 error=display.windows[-1]
 assert error.master is owner and error.transient_parent is owner
 assert error.geometry_value=='+100+100' and '<Map>' not in owner.bindings


def test_owner_map_keeps_a_newer_modal_grab_and_focus(display,monkeypatch):
 owner=display.root;visible=[False]
 monkeypatch.setattr(owner,'winfo_viewable',lambda:visible[0])
 error_dialog.show_error(owner,'Background failure','Message')
 error=display.windows[-1];callback=owner.bindings['<Map>']
 newer=display.Top(owner);newer.grab_set()
 newer_focus=object();display.focus=newer_focus;visible[0]=True
 callback(SimpleNamespace(widget=owner))
 assert error.transient_parent is owner and '<Map>' not in owner.bindings
 assert error.raised==0 and display.focus is newer_focus
 assert owner.grab_current() is newer


@pytest.mark.parametrize('operation',['ttk::combobox::Unpost','ttk::releaseGrab'])
def test_popup_mutation_failure_is_logged_after_validation(display,monkeypatch,caplog,operation):
 owner=display.root
 class Combo:
  def __str__(self):return '.combo'
 combo=Combo()
 monkeypatch.setattr(error_dialog.ttk,'Combobox',Combo)
 monkeypatch.setattr(owner,'nametowidget',lambda path:combo)
 def call(*args):
  if args[:2]==('grab','current'):return '.combo.popdown'
  if args[:2]==('winfo','class'):return 'ComboboxPopdown' if args[2]=='.combo.popdown' else 'TCombobox'
  if args[:2]==('winfo','parent'):return '.combo'
  if args[0]==operation:raise tk.TclError('synthetic popup mutation failure')
  return ''
 monkeypatch.setattr(owner.tk,'call',call)
 error_dialog._unpost_combobox_grab(owner)
 assert any(record.exc_info and 'popdown' in record.getMessage().lower() for record in caplog.records)

@pytest.mark.parametrize('rootxy',[(100,100),(-32000,-32000)])
def test_unviewable_parent_does_not_hide_or_misplace_error(display,monkeypatch,rootxy):
 parent=display.root;calls=[]
 monkeypatch.setattr(parent,'winfo_viewable',lambda:False)
 monkeypatch.setattr(parent,'winfo_rootx',lambda:rootxy[0]);monkeypatch.setattr(parent,'winfo_rooty',lambda:rootxy[1])
 monkeypatch.setattr(display.Top,'transient',lambda window,owner:calls.append(owner))
 error_dialog.show_error(parent,'Hidden parent','Message')
 error=display.windows[-1]
 assert calls==[], 'A hidden transient owner also hides the error'
 assert error.geometry_value=='+760+390', 'Unviewable parent coordinates must not position the error'
 assert parent.winfo_rootx()==rootxy[0] and parent.winfo_rooty()==rootxy[1]
 assert parent.grab_current() is error

def test_viewable_secondary_monitor_position_is_unchanged(display,monkeypatch):
 parent=display.root;calls=[]
 monkeypatch.setattr(parent,'winfo_rootx',lambda:-1500)
 monkeypatch.setattr(display.Top,'transient',lambda window,owner:calls.append(owner))
 error_dialog.show_error(parent,'Normal parent','Message')
 assert calls==[parent] and display.windows[-1].geometry_value=='+-1500+100'

@pytest.mark.parametrize('deferred_restore',[False,True])
@pytest.mark.parametrize('variant',['valid','wrong-holder-class','wrong-parent-class','wrong-path','unwrapped-combo'])
def test_only_validated_combobox_popdown_is_unposted_before_new_modal(display,monkeypatch,variant,deferred_restore):
 parent=display.root;host=display.Top(parent);events=[]
 class Combo:
  _w='.combo'
  master=parent
  children={}
  def __str__(self):return self._w
 combo=Combo();combo.tk=parent.tk
 if variant!='unwrapped-combo':parent.children['combo']=combo
 monkeypatch.setattr(error_dialog.ttk,'Combobox',Combo)
 holder='.combo.popdown' if variant!='wrong-path' else '.combo.other'
 parent.tk.holder=holder;saved={'pending':True}
 original_call=parent.tk.call
 def call(*args):
  if args[:2]==('winfo','class'):
   if args[2]==holder:return 'OtherPopup' if variant=='wrong-holder-class' else 'ComboboxPopdown'
   if args[2]=='.combo':return 'TEntry' if variant=='wrong-parent-class' else 'TCombobox'
  if args[:2]==('winfo','parent'):return '.combo'
  if args[0]=='ttk::combobox::Unpost':
   assert args[1]=='.combo';events.append('unpost')
   parent.tk.holder='' if deferred_restore else host._w
   if not deferred_restore:saved['pending']=False
   return ''
  if args[0]=='ttk::releaseGrab':
   assert args[1]==holder;events.append('release')
   if saved['pending']:parent.tk.holder=host._w;saved['pending']=False
   return ''
  return original_call(*args)
 monkeypatch.setattr(parent.tk,'call',call)
 original_init=display.Top.__init__
 def init(window,master=None):events.append('create');original_init(window,master)
 monkeypatch.setattr(display.Top,'__init__',init)
 error_dialog.show_error(parent,'Popup overlap','Message')
 error=display.windows[-1]
 if variant=='valid':
  assert events[0]=='unpost' and events[-1]=='create'
  assert getattr(error,error_dialog._PREVIOUS_GRAB_ATTR) is host
  # A later Unmap repeats releaseGrab/RestoreGrab; its saved slot must be gone.
  if saved['pending']:parent.tk.holder=host._w
  assert parent.grab_current() is error
  error.protocols['WM_DELETE_WINDOW']()
  assert parent.grab_current() is host
 else:
  assert events==['create'], 'Unknown/unvalidated raw grab must not be unposted'
  assert getattr(error,error_dialog._PREVIOUS_GRAB_ATTR) is None
