# Arche Browser

MCP Server for Browser Automation via Chrome DevTools Protocol.

Control a real Chrome browser from Claude Code or any MCP client.

## Features

- **Full Browser Control**: Navigation, clicks, typing, screenshots, and more
- **Real Browser**: Uses your actual Chrome with cookies, extensions, login sessions
- **Remote Access**: Control browser on any machine via SSE transport
- **Token Authentication**: Secure remote access with auto-generated tokens
- **Site-Specific Clients**: Built-in ChatGPT client with bot detection bypass
- **Complete CDP Access**: Cookies, storage, network, console, emulation, performance

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

### As MCP Server (Local)

Add to Claude Code settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "browser": {
      "command": "arche-browser"
    }
  }
}
```

### As MCP Server (Remote)

On the machine with Chrome:

```bash
arche-browser --sse --port 8080

# Output:
# [*] Auth: ENABLED
# [*] Token: abc123...
# [*] Connect URL: http://localhost:8080/sse?token=abc123...
```

On Claude Code (use the token from server output):

```json
{
  "mcpServers": {
    "browser": {
      "url": "http://YOUR_IP:8080/sse?token=YOUR_TOKEN"
    }
  }
}
```

### Authentication

Remote SSE servers are protected by token authentication by default:

```bash
# Token is auto-generated and saved to ~/.arche-browser/token
arche-browser --sse --port 8080

# Show current token
arche-browser --show-token

# Generate new token
arche-browser --reset-token

# Use custom token
arche-browser --sse --token my-secret-token

# Disable auth (not recommended)
arche-browser --sse --no-auth
```

### As Python Library

```python
from arche_browser import Browser, Chrome

# Start Chrome and connect
with Chrome() as chrome:
    b = Browser()
    b.goto("https://example.com")
    print(b.title)
    b.screenshot("page.png")
```

### ChatGPT Client

```python
from arche_browser.sites import ChatGPT

client = ChatGPT("localhost:9222")
print(client.user)
print(client.models())
response = client.send("Tell me a joke")
print(response)
```

## MCP Tools

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

### Waiting
| Tool | Description |
|------|-------------|
| `wait_for(selector)` | Wait for element |
| `wait_gone(selector)` | Wait for removal |
| `wait_for_text(text)` | Wait for text |

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

### Network
| Tool | Description |
|------|-------------|
| `fetch(path, method, body)` | HTTP via browser |
| `network_enable()` | Enable monitoring |
| `network_requests()` | Get requests |

### Emulation
| Tool | Description |
|------|-------------|
| `set_viewport(w, h)` | Set viewport |
| `set_user_agent(ua)` | Set user agent |
| `set_geolocation(lat, lon)` | Set location |
| `set_timezone(tz)` | Set timezone |
| `set_offline(bool)` | Offline mode |
| `throttle_network(down, up)` | Throttle speed |

### Input Events
| Tool | Description |
|------|-------------|
| `mouse_move(x, y)` | Move mouse |
| `mouse_click(x, y)` | Click at coords |
| `key_press(key)` | Press key |
| `key_type(text)` | Type text |

### JavaScript
| Tool | Description |
|------|-------------|
| `evaluate(script)` | Execute JS |

### Pages
| Tool | Description |
|------|-------------|
| `get_pages()` | List tabs |
| `new_page(url)` | Open new tab |
| `close_page(id)` | Close tab |

### Debugging
| Tool | Description |
|------|-------------|
| `console_messages()` | Get console |
| `highlight_element(sel)` | Highlight |
| `get_performance_metrics()` | Perf metrics |

## CLI Options

```
arche-browser [OPTIONS]

Options:
  --sse           Run as SSE server for remote access
  --port PORT     SSE server port (default: 8080)
  --headless      Run Chrome in headless mode
  --no-auth       Disable token authentication
  --token TOKEN   Use specific auth token
  --show-token    Show current auth token
  --reset-token   Generate new auth token
  -h, --help      Show help
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
└── sites/
    └── chatgpt.py # ChatGPT-specific client
```

## Requirements

- Python 3.10+
- Chrome, Chromium, or Edge browser
- MCP client (Claude Code, etc.)

## License

MIT
