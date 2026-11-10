"""Simple Gemini-powered interview practice assistant (Windows-friendly)."""
import io
import sys
import ctypes
import os
import queue
import threading
import time
import wave
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

import mss
from PIL import Image
from google import genai
from google.genai import types
from pynput import keyboard
import sounddevice as sd

DEFAULT_MODEL = 'gemini-3.5-flash-lite'
FALLBACK_MODEL = 'gemini-3.1-flash-lite'
MODEL_CHOICES = (DEFAULT_MODEL, FALLBACK_MODEL, 'gemini-3.5-flash',
                 'gemini-3.6-flash', 'gemini-3.8-flash')
PROMPT = ('You are a concise interview practice tutor. Answer the question directly in at most '
          '3 short sentences. No introductions or filler. For code questions give only minimal '
          'correct code and a brief explanation if needed. For experience questions give a '
          'sample structure and never invent personal achievements.')

class InterviewAssistant:
    def __init__(self, root):
        self.root = root
        root.title('Interview Assistant')
        screen_width = root.winfo_screenwidth()
        width = min(780, max(480, screen_width - 60))
        root.geometry(f'{width}x310+{max(0, (screen_width-width)//2)}+12')
        root.minsize(440, 220)
        root.attributes('-topmost', True)
        self.events = queue.Queue()
        self.working = False
        self.recording = False
        self.started_at = None
        self.first_token_at = None
        self.stream_started = False
        self.hotkeys = None
        self.api_key = tk.StringVar(value=os.getenv('GEMINI_API_KEY', ''))
        self.model = tk.StringVar(value=DEFAULT_MODEL)
        self.listen_secs = tk.IntVar(value=5)
        self.allow_fallback = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value='Ready • Ctrl+Space: screen • Ctrl+Shift+L: microphone')
        self.capture_exclusion = tk.BooleanVar(value=True)
        self.opacity = tk.DoubleVar(value=0.96)
        self.settings_window = None
        self.drag_start = None
        self.setup_ui()
        self.setup_hotkeys()
        root.after(350, self.apply_capture_exclusion)
        self.root.after(100, self.drain_events)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def setup_ui(self):
        # The answer is intentionally the first and largest element, near the webcam.
        self.root.configure(bg='#172133')
        header = tk.Frame(self.root, bg='#172133', height=34)
        header.pack(fill='x', padx=10, pady=(5, 0))
        header.bind('<ButtonPress-1>', self.begin_drag)
        header.bind('<B1-Motion>', self.drag_overlay)
        title = tk.Label(header, text='●  Interview Assistant', bg='#172133', fg='#e9f1ff', font=('Segoe UI', 10, 'bold'))
        title.pack(side='left')
        title.bind('<ButtonPress-1>', self.begin_drag)
        title.bind('<B1-Motion>', self.drag_overlay)
        ttk.Button(header, text='Settings', command=self.open_settings).pack(side='right', padx=(6, 0))
        ttk.Button(header, text='—', width=3, command=self.minimize_overlay).pack(side='right')
        ttk.Button(header, text='Screen', command=self.analyze_screen).pack(side='right', padx=(0, 5))
        ttk.Button(header, text='Listen', command=self.record_audio).pack(side='right', padx=(0, 5))
        self.answer = scrolledtext.ScrolledText(self.root, height=9, wrap='word',
                                                bg='#0e1726', fg='#f4f8ff', insertbackground='white',
                                                selectbackground='#42669c', relief='flat',
                                                font=('Segoe UI', 14), padx=14, pady=9)
        self.answer.pack(fill='both', expand=True, padx=10, pady=(8, 5))
        self.answer.insert('1.0', 'Answers appear here. Press Ctrl+Space to analyze the screen.')
        self.answer.configure(state='disabled')
        bottom = ttk.Frame(self.root, padding=(10, 0, 10, 4))
        bottom.pack(fill='x')
        self.question = ttk.Entry(bottom)
        self.question.pack(side='left', fill='x', expand=True)
        self.question.bind('<Return>', lambda event: self.ask_typed())
        ttk.Button(bottom, text='Ask', command=self.ask_typed).pack(side='left', padx=(6, 0))
        ttk.Label(self.root, textvariable=self.status, anchor='w').pack(fill='x', padx=10, pady=(0, 5))
        self.root.attributes('-alpha', self.opacity.get())

    def begin_drag(self, event):
        self.drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def drag_overlay(self, event):
        if self.drag_start:
            x0, y0, wx, wy = self.drag_start
            self.root.geometry(f'+{max(0, wx+event.x_root-x0)}+{max(0, wy+event.y_root-y0)}')

    def minimize_overlay(self):
        self.root.iconify()

    def set_opacity(self, value):
        self.root.attributes('-alpha', float(value))

    def open_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.settings_window = window
        window.title('Interview Assistant - Settings')
        window.geometry('530x315')
        window.attributes('-topmost', True)
        body = ttk.Frame(window, padding=16)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Gemini API key').pack(anchor='w')
        self.key_entry = ttk.Entry(body, textvariable=self.api_key, show='•')
        self.key_entry.pack(fill='x', pady=(3, 8))
        ttk.Label(body, text='Model').pack(anchor='w')
        ttk.Combobox(body, textvariable=self.model, values=MODEL_CHOICES).pack(fill='x', pady=(3, 8))
        ttk.Checkbutton(body, text='Try another Flash-Lite model on 503 (brief fallback)',
                        variable=self.allow_fallback).pack(anchor='w')
        audio = ttk.Frame(body)
        audio.pack(fill='x', pady=(5, 2))
        ttk.Label(audio, text='Microphone recording duration (seconds)').pack(side='left')
        ttk.Spinbox(audio, from_=3, to=30, width=5, textvariable=self.listen_secs).pack(side='left', padx=10)
        ttk.Checkbutton(body, text='Request exclusion from screen captures (Windows only)',
                        variable=self.capture_exclusion, command=self.apply_capture_exclusion).pack(anchor='w', pady=(7, 0))
        ttk.Label(body, text='Supported by many capture tools, NOT guaranteed for every app.',
                  foreground='#9a5c22').pack(anchor='w', pady=(0, 5))
        ttk.Label(body, text='Overlay opacity').pack(anchor='w')
        ttk.Scale(body, from_=0.65, to=1.0, variable=self.opacity,
                  command=self.set_opacity).pack(fill='x')
        ttk.Button(body, text='Close settings', command=window.destroy).pack(anchor='e', pady=8)
        window.after(250, lambda: self.apply_window_capture_exclusion(window))

    def apply_window_capture_exclusion(self, window):
        if sys.platform != 'win32' or not window.winfo_exists():
            return False
        try:
            # Only owned top-level windows are valid. Windows 10 2004+ supports 0x11.
            hwnd = ctypes.windll.user32.GetAncestor(window.winfo_id(), 2)  # GA_ROOT
            mode = 0x00000011 if self.capture_exclusion.get() else 0x00000000
            result = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, mode)
            return bool(result)
        except (AttributeError, OSError):
            return False

    def apply_capture_exclusion(self):
        if sys.platform != 'win32':
            self.status.set('Capture exclusion is Windows-only; overlay still works.')
            return
        ok = self.apply_window_capture_exclusion(self.root)
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.apply_window_capture_exclusion(self.settings_window)
        if self.capture_exclusion.get():
            if ok:
                self.status.set('Capture exclusion requested. Verify in the meeting share preview.')
            else:
                self.status.set('Windows did not apply capture exclusion; the overlay may appear in sharing.')
        else:
            self.status.set('Capture exclusion OFF: overlay may appear in sharing.')

    def setup_hotkeys(self):
        try:
            self.hotkeys = keyboard.GlobalHotKeys({
                '<ctrl>+<space>': lambda: self.events.put(('capture', None)),
                '<ctrl>+<shift>+l': lambda: self.events.put(('record', None)),
            })
            self.hotkeys.start()
        except Exception as exc:
            self.status.set(f'Global shortcuts unavailable: {exc}. Use buttons instead.')

    def drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'capture':
                    self.analyze_screen()
                elif kind == 'record':
                    self.record_audio()
                elif kind == 'chunk':
                    if not self.stream_started:
                        self.stream_started = True
                        self.first_token_at = time.monotonic()
                        self.status.set(f'First answer text in {self.first_token_at-self.started_at:.1f}s • streaming...')
                    self.answer.configure(state='normal')
                    self.answer.insert('end', payload)
                    self.answer.see('end')
                    self.answer.configure(state='disabled')
                elif kind == 'result':
                    self.working = False
                    if payload:
                        self.set_answer(payload)
                    elapsed = time.monotonic() - self.started_at if self.started_at else 0
                    first = (f' • first text {self.first_token_at-self.started_at:.1f}s'
                             if self.first_token_at and self.started_at else '')
                    self.status.set(f'Ready • total {elapsed:.1f}s{first} (includes recording/capture).')
                elif kind == 'error':
                    self.working = False
                    self.set_answer('Error: ' + str(payload))
                    self.status.set('Request failed. Check API key, model, network and microphone.')
                elif kind == 'status':
                    self.status.set(str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self.drain_events)

    def set_answer(self, text):
        self.answer.configure(state='normal')
        self.answer.delete('1.0', 'end')
        self.answer.insert('1.0', text)
        self.answer.configure(state='disabled')

    def client_settings(self):
        key = self.api_key.get().strip()
        model = self.model.get().strip()
        if not key:
            messagebox.showwarning('Missing key', 'Enter your Gemini API key first.')
            return None
        if not model:
            messagebox.showwarning('Missing model', 'Enter a Gemini model name.')
            return None
        if self.working:
            self.status.set('A request is in progress.')
            return None
        self.working = True
        self.started_at = time.monotonic()
        self.first_token_at = None
        self.stream_started = False
        self.set_answer('')
        return key, model, self.allow_fallback.get()

    def call_gemini(self, key, model, contents, allow_fallback=True):
        """Low-latency streaming; one primary attempt, then a brief overload fallback."""
        client = None
        try:
            # Disable automatic multi-second retries. Let the fallback handle 503.
            client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(
                    retry_options=types.HttpRetryOptions(attempts=1),
                    timeout=16000,
                ),
            )
            candidates = [model]
            if allow_fallback:
                backup = (FALLBACK_MODEL if model != FALLBACK_MODEL else DEFAULT_MODEL)
                if backup not in candidates:
                    candidates.append(backup)

            for index, candidate in enumerate(candidates):
                saw_text = False
                try:
                    self.events.put(('status', f'Asking {candidate} • streaming...'))
                    level = 'low' if candidate.startswith(('gemini-3.8-', 'gemini-3.7-')) else 'minimal'
                    config = types.GenerateContentConfig(
                        max_output_tokens=240,
                        thinking_config=types.ThinkingConfig(thinking_level=level),
                    )
                    for response in client.models.generate_content_stream(
                            model=candidate, contents=contents, config=config):
                        chunk = response.text or ''
                        if chunk:
                            saw_text = True
                            self.events.put(('chunk', chunk))
                    self.events.put(('result', '' if saw_text else 'No text returned by Gemini.'))
                    return
                except Exception as exc:
                    code = getattr(exc, 'code', None)
                    message = str(exc)
                    overloaded = code == 503 or ('503' in message and 'UNAVAILABLE' in message)
                    if overloaded and not saw_text and index + 1 < len(candidates):
                        self.events.put(('status', f'{candidate} busy • trying {candidates[index + 1]}...'))
                        continue
                    if overloaded:
                        self.events.put(('error', 'Google is busy (503). Try again, or select another model in Settings.'))
                    else:
                        self.events.put(('error', message))
                    return
        except Exception as exc:
            self.events.put(('error', str(exc)))
        finally:
            try:
                if client is not None:
                    client.close()
            except Exception:
                pass

    def analyze_screen(self):
        settings = self.client_settings()
        if not settings:
            return
        key, model, fallback = settings
        self.status.set('Capturing primary screen...')
        # Hide the overlay during local screenshot analysis regardless of capture affinity.
        self.root.withdraw()
        self.root.after(80, lambda: self.finish_capture(key, model, fallback))

    def finish_capture(self, key, model, fallback):
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                grab = sct.grab(monitor)
                image = Image.frombytes('RGB', grab.size, grab.rgb)
            # JPEG and resizing substantially reduce upload bytes and encoding work.
            image.thumbnail((1280, 800), Image.Resampling.BILINEAR)
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=65, optimize=False)
            data = buffer.getvalue()
            self.root.deiconify()
            self.root.lift()
            self.root.after(150, self.apply_capture_exclusion)
            self.status.set('Analyzing compressed screenshot...')
            contents = [PROMPT + '\nRead any visible interview practice question in this screenshot. If none is visible, say so.',
                        types.Part.from_bytes(data=data, mime_type='image/jpeg')]
            threading.Thread(target=self.call_gemini, args=(key, model, contents, fallback), daemon=True).start()
        except Exception as exc:
            self.root.deiconify()
            self.working = False
            self.set_answer('Screen capture failed: ' + str(exc))
            self.status.set('Ready.')

    def record_audio(self):
        settings = self.client_settings()
        if not settings:
            return
        key, model, fallback = settings
        try:
            seconds = max(3, min(30, int(self.listen_secs.get())))
        except (ValueError, tk.TclError):
            seconds = 8
        self.status.set(f'Recording microphone for {seconds} seconds...')
        threading.Thread(target=self.capture_audio, args=(key, model, seconds, fallback), daemon=True).start()

    def capture_audio(self, key, model, seconds, fallback):
        try:
            rate = 16000
            audio = sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype='int16')
            sd.wait()
            with io.BytesIO() as buffer:
                with wave.open(buffer, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(rate)
                    wav.writeframes(audio.tobytes())
                audio_bytes = buffer.getvalue()
            self.events.put(('status', 'Analyzing recorded question with Gemini...'))
            contents = [PROMPT + '\nTranscribe the audible question, then answer it. If there is no intelligible question, say so.',
                        types.Part.from_bytes(data=audio_bytes, mime_type='audio/wav')]
            self.call_gemini(key, model, contents, fallback)
        except Exception as exc:
            self.events.put(('error', str(exc)))

    def ask_typed(self):
        question = self.question.get().strip()
        if not question:
            messagebox.showinfo('Type a question', 'Enter a question first.')
            return
        settings = self.client_settings()
        if not settings:
            return
        key, model, fallback = settings
        self.status.set('Asking Gemini (streaming answer)...')
        threading.Thread(target=self.call_gemini,
                         args=(key, model, PROMPT + '\nQuestion: ' + question, fallback), daemon=True).start()

    def close(self):
        try:
            if self.hotkeys:
                self.hotkeys.stop()
        finally:
            self.root.destroy()

if __name__ == '__main__':
    root = tk.Tk()
    InterviewAssistant(root)
    root.mainloop()
