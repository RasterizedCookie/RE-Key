import tkinter as tk
from tkinter import messagebox, simpledialog
import ttkbootstrap as tb
from ttkbootstrap.constants import *
import pystray
from PIL import Image, ImageDraw
import threading
import keyboard
import time
import json
import os
import sys
import subprocess

if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))

CONFIG_FILE = os.path.join(APP_DIR, "config.json")
ERROR_LOG_FILE = os.path.join(APP_DIR, "RE_Key_error.log")

try:
    import winreg
except ImportError:
    winreg = None

REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "RE-Key"

def get_startup_status():
    if not winreg:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except WindowsError:
        return False

def set_startup_status(enable):
    if not winreg:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_WRITE | winreg.KEY_SET_VALUE)
        if enable:
            if getattr(sys, 'frozen', False):
                cmd = f'"{sys.executable}"'
            else:
                script_path = os.path.abspath(sys.argv[0])
                python_exe = sys.executable.replace("python.exe", "pythonw.exe")
                cmd = f'"{python_exe}" "{script_path}"'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Failed to change startup setting: {e}")
        return False


class KeyTracker:
    def __init__(self, key, key_config, callback):
        self.key = key
        self.key_config = key_config
        self.callback = callback
        self.presses = 0
        self.last_press_time = 0
        self.timer = None
        self.is_down = False
        self.down_time = 0
        self.long_press_triggered = False
        self.generation = 0

    def on_event(self, e):
        try:
            is_pressed = keyboard.is_pressed(self.key)
        except ValueError:
            return False

        now = time.time()
        
        has_single = 'single_press' in self.key_config
        has_double = 'double_press' in self.key_config
        has_triple = 'triple_press' in self.key_config
        has_long = 'long_press' in self.key_config

        if is_pressed and not self.is_down:
            self.is_down = True
            self.down_time = now
            self.long_press_triggered = False
            if has_long:
                self.start_long_press_timer()
        elif not is_pressed and self.is_down:
            self.is_down = False
            self.cancel_timer()
            
            if not self.long_press_triggered:
                if has_double or has_triple:
                    if now - self.last_press_time > 0.35:
                        self.presses = 1
                    else:
                        self.presses += 1
                    
                    self.last_press_time = now
                    self.start_multi_press_timer()
                elif has_single:
                    # No double/triple presses configured, fire single press instantly on release!
                    self.presses = 0
                    self.callback(self.key, 'single_press')
                
        # Only block this event if it is part of our tracked hotkey!
        # If is_pressed is stuck True (e.g. dropped UP event), we MUST NOT block unrelated keys.
        components = [k.strip().lower() for k in self.key.split('+')]
        if is_pressed and e.name and e.name.lower() in components:
            return True
        return False

    def start_long_press_timer(self):
        self.cancel_timer()
        self.generation += 1
        current_gen = self.generation
        
        def callback():
            if self.generation == current_gen and self.is_down:
                self.long_press_triggered = True
                self.callback(self.key, 'long_press')
                
        self.timer = threading.Timer(0.4, callback)
        self.timer.start()

    def start_multi_press_timer(self):
        self.cancel_timer()
        self.generation += 1
        current_gen = self.generation
        
        has_single = 'single_press' in self.key_config
        has_double = 'double_press' in self.key_config
        has_triple = 'triple_press' in self.key_config

        def callback():
            if self.generation == current_gen and not self.is_down:
                if self.presses == 1 and has_single:
                    self.callback(self.key, 'single_press')
                elif self.presses == 2 and has_double:
                    self.callback(self.key, 'double_press')
                elif self.presses >= 3 and has_triple:
                    self.callback(self.key, 'triple_press')
                self.presses = 0
                
        self.timer = threading.Timer(0.35, callback) # Reduced from 0.5s to 0.35s for snappier double-press detection
        self.timer.start()

    def cancel_timer(self):
        self.generation += 1
        if self.timer:
            self.timer.cancel()
            self.timer = None

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = APP_DIR
    return os.path.join(base_path, relative_path)

class ReKeyApp:
    def __init__(self):
        self.config = self.load_config()
        self.trackers = {}
        self.is_recording = False
        self.is_sending_macro = False
        self.is_paused = False
        self.record_callback = None
        self.setup_hook()
        
        self.root = tb.Window(themename="darkly")
        self.root.title("RE:Key")
        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)
            
        self.root.geometry("600x540")
        self.root.protocol('WM_DELETE_WINDOW', self.hide_window)
        self.root.resizable(False, False)
        
        self.setup_ui()
        self.refresh_key_list()
        
        # Tray setup in a separate thread
        self.tray_thread = threading.Thread(target=self.setup_tray, daemon=True)
        self.tray_thread.start()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading config: {e}")
        return {}

    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")

    def setup_hook(self):
        try:
            keyboard.unhook_all()
        except:
            pass
        self.trackers.clear()
        for key in self.config.keys():
            self.trackers[key] = KeyTracker(key, self.config.get(key, {}), self.on_action_triggered)
        keyboard.hook(self.global_hook, suppress=True)

    def global_hook(self, e):
        # In the keyboard library, a blocking hook must return True to ALLOW the event,
        # and False to SUPPRESS (block) the event from the OS.
        if self.is_paused:
            return True # Allow everything when paused
            
        if self.is_sending_macro:
            return True # Allow macros to pass through

        if self.is_recording:
            if self.record_callback:
                self.record_callback(e)
            return False # Block all keys from OS during recording

        # Fix keyboard state desync! When we suppress keys by returning False,
        # the keyboard module skips updating its own state, causing is_pressed() 
        # to get stuck forever. We update it manually here first.
        with keyboard._pressed_events_lock:
            if e.event_type == keyboard.KEY_DOWN:
                keyboard._pressed_events[e.scan_code] = e
            elif e.event_type == keyboard.KEY_UP:
                keyboard._pressed_events.pop(e.scan_code, None)

        should_block = False
        for tracker in self.trackers.values():
            if tracker.on_event(e):
                should_block = True
                
        return not should_block

    def on_action_triggered(self, key, action_type):
        action = self.config.get(key, {}).get(action_type)
        if not action:
            return

        action_cmd = action.get('command', '').strip()
        action_mode = action.get('mode', 'Send Keys')

        if not action_cmd:
            return

        print(f"Triggered {action_type} for {key}: {action_mode} -> {action_cmd}")
        
        try:
            if action_mode == 'Send Keys':
                self.is_sending_macro = True
                try:
                    time.sleep(0.05)
                    keyboard.send(action_cmd)
                finally:
                    self.is_sending_macro = False
            elif action_mode == 'Run Program':
                subprocess.Popen(action_cmd, shell=True)
        except Exception as e:
            with open(ERROR_LOG_FILE, "a") as f:
                f.write(f"[{time.ctime()}] Action execution error ({action_type}): {e}\n")
            
    def setup_tray(self):
        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            image = Image.open(icon_path)
        else:
            image = Image.new('RGBA', (64, 64), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse([4, 4, 60, 60], fill=(34, 39, 46, 255))

        menu = pystray.Menu(
            pystray.MenuItem(lambda item: "▶ Resume Tracker" if self.is_paused else "⏸ Pause Tracker", lambda icon, item: self.root.after(0, self.toggle_pause)),
            pystray.MenuItem("Settings", lambda icon, item: self.root.after(0, self.root.deiconify)),
            pystray.MenuItem("Quit", self.quit_app)
        )
        self.tray_icon = pystray.Icon("RE_Key", image, "RE:Key", menu)
        self.tray_icon.run()

    def hide_window(self):
        if getattr(self, 'current_selected_key', None) and self.has_unsaved_changes():
            resp = messagebox.askyesnocancel("Unsaved Changes", f"You have unsaved changes for '{self.current_selected_key}'. Do you want to save them before minimizing to tray?")
            if resp is True:
                self.save_and_apply(silent=True)
            elif resp is None:
                return # Don't hide
        self.root.withdraw()
        
    def quit_app(self, *args):
        def prompt_and_quit():
            if getattr(self, 'current_selected_key', None) and self.has_unsaved_changes():
                resp = messagebox.askyesno("Unsaved Changes", f"You have unsaved changes for '{self.current_selected_key}'. Do you want to save them before quitting?")
                if resp:
                    self.save_and_apply(silent=True)
                    
            if hasattr(self, 'tray_icon') and self.tray_icon:
                self.tray_icon.stop()
            try:
                keyboard.unhook_all()
            except:
                pass
            self.root.destroy()
            os._exit(0)
            
        self.root.after(0, prompt_and_quit)

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.play_pause_btn.config(text="▶ Resume Tracker")
            try: keyboard.unhook_all()
            except: pass
        else:
            self.play_pause_btn.config(text="⏸ Pause Tracker")
            self.setup_hook()
            
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.tray_icon.update_menu()

    def toggle_startup(self):
        enable = self.startup_var.get()
        success = set_startup_status(enable)
        if not success:
            self.startup_var.set(not enable)
            messagebox.showerror("Error", "Failed to update startup setting in Windows Registry.")

    def setup_ui(self):
        main_frame = tb.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Global Toolbar
        toolbar = tb.Frame(main_frame)
        toolbar.pack(fill=tk.X, pady=(0, 15))
        
        self.play_pause_btn = tb.Button(toolbar, text="⏸ Pause Tracker", command=self.toggle_pause, width=16, bootstyle=WARNING)
        self.play_pause_btn.pack(side=tk.LEFT)
        
        tb.Label(toolbar, text=" | ").pack(side=tk.LEFT, padx=5)
        
        tb.Button(toolbar, text="💾 Save Configuration", command=self.save_and_apply, bootstyle=SUCCESS).pack(side=tk.LEFT)
        
        tb.Label(toolbar, text=" | ").pack(side=tk.LEFT, padx=5)
        
        self.startup_var = tk.BooleanVar(value=get_startup_status())
        self.startup_chk = tb.Checkbutton(
            toolbar, 
            text="Start on Startup", 
            variable=self.startup_var, 
            command=self.toggle_startup, 
            bootstyle="round-toggle"
        )
        self.startup_chk.pack(side=tk.LEFT, padx=10)
        
        # Top Panel (Select Key)
        top_frame = tb.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 10))
        
        tb.Label(top_frame, text="Trigger:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.key_combo_var = tk.StringVar()
        self.key_combo = tb.Combobox(top_frame, textvariable=self.key_combo_var, state="readonly", width=30)
        self.key_combo.pack(side=tk.LEFT, padx=5)
        self.key_combo.bind('<<ComboboxSelected>>', self.on_key_select)
        
        tb.Button(top_frame, text="Add Key", command=self.add_key, bootstyle=PRIMARY).pack(side=tk.LEFT, padx=5)
        tb.Button(top_frame, text="Remove Key", command=self.remove_key, bootstyle=DANGER).pack(side=tk.LEFT, padx=5)
        
        # Bottom Panel (Actions for selected key)
        self.right_frame = tb.LabelFrame(main_frame, text="Actions", padx=10, pady=10)
        self.right_frame.pack(fill=tk.BOTH, expand=True)
        
        self.action_vars = {}
        self.create_action_ui(self.right_frame, "Single Press", "single_press")
        self.create_action_ui(self.right_frame, "Double Press", "double_press")
        self.create_action_ui(self.right_frame, "Triple Press", "triple_press")
        self.create_action_ui(self.right_frame, "Long Press", "long_press")

    def create_action_ui(self, parent, label_text, action_key):
        frame = tb.Frame(parent, padding=5)
        frame.pack(fill=tk.X, pady=5)
        
        tb.Label(frame, text=label_text, width=15, font=('', 10, 'bold')).pack(side=tk.TOP, anchor='w')
        
        row = tb.Frame(frame)
        row.pack(fill=tk.X, pady=5)
        
        tb.Label(row, text="Type:").pack(side=tk.LEFT)
        mode_var = tk.StringVar(value="Send Keys")
        mode_cb = tb.Combobox(row, textvariable=mode_var, values=["Send Keys", "Run Command"], state="readonly", width=12)
        mode_cb.pack(side=tk.LEFT, padx=5)
        
        tb.Label(row, text="Action:").pack(side=tk.LEFT)
        cmd_var = tk.StringVar()
        cmd_entry = tb.Entry(row, textvariable=cmd_var)
        cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        def record_cmd():
            capture_win = tb.Toplevel(self.root)
            capture_win.title("Capture Shortcut")
            capture_win.geometry("300x150")
            capture_win.transient(self.root)
            capture_win.grab_set()
            
            lbl = tb.Label(capture_win, text="Press your shortcut (or sequence of keys)...\nClick 'Done' when finished.", font=('', 10), justify=tk.CENTER)
            lbl.pack(expand=True, pady=10)
            
            recorded_chords = []
            
            def handle_capture(hk):
                if hk and hk != 'f24':
                    recorded_chords.append(hk.strip())
                    lbl.config(text=f"Recorded: {', '.join(recorded_chords)}\n\nPress next key or click Done.")
                    
            def finish_recording():
                self.is_recording = False
                self.record_callback = None
                try: capture_win.destroy()
                except: pass
                if recorded_chords:
                    cmd_var.set(', '.join(recorded_chords))

            done_btn = tb.Button(capture_win, text="Done", command=finish_recording, bootstyle=SUCCESS)
            done_btn.pack(pady=10)
                        
            recorded_keys = set()
            recorded_sequence = []
            
            def on_key(e):
                if e.name == 'f24':
                    self.root.after(0, finish_recording)
                    return
                    
                if e.event_type == keyboard.KEY_DOWN:
                    if e.name not in recorded_keys:
                        recorded_keys.add(e.name)
                        recorded_sequence.append(e.name)
                elif e.event_type == keyboard.KEY_UP:
                    if e.name in recorded_keys:
                        recorded_keys.remove(e.name)
                    if not recorded_keys and recorded_sequence:
                        hk = '+'.join(recorded_sequence)
                        recorded_sequence.clear()
                        self.root.after(0, lambda: handle_capture(hk))
                        
            self.record_callback = on_key
            self.is_recording = True

            def on_close():
                keyboard.send('f24')
                
            capture_win.protocol("WM_DELETE_WINDOW", on_close)
            
        record_btn = tb.Button(row, text="Record", width=7, command=record_cmd, bootstyle=INFO)
        record_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        clear_btn = tb.Button(row, text="Clear", width=5, command=lambda: cmd_var.set(''), bootstyle=SECONDARY)
        clear_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        def on_mode_change(*args):
            if mode_var.get() == "Send Keys":
                record_btn.pack(side=tk.LEFT, padx=(0, 5))
                clear_btn.pack(side=tk.LEFT, padx=(0, 5))
            else:
                record_btn.pack_forget()
                clear_btn.pack_forget()
        
        mode_var.trace_add('write', on_mode_change)
        
        self.action_vars[action_key] = {'mode': mode_var, 'cmd': cmd_var}

    def clear_action_ui(self):
        for vars_dict in self.action_vars.values():
            vars_dict['mode'].set('Send Keys')
            vars_dict['cmd'].set('')

    def refresh_key_list(self):
        keys = list(self.config.keys())
        self.key_combo['values'] = keys
        if keys:
            if self.key_combo_var.get() not in keys:
                self.key_combo.current(0)
                self.on_key_select(None)
        else:
            self.key_combo.set('')
            self.clear_action_ui()

    def has_unsaved_changes(self):
        if not getattr(self, 'current_selected_key', None):
            return False
            
        key_config = self.config.get(self.current_selected_key, {})
        for action_key, vars_dict in self.action_vars.items():
            cmd = vars_dict['cmd'].get().strip()
            mode = vars_dict['mode'].get()
            
            saved_action = key_config.get(action_key, {})
            saved_cmd = saved_action.get('command', '')
            saved_mode = saved_action.get('mode', 'Send Keys')
            
            if cmd != saved_cmd or (cmd and mode != saved_mode):
                return True
        return False

    def on_key_select(self, event=None):
        new_key = self.key_combo_var.get()
        if not new_key:
            return
            
        if getattr(self, 'current_selected_key', None) and self.current_selected_key != new_key:
            if self.has_unsaved_changes():
                resp = messagebox.askyesnocancel("Unsaved Changes", f"You have unsaved changes for '{self.current_selected_key}'. Do you want to save them before switching?")
                if resp is True:
                    self.save_and_apply(silent=True)
                elif resp is None:
                    # Cancel switching
                    self.key_combo_var.set(self.current_selected_key)
                    return
        
        self.current_selected_key = new_key
        key_config = self.config.get(new_key, {})
        
        for action_key, vars_dict in self.action_vars.items():
            action_config = key_config.get(action_key, {})
            vars_dict['mode'].set(action_config.get('mode', 'Send Keys'))
            vars_dict['cmd'].set(action_config.get('command', ''))

    def add_key(self):
        capture_win = tb.Toplevel(self.root)
        capture_win.title("Add Key")
        capture_win.geometry("300x120")
        capture_win.transient(self.root)
        capture_win.grab_set()
        
        lbl = tb.Label(capture_win, text="Press the key or key combination now...", font=('', 10))
        lbl.pack(expand=True)

        def handle_capture(hk):
            self.is_recording = False
            self.record_callback = None
            try:
                if capture_win.winfo_exists():
                    capture_win.destroy()
            except:
                pass

            if hk and hk != 'f24':
                key = hk.strip()
                if key not in self.config:
                    self.config[key] = {}
                    self.refresh_key_list()
                    self.key_combo_var.set(key)
                    self.on_key_select(None)
                    self.setup_hook()
                else:
                    messagebox.showwarning("Warning", f"Key '{key}' is already configured.")
                    self.key_combo_var.set(key)
                    self.on_key_select(None)

        recorded_keys = set()
        recorded_sequence = []
        capture_done = False
        
        def on_key(e):
            nonlocal capture_done
            if capture_done: return
            
            if e.name == 'f24':
                capture_done = True
                self.root.after(0, lambda: handle_capture('f24'))
                return
                
            if e.event_type == keyboard.KEY_DOWN:
                if e.name not in recorded_keys:
                    recorded_keys.add(e.name)
                    recorded_sequence.append(e.name)
            elif e.event_type == keyboard.KEY_UP:
                if e.name in recorded_keys:
                    recorded_keys.remove(e.name)
                if not recorded_keys and recorded_sequence:
                    capture_done = True
                    hk = '+'.join(recorded_sequence)
                    self.root.after(0, lambda: handle_capture(hk))
                    
        self.record_callback = on_key
        self.is_recording = True

        def on_close():
            keyboard.send('f24')
            
        capture_win.protocol("WM_DELETE_WINDOW", on_close)

    def remove_key(self):
        key = self.key_combo_var.get()
        if not key:
            return
        
        if messagebox.askyesno("Confirm", f"Are you sure you want to remove '{key}'?"):
            del self.config[key]
            self.current_selected_key = None # Prevent unsaved changes prompt for deleted key
            self.refresh_key_list()
            self.setup_hook() # Apply instantly
            self.save_config()

    def save_and_apply(self, silent=False):
        key = getattr(self, 'current_selected_key', self.key_combo_var.get())
        if not key:
            if not silent: messagebox.showinfo("Info", "Select a key first to save its configuration.")
            return
            
        key_config = {}
        for action_key, vars_dict in self.action_vars.items():
            cmd = vars_dict['cmd'].get().strip()
            if cmd:
                key_config[action_key] = {
                    'mode': vars_dict['mode'].get(),
                    'command': cmd
                }
                
        self.config[key] = key_config
        self.save_config()
        self.setup_hook()
        if not silent: messagebox.showinfo("Success", f"Configuration for '{key}' saved and applied!")

if __name__ == "__main__":
    app = ReKeyApp()
    app.root.mainloop()
