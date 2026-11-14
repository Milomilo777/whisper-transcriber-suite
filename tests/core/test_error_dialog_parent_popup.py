"""Actual dialog contracts for native-confirmed hidden-parent/popup schedules."""
import tkinter as tk
import pytest
from app.widgets import error_dialog
from tests.core.test_error_dialog_grab_lookup import display

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
