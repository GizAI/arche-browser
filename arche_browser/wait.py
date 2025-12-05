"""
WaitForHelper - DOM Stabilization

Waits for DOM to stabilize after actions.
Inspired by chrome-devtools-mcp's WaitForHelper.
"""

import time
import threading
from typing import Any, Callable, Optional
from dataclasses import dataclass


@dataclass
class WaitConfig:
    """Wait timing configuration."""
    stable_dom_timeout: float = 3.0      # Max wait for DOM stability
    stable_dom_for: float = 0.1          # DOM must be stable for this long
    navigation_timeout: float = 3.0       # Max wait for navigation
    navigation_detect: float = 0.1        # Time to detect navigation start


class WaitForHelper:
    """
    Waits for DOM stabilization after actions.

    Uses MutationObserver pattern via CDP to detect when
    the page has stopped changing.
    """

    def __init__(self, browser: Any, config: Optional[WaitConfig] = None):
        self.browser = browser
        self.config = config or WaitConfig()
        self._aborted = False

    def abort(self):
        """Abort waiting."""
        self._aborted = True

    def wait_for_stable_dom(self) -> bool:
        """
        Wait for DOM to be stable (no mutations for stable_dom_for seconds).

        Returns:
            True if DOM stabilized, False if timeout
        """
        script = f"""
        new Promise((resolve) => {{
            let timeoutId;
            const stableFor = {int(self.config.stable_dom_for * 1000)};
            const maxTimeout = {int(self.config.stable_dom_timeout * 1000)};

            const observer = new MutationObserver(() => {{
                clearTimeout(timeoutId);
                timeoutId = setTimeout(() => {{
                    observer.disconnect();
                    resolve(true);
                }}, stableFor);
            }});

            // Start initial timeout (DOM might already be stable)
            timeoutId = setTimeout(() => {{
                observer.disconnect();
                resolve(true);
            }}, stableFor);

            // Overall timeout
            setTimeout(() => {{
                observer.disconnect();
                resolve(false);
            }}, maxTimeout);

            const target = document.body || document.documentElement;
            if (!target) {{
                resolve(true);  // No DOM yet, consider stable
                return;
            }}
            observer.observe(target, {{
                childList: true,
                subtree: true,
                attributes: true
            }});
        }})
        """
        try:
            return self.browser.eval(script, timeout=self.config.stable_dom_timeout + 1)
        except Exception:
            return False

    def wait_for_navigation(self) -> bool:
        """
        Wait for any pending navigation to complete.

        Returns:
            True if navigation completed or none detected
        """
        # Check if navigation is happening by monitoring readyState
        script = """
        new Promise((resolve) => {
            if (document.readyState === 'complete') {
                resolve(true);
                return;
            }

            const onLoad = () => {
                window.removeEventListener('load', onLoad);
                resolve(true);
            };
            window.addEventListener('load', onLoad);

            // Timeout fallback
            setTimeout(() => {
                window.removeEventListener('load', onLoad);
                resolve(document.readyState === 'complete');
            }, %d);
        })
        """ % int(self.config.navigation_timeout * 1000)

        try:
            return self.browser.eval(script, timeout=self.config.navigation_timeout + 1)
        except Exception:
            return False

    def wait_after_action(self, action: Callable[[], Any]) -> Any:
        """
        Execute action and wait for DOM to stabilize.

        Args:
            action: Function to execute

        Returns:
            Action result
        """
        self._aborted = False

        # Execute action
        result = action()

        if self._aborted:
            return result

        # Small delay to let navigation start
        time.sleep(self.config.navigation_detect)

        if self._aborted:
            return result

        # Wait for navigation if any
        self.wait_for_navigation()

        if self._aborted:
            return result

        # Wait for DOM stability
        self.wait_for_stable_dom()

        return result
