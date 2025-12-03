# Arche Browser

MCP Server for Browser Automation via Chrome DevTools Protocol.

Control a real Chrome browser from Claude Code or any MCP client - locally or remotely.

## Quick Start

```bash
# Install
pip install arche-browser

# Or install from source
pip install git+https://github.com/GizAI/arche-browser.git

# Or one-liner (no install needed)
python -c "$(curl -fsSL https://raw.githubusercontent.com/GizAI/arche-browser/main/arche_browser.py)"
```

## Usage

### Local MCP Server (stdio)

Add to your Claude Code MCP settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "browser": {
      "command": "arche-browser"
    }
  }
}
```

### Remote MCP Server (SSE)

On your machine with Chrome:

```bash
arche-browser --sse --port 8080
```

On Claude Code (remote machine), add to MCP settings:

```json
{
  "mcpServers": {
    "browser": {
      "url": "http://YOUR_IP:8080/sse"
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `browser_goto(url)` | Navigate to URL |
| `browser_url()` | Get current URL |
| `browser_title()` | Get page title |
| `browser_text(selector)` | Get element text |
| `browser_html(selector)` | Get element HTML |
| `browser_click(selector)` | Click element |
| `browser_type(selector, text)` | Type into input |
| `browser_wait(selector, timeout)` | Wait for element |
| `browser_eval(script)` | Execute JavaScript |
| `browser_screenshot(path)` | Take screenshot |
| `browser_fetch(path, method, body)` | HTTP request via browser |
| `browser_pages()` | List open tabs |
| `browser_new_page(url)` | Open new tab |

## CLI Options

```
arche-browser [OPTIONS]

Options:
  --sse           Run as SSE server for remote access
  --port PORT     SSE server port (default: 8080)
  --headless      Run Chrome in headless mode
  --cdp-port PORT Chrome CDP port (default: 9222)
```

## Examples

### Web Scraping

```
User: Go to example.com and get the page title
Claude: [Uses browser_goto, browser_title tools]
```

### Form Automation

```
User: Log into my account on site.com
Claude: [Uses browser_goto, browser_type, browser_click tools]
```

### API Testing via Browser

```
User: Fetch data from the /api/users endpoint
Claude: [Uses browser_fetch tool - bypasses CORS, uses cookies]
```

## How It Works

1. Arche Browser launches Chrome with remote debugging enabled
2. Connects via Chrome DevTools Protocol (CDP)
3. Exposes browser control as MCP tools
4. Claude Code uses these tools to automate the browser

## Features

- **Real Browser**: Uses your actual Chrome with your cookies, extensions, and login sessions
- **Remote Access**: Control browser on any machine via SSE transport
- **Full CDP Access**: Screenshots, JavaScript execution, network interception
- **No Bot Detection**: Uses UI automation techniques that bypass detection
- **Persistent Profile**: Browser state persists in `~/.arche-browser/profile`

## Requirements

- Python 3.10+
- Chrome, Chromium, or Edge browser
- MCP client (Claude Code, etc.)

## License

MIT
