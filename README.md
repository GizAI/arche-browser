# Arche Browser

MCP Server for Browser Automation and Full Local PC Control.

Control a real Chrome browser AND your entire computer from Claude Code or any MCP client.

## Features

- **Full Browser Control**: Navigation, clicks, typing, screenshots, and more
- **Full PC Control**: Shell commands, Python execution, file system, clipboard, processes
- **Real Browser**: Uses your actual Chrome with cookies, extensions, login sessions
- **Remote Access**: Control browser/PC on any machine via SSE transport
- **Token Authentication**: Secure remote access with auto-generated tokens
- **Minimal Design**: Just a few powerful primitives that can do anything

## Design Philosophy

Inspired by Eric Gamma's principles: **Simple, Flexible, Powerful**

Instead of hundreds of specific tools, Arche provides a few powerful primitives:

| Primitive | What it does | What you can achieve |
|-----------|--------------|----------------------|
| `shell()` | Execute any shell command | Volume, reboot, programs, services, ANYTHING |
| `python_exec()` | Execute Python code | Camera, Excel, AI, complex logic, ANYTHING |
| `screen_capture()` | Desktop screenshot | Visual feedback for AI |

With just `shell` and `python_exec`, AI can literally control **EVERYTHING** on your computer.

## Installation

```bash
# From PyPI
pip install arche-browser

# From GitHub
pip install git+https://github.com/GizAI/arche-browser.git

# One-liner (no install)
uvx arche-browser
```

## Usage

### Browser Only (Default)

```bash
arche-browser
```

Claude Code config:
```json
{"mcpServers": {"browser": {"command": "arche-browser"}}}
```

### Full PC Control

```bash
arche-browser --local
```

Claude Code config:
```json
{"mcpServers": {"arche": {"command": "arche-browser", "args": ["--local"]}}}
```

### PC Control Only (No Browser)

```bash
arche-browser --local --no-browser
```

### Remote Access (SSE)

On the machine with Chrome:
```bash
arche-browser --sse --port 8080 --local

# Output:
# [*] Auth: ENABLED
# [*] Token: abc123...
# [*] Connect URL: http://localhost:8080/sse?token=abc123...
```

On Claude Code:
```json
{"mcpServers": {"remote": {"url": "http://YOUR_IP:8080/sse?token=YOUR_TOKEN"}}}
```

## Local Control Tools

### Core Primitives

| Tool | Description |
|------|-------------|
| `shell(command)` | Execute shell command (bash/cmd/powershell) |
| `python_exec(code)` | Execute Python code with full system access |
| `screen_capture(path)` | Capture desktop screenshot |

### Convenience Tools

| Tool | Description |
|------|-------------|
| `file_read(path)` | Read file content |
| `file_write(path, content)` | Write file content |
| `file_list(path, pattern)` | List directory contents |
| `file_delete(path)` | Delete file or directory |
| `file_copy(src, dst)` | Copy file or directory |
| `file_move(src, dst)` | Move/rename file or directory |
| `clipboard_get()` | Get clipboard content |
| `clipboard_set(content)` | Set clipboard content |
| `system_info()` | Get OS, CPU, memory, disk info |
| `process_list()` | List running processes |
| `process_kill(pid/name)` | Kill a process |

### What You Can Do

```python
# Volume control (Windows)
shell("powershell (Get-AudioDevice -Playback).SetMute($false)")

# Take a photo with webcam
python_exec("""
import cv2
cap = cv2.VideoCapture(0)
ret, frame = cap.read()
cv2.imwrite("photo.jpg", frame)
cap.release()
""")

# Create Excel spreadsheet
python_exec("""
import openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws['A1'] = 'Sales Report'
ws['A2'] = 1000
wb.save('report.xlsx')
""")

# System maintenance
shell("cleanmgr /d C:")  # Windows disk cleanup
shell("sudo apt autoremove")  # Linux cleanup

# Reboot computer
shell("shutdown /r /t 60")  # Windows
shell("sudo reboot")  # Linux

# Kill a program
process_kill(name="notepad.exe")
```

## Browser Tools

### Navigation
| Tool | Description |
|------|-------------|
| `goto(url)` | Navigate to URL |
| `get_url()` | Get current URL |
| `get_title()` | Get page title |
| `reload()` | Reload page |
| `go_back()` | Go back in history |
| `go_forward()` | Go forward in history |

### DOM & Input
| Tool | Description |
|------|-------------|
| `get_text(selector)` | Get element text |
| `get_html(selector)` | Get element HTML |
| `click(selector)` | Click element |
| `type_text(selector, text)` | Type into input |
| `select_option(selector, value)` | Select dropdown |
| `check_box(selector, checked)` | Check/uncheck |
| `scroll_to(x, y)` | Scroll page |

### Screenshots & PDF
| Tool | Description |
|------|-------------|
| `screenshot(path)` | Take screenshot |
| `pdf(path)` | Generate PDF |

### Cookies & Storage
| Tool | Description |
|------|-------------|
| `get_cookies()` | Get cookies |
| `set_cookie(name, value)` | Set cookie |
| `storage_get(key)` | Get localStorage |
| `storage_set(key, value)` | Set localStorage |

### JavaScript
| Tool | Description |
|------|-------------|
| `evaluate(script)` | Execute JS |

## CLI Options

```
arche-browser [OPTIONS]

Mode:
  --local          Enable full local PC control
  --no-browser     Disable browser tools (requires --local)

Transport:
  --sse            Run as SSE server for remote access
  --port PORT      SSE server port (default: 8080)

Browser:
  --headless       Run Chrome in headless mode

Authentication:
  --no-auth        Disable token authentication
  --token TOKEN    Use specific auth token
  --show-token     Show current auth token
  --reset-token    Generate new auth token
```

## Architecture

```
arche_browser/
├── __init__.py    # Package exports
├── __main__.py    # CLI entry point
├── chrome.py      # Chrome process management
├── browser.py     # Full CDP browser automation
├── server.py      # MCP server with all tools
├── auth.py        # Token authentication
├── local.py       # Local PC control primitives
└── sites/
    └── chatgpt.py # ChatGPT-specific client
```

## Security

- **Token Authentication**: Remote SSE servers require authentication by default
- **Explicit Opt-in**: Local PC control requires `--local` flag
- **No Sandbox**: Local control has NO restrictions - use responsibly

## Requirements

- Python 3.10+
- Chrome, Chromium, or Edge browser (for browser tools)
- MCP client (Claude Code, etc.)

## License

MIT
