# ggContext

**English** · [Türkçe](README.tr.md)

<p align="center"><img src="ggcontext.png" alt="ggContext icon" width="96"></p>

A local Windows app that opens Claude, ChatGPT, Gemini and other AI sites **side by side in one window, in separate tabs**, and
**carries the context (summary, decisions, answers, files) between them in a few clicks**. It was built for working with free accounts:
when one chat hits its quota, you continue the work in another one without losing the topic and while spending fewer tokens.

> **Important:** ggContext does not send messages for you, does not switch between accounts on its own, and does not store passwords.
> You log in to the sites yourself; the app only automates the copy-and-paste work. Sending the message (Enter) is always up to you.

## Features

- **Many tabs, one window:** Claude, ChatGPT, Gemini (and any other site you add) open as real browser tabs. Every tab has its own login session.
- **Topics:** the goal, summary, decisions, open items, answers and files of a project are kept together under one "topic".
- **Context pack:** the summary, decisions, latest answers and files of a topic are trimmed to a token budget, combined into a single block and pasted into the message box of the open chat.
- **Context extraction:** the text of the open chat is read and summarized by another AI (e.g. Gemini); the reply is imported into the topic automatically.
- **Add files to a chat:** paste files you picked from the topic into the open chat at any moment, as text or as files; many files are packed into zip parts of at most 30 MB.
- **Ask another tab:** send selected text to another tab with ready-made prompts from the right-click menu.
- **Translation box:** opens the selected text in Google Translate in a small box.
- **Dark and light burgundy themes**, draggable and renamable tabs, taskbar and notification-area icon, and Windows Search integration.

## Requirements

| What | Version | Notes |
|---|---|---|
| Operating system | Windows 10 / 11 (64-bit) | The title bar colour is fully applied on Windows 11 |
| Python | 3.10 or newer (recommended: 3.12) | The core uses only the standard library |
| PySide6 | 6.8 or newer | Qt UI and the embedded browser (QtWebEngine), see `requirements.txt` |
| PyInstaller | 6.0 or newer | Only needed to build the `.exe`, see `requirements-build.txt` |
| Internet | Required | To install packages and to reach the AI sites |

PySide6 is a large package (hundreds of MB). Because the embedded browser is Chromium based, the resulting `.exe` folder is large as well.

## Installation

### A) As an `.exe` (recommended)

1. Download or clone the project: `git clone <repository-url>`
2. Double-click **`build.bat`**.
   It finds Python, runs the tests, installs PySide6 and PyInstaller into `.venv` if needed, and then builds the app.
3. When it finishes you get **`dist\ggContext\ggContext.exe`**. When moving it elsewhere, move the **whole** `dist\ggContext` folder.

On first launch the app leaves a shortcut in the Start menu, so you can press the Windows key and type **ggContext** to find it.

### B) Run with Python

```
pip install -r requirements.txt
python main.py
```

### Building the `.exe` by hand

```
pip install -r requirements-build.txt
pyinstaller --noconfirm --clean --noconsole --onedir --icon ggcontext.ico --name ggContext main.py
```

### Tests

```
python -m unittest test_core
```

## Where is my data?

Your topics, saved answers and settings live under `%APPDATA%\ggContext\` (`baglam.db`). The login sessions of the tabs are in the `profiles\` folder next to it.
If you share the application folder with a friend, this data does **not** go with it. A folder from an older version named `BaglamKoprusu`
is moved to `ggContext` automatically on first launch.

> The `profiles\` folder stores login cookies unencrypted. Do not share it with anyone and do not upload it to GitHub.

## Everyday use

1. Pick a **topic** on the left or create a **new topic**. Claude, ChatGPT and Gemini tabs are ready on first launch; add other sites with **Add account / tab**.
2. Chat in a tab. When you copy a reply with the site's own **Copy** button, the app saves it to the topic as that tab's answer automatically.
3. Before moving to another tab, press **Extract context** in the source tab. The app reads the chat text and pastes it, with a summary request, into the tab selected in the right panel under
   **Summary > Tab to extract context** (Gemini by default). You press Enter; when the reply arrives you press **Copy**.
   The app recognizes that the reply is a context summary and offers to import it into the topic.
4. In the other tab, click the message box once and press **Paste context**. If you like, type your question into the **Request** field of the **Pack** tab; the context and the question go in one go.
5. If you added files to the topic, **Add files…** pastes the ones you pick into the open chat at any time.

### How context extraction works

- **Extract context (button on the tab):** the text of the open chat is read from the page and pasted into the selected extraction tab. Because the text goes to another service, you are asked to confirm first (this can be turned off in the right panel).
  If the selected tab is the source itself, the request is made inside the same chat.
- **Extract context in this chat (⋯ menu):** the chat's own AI, which already knows the conversation, writes the summary.
- A reply is recognized if it contains at least three of the headings `HEDEF:`, `ÖZET:`, `KARARLAR:`, `AÇIK İŞLER:` (goal, summary, decisions, open items).
- The text that is read is capped at roughly 80 thousand characters; the middle of anything longer is trimmed. Old messages that are not loaded on the page cannot be read.

### What does the pack contain?

As the budget shrinks, it is trimmed starting from the lowest layer:

1. Title, goal, summary
2. Decisions and open items (always kept)
3. Latest conversations (+ up to 3 pinned older answers)
4. Files (most recently changed first)

Raw records are never deleted from the database; a pack is only a view. **Delta mode** sends only what changed while you continue the same chat.
Token counts are estimates (about 3.5 characters = 1 token).

### Adding files to a chat

You can add the files you tick from the topic to the open chat in two ways:

- **Paste as text:** the content lands in the message box and password-like values are masked.
- **Attach as files:** for PDFs, images and Office files. Several files are packed into zip parts of at most 30 MB (optional); a single file over 30 MB gets its own zip and a warning.

In file mode, the files are put on the clipboard as files and pasted into the page. Some sites may not accept this: click the message box and press `Ctrl+V`, or drag the files from the prepared folder.
Masking cannot be applied to files attached this way.

### Asking another tab, and translation

- Select text on a page and right-click: **Ask another tab > (tab) > (template)**. Built-in templates: ask as is, research on the web, critique, summarize, translate to Turkish. Edit them with the **Prompt templates** button on the left (a `# Name` line followed by the prompt; `{metin}` is where the selected text goes).
- **Translate (Google Translate):** opens the selected text in translate.google.com in a small box and lets Google detect the source language. The target is chosen automatically (Turkish text to English, everything else to Turkish).
- **Dropping files or text onto a tab name** adds them to that tab.

## Privacy and security

- Files such as `.env`, `.pem`, `.key`, `id_rsa` and `credentials.json` never go into a pack.
- Values that look like API keys or passwords (`sk-…`, `password = …`, `Bearer …`) are masked. This is best effort; look at the preview in the Pack tab before sending.
- Emails and passwords are not stored by the app; the session stays in a local folder as cookies, like in a browser.
- Actions such as translation and "ask another tab" send the text you selected to the site in question, and only when you trigger them.

## Known limitations

- Sites can change their pages; features that depend on the page structure, such as **Select last reply**, may need updating when that happens.
- Some sites (especially sign-in with Google) block embedded browsers; try signing in with email and a code instead.
- The dark theme for the sites inside tabs is applied when the app starts; restart the app after changing the theme.
- The project is independent and has no official connection to Anthropic, OpenAI or Google.
- The prompts and headings used for context extraction (`HEDEF`, `ÖZET`, `KARARLAR`, `AÇIK İŞLER`) are in Turkish, and the app interface is in Turkish.

## File structure

| File | Purpose |
|---|---|
| `main.py` | Launcher |
| `baglam_core.py` | Database, pack building, token budget, file/zip preparation, tab and chat records (standard library only) |
| `baglam_ui.py` | PySide6 UI: embedded web tabs and the context panel |
| `baglam_theme.py` | Dark/light burgundy theme and the Windows title bar colour |
| `baglam_icon.py` | App icon embedded in code (burgundy "G" on black) |
| `baglam_shortcut.py` | Start menu shortcut (so the app shows up in Windows Search) |
| `ggcontext.ico`, `ggcontext.png` | The `.exe` icon and the README image |
| `test_core.py` | Core tests |
| `build.bat` | One-click `.exe` build |

## Shortcuts and what is what

### Keyboard shortcuts

| Shortcut | What it does |
|---|---|
| `Ctrl+1` | Switch to the tab on the left (wraps around at the start) |
| `Ctrl+2` | Switch to the tab on the right (wraps around at the end) |
| `Ctrl+B` | Show/hide the context panel on the right |
| `Ctrl+Shift+B` | Show/hide the topic panel on the left |
| `Ctrl+Shift+C` | Copy the context pack to the clipboard |
| `Ctrl+Shift+S` | Add the text on the clipboard to the topic as an answer |
| `Ctrl+Shift+F` | Add the files you picked to the open chat |
| `Ctrl+Shift+L` | Select the last AI message in the open chat |
| `Ctrl+Shift+T` | Open the selected text in the Google Translate box |

### Buttons on a tab

| Button | Purpose |
|---|---|
| `←` `→` `↻` `⌂` | Back, forward, reload, go to the site's home address (⌂) |
| Address bar | The tab's address; press Enter to go |
| **Extract context** | Reads the open chat and pastes it with a summary request into the tab selected in the right panel |
| **Paste context** | Pastes the topic's context pack into this tab's message box |
| **Add files…** | Adds the files you pick to this chat as text or as files/zip |
| **Select last reply** | Selects the last AI message in the chat |
| `⋯` menu | Extract context in this chat, save the selection as an answer, zoom, force dark page, rename, edit name/address, clear session, remove tab |

### Right-click menus

| Where | Options |
|---|---|
| On a page (with text selected) | **Ask another tab**, **Translate (Google Translate)**, **Save selection as an answer** |
| On a page (always) | **ggContext** submenu: paste context, add files, extract context, select last reply |
| On a tab name | Rename, edit name/address, remove tab (double-click also renames) |

### Right panel tabs

| Tab | Contents |
|---|---|
| **Summary** | Choice of the extraction tab, goal, summary, decisions, open items |
| **Answers** | Saved answers (pin, delete) |
| **Files** | Files/folders added to the topic, "add my chosen files to the open chat", zip option, upload folder |
| **Chats** | The last 10 chats of the topic; click to open one in its tab |
| **Pack** | Preview of the context pack, layers, delta mode, the **Request** field |

### Status bar and icons

| Item | Purpose |
|---|---|
| `◧` (bottom right) | Hide/show the topic panel on the left |
| `▥` (bottom right) | Show/hide the context panel on the right |
| Taskbar icon | The running app; right-click > "Pin to taskbar" to keep it there |
| Notification-area icon | Click to hide/show the window; the menu has **Minimize to tray on close**, **Add to Windows Search / refresh**, **Quit** |
| Dragging | Drag the tabs at the top to reorder them; the order is saved |

## Code style

The code follows my own coding-style guide, adapted to Python: public functions and methods are PascalCase; local variables, parameters and fields are camelCase;
boolean flags end in `...Flag`; `gg` is used for temporaries; single-statement conditions and methods are written on one line; comments are in Turkish and start with a lowercase letter.
Methods that Qt calls by name (such as `closeEvent` and `eventFilter`) are left unchanged.
