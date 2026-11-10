# Interview Assistant — Top Overlay Edition (Windows 11)

A compact, always-on-top, top-center Gemini interview **practice** assistant with screenshot analysis, optional microphone input, typed questions, and streaming answers.

## Start

1. Extract the ZIP.
2. Open `interview_assistant` and double-click `start_windows.bat`.
3. Open **Settings**, paste your Gemini API key from https://aistudio.google.com/apikey, and choose a model. Default: `gemini-3.8-flash`.
4. Type a question and press **Ask**, or use the buttons/hotkeys.

If needed, in PowerShell run `py -3 -m pip install -r requirements.txt` followed by `py -3 app.py`.

## Overlay

- The panel opens **top-center**, close to a typical laptop camera. The **answer textbox** takes priority, with large text.
- Drag the dark title bar to move it. Resize using normal window borders.
- **Settings** opens a separate window for API key, model, audio duration, opacity and capture exclusion.
- **Screen** or `Ctrl+Space` analyzes your primary display (briefly hides overlay during capture).
- **Listen** or `Ctrl+Shift+L` records from the default microphone for the configured seconds. Audio is off unless triggered.
- The answer is streamed, and Gemini 3.6 Flash is used as backup after a 503 when enabled.

## Capture-exclusion setting: important limitations

Windows 10 2004+ offers `SetWindowDisplayAffinity(..., WDA_EXCLUDEFROMCAPTURE)` to request exclusion of a window from supported screen capture APIs. The app attempts to apply it to both the overlay and settings window. **This is not guaranteed to work with every screen-sharing or recording application**, external camera, hardware capture, remote software, or display mode. The on-screen status reports whether Windows accepted the call, not whether your conferencing app respects it. **Test using your meeting platform's own share preview or a second device before relying on it.** If exclusion fails, assume the window is visible. You can disable this preference in Settings.

Reference: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity

## Privacy and responsible use

This is for interview preparation and situations where AI use and recording are allowed. Obtain permission before recording people or using assistance during evaluated interviews. Screen captures and audio are transmitted to Google's Gemini API; avoid exposing sensitive material. API key remains in memory for the current session.

## Testing notes

Python syntax has been validated. Live API behavior and Windows capture-exclusion behavior require testing on a Windows PC with a valid Gemini key and the actual sharing software. A 503 from the Gemini API means the model is temporarily overloaded.
