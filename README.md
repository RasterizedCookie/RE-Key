# RE:Key

Give your keyboard superpowers. Bind custom actions to double-taps and triple-taps on *any* key, without breaking your normal typing.

RE:Key sits in your system tray and listens for your custom multi-press triggers to launch apps, run scripts, or fire shortcuts.

---

## ✨ Features

- **Double & Triple Tap Triggers**: Map different actions to double or triple presses.
- **Doesn't Break Typing**: Normal single key presses go through instantly. No lag, no weird interruptions.
- **Two Action Types**:
  - `Send Keys`: Trigger custom hotkeys or media controls (like `ctrl+c`, `volume_up`).
  - `Run Command`: Run shell commands or launch apps in the background.
- **Sleek Look**: Modern dark-mode UI built with `ttkbootstrap`.
- **System Tray Mode**: Stays out of your way. Pause or resume tracking directly from the tray icon.
- **Config Auto-saves**: Your bindings save automatically to `config.json`.

---

## 🚀 Getting Started

If you just want to use the app, grab the latest standalone `.exe` from the [Releases](#) tab (no Python setup needed).

### Running from Source

1. Clone this repo:
   ```bash
   git clone https://github.com/yourusername/RE-Key.git
   cd RE-Key
   ```

2. Spin up a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run it:
   ```bash
   python rekey.py
   ```

---

## 🛠️ Build it Yourself

To package the app into a single `.exe` file using PyInstaller:

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile rekey.py --name RE-Key --icon icon.ico --add-data "icon.ico;."
```
Your compiled app will be ready in the `dist/` folder.

---

## 🎮 How to Use

1. Launch RE:Key.
2. In the **Trigger** dropdown, select a key (e.g., `f2`, `caps lock`), or click **"Setup Configured Key"** and just press the key you want.
3. Choose what you want **Double Press** and **Triple Press** to do.
4. Set the mode (`Send Keys` or `Run Command`) and enter your target (like `notepad.exe` or `shift+win+s`).
5. Hit the green **Save & Apply** button.
6. Close the window to send it to the system tray. It'll keep listening in the background.

---

## ⚠️ Heads Up

- **Antivirus Flags**: Because the app hooks into your keyboard system-wide to catch multi-presses, some antivirus software might flag it as a keylogger. This is a common false positive with Python keyboard hooking libraries.
- **Admin Rights**: Some elevated windows (like Task Manager or Command Prompt) won't accept simulated keys unless RE:Key is run as Administrator.

---

## 🤝 Want to contribute?

Feel free to open issues or pull requests!

## 📝 License

MIT License. See `LICENSE` for details.
