"""
Accessibility Tree Snapshot System

Converts Chrome's a11y tree into a compact, token-efficient format
with versioned UID-based element references.

Design: Eric Gamma style - simple, flexible, powerful.
"""

from typing import Any, Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
import time

from .utils import box_center


@dataclass
class SnapshotNode:
    """A node in the accessibility tree snapshot."""
    uid: str
    role: str
    name: str = ""
    value: str = ""
    description: str = ""
    children: List["SnapshotNode"] = field(default_factory=list)
    backend_node_id: Optional[int] = None
    # States
    focused: bool = False
    disabled: bool = False
    expanded: Optional[bool] = None
    checked: Optional[bool] = None
    selected: bool = False
    required: bool = False
    level: Optional[int] = None
    url: str = ""


class Snapshot:
    """
    Versioned accessibility tree snapshot.

    UIDs include version prefix: "v1_a", "v2_1b"
    Stale snapshot detection prevents errors from outdated UIDs.
    """

    __slots__ = ('_version', '_root', '_uid_map', '_backend_map', '_counter', '_timestamp')

    def __init__(self, version: int = 1):
        self._version = version
        self._root: Optional[SnapshotNode] = None
        self._uid_map: Dict[str, SnapshotNode] = {}
        self._backend_map: Dict[int, str] = {}
        self._counter = 0
        self._timestamp = time.time()

    @property
    def version(self) -> int:
        return self._version

    @property
    def age(self) -> float:
        """Seconds since snapshot was taken."""
        return time.time() - self._timestamp

    def _uid(self) -> str:
        """Generate versioned UID: v{version}_{base36}"""
        self._counter += 1
        n = self._counter
        chars = "0123456789abcdefghijklmnopqrstuvwxyz"
        b36 = ""
        while n:
            b36 = chars[n % 36] + b36
            n //= 36
        return f"v{self._version}_{b36 or '0'}"

    def parse(self, ax_tree: Dict) -> Optional[SnapshotNode]:
        """Parse CDP Accessibility.getFullAXTree response."""
        self._uid_map.clear()
        self._backend_map.clear()
        self._counter = 0
        self._timestamp = time.time()

        nodes = ax_tree.get("nodes", [])
        if not nodes:
            return None

        lookup = {n.get("nodeId", ""): n for n in nodes if n.get("nodeId")}
        self._root = self._parse_node(nodes[0], lookup)
        return self._root

    def _parse_node(self, data: Dict, lookup: Dict) -> SnapshotNode:
        """Parse single AX node recursively."""
        uid = self._uid()

        # Extract values from CDP format
        def val(key: str, default: Any = "") -> Any:
            v = data.get(key, {})
            return v.get("value", default) if isinstance(v, dict) else v

        # Properties from array
        props = {}
        for p in data.get("properties", []):
            pv = p.get("value", {})
            props[p.get("name", "")] = pv.get("value") if isinstance(pv, dict) else pv

        node = SnapshotNode(
            uid=uid,
            role=val("role", "unknown"),
            name=val("name"),
            value=str(val("value")) if val("value") else "",
            description=val("description"),
            backend_node_id=data.get("backendDOMNodeId"),
            focused=props.get("focused", False),
            disabled=props.get("disabled", False),
            expanded=props.get("expanded"),
            checked=props.get("checked"),
            selected=props.get("selected", False),
            required=props.get("required", False),
            level=props.get("level"),
            url=props.get("url", ""),
        )

        self._uid_map[uid] = node
        if node.backend_node_id:
            self._backend_map[node.backend_node_id] = uid

        # Parse children, skip ignored nodes
        for cid in data.get("childIds", []):
            child = lookup.get(cid)
            if child:
                if child.get("ignored"):
                    for gcid in child.get("childIds", []):
                        gc = lookup.get(gcid)
                        if gc:
                            node.children.append(self._parse_node(gc, lookup))
                else:
                    node.children.append(self._parse_node(child, lookup))

        return node

    def get(self, uid: str) -> Optional[SnapshotNode]:
        """Get node by UID."""
        return self._uid_map.get(uid)

    def backend_id(self, uid: str) -> Optional[int]:
        """Get backend DOM node ID for UID."""
        node = self._uid_map.get(uid)
        return node.backend_node_id if node else None

    def validate_uid(self, uid: str) -> bool:
        """Check if UID belongs to this snapshot version."""
        if not uid.startswith(f"v{self._version}_"):
            return False
        return uid in self._uid_map

    def format(self, verbose: bool = False, max_depth: int = 50) -> str:
        """Format as compact text."""
        if not self._root:
            return "<empty>"
        lines: List[str] = []
        self._fmt(self._root, lines, 0, verbose, max_depth)
        return "\n".join(lines)

    def _fmt(self, node: SnapshotNode, lines: List[str], depth: int, verbose: bool, max_depth: int):
        if depth > max_depth:
            return

        # Skip noise
        if node.role in ("none", "generic", "InlineTextBox") and not node.name and not verbose:
            for c in node.children:
                self._fmt(c, lines, depth, verbose, max_depth)
            return

        parts = [f"[{node.uid}]", node.role]

        if node.name:
            name = node.name[:80].replace("\n", " ")
            parts.append(f'"{name}"' + ("..." if len(node.name) > 80 else ""))

        if node.value and node.role in ("textbox", "combobox", "spinbutton", "slider"):
            parts.append(f"val={node.value[:30]}")

        # States
        for attr, label in [("focused", "●"), ("disabled", "⊘"), ("selected", "✓"), ("required", "*")]:
            if getattr(node, attr):
                parts.append(label)

        if node.expanded is not None:
            parts.append("▼" if node.expanded else "▶")
        if node.checked is not None:
            parts.append("☑" if node.checked else "☐")
        if node.level and node.role == "heading":
            parts.append(f"h{node.level}")
        if verbose and node.url:
            parts.append(f"→{node.url[:40]}")

        lines.append("  " * depth + " ".join(parts))
        for c in node.children:
            self._fmt(c, lines, depth + 1, verbose, max_depth)

    @property
    def root(self) -> Optional[SnapshotNode]:
        return self._root

    def __len__(self) -> int:
        return len(self._uid_map)


class SnapshotManager:
    """
    Manages snapshot lifecycle with version control.

    Detects stale UIDs and provides element access.
    """

    def __init__(self, browser: Any):
        self.browser = browser
        self._current: Optional[Snapshot] = None
        self._version = 0
        self._wait_helper = None

    def _get_wait_helper(self):
        if self._wait_helper is None:
            from .wait import WaitForHelper
            self._wait_helper = WaitForHelper(self.browser)
        return self._wait_helper

    def take(self, verbose: bool = False) -> Tuple[str, int]:
        """Take new snapshot. Returns (formatted_text, node_count)."""
        self._version += 1
        self._current = Snapshot(self._version)
        ax = self.browser.accessibility_tree()
        self._current.parse(ax)
        return self._current.format(verbose), len(self._current)

    def get_element(self, uid: str) -> int:
        """Get backend node ID, validating UID version."""
        if not self._current:
            raise ValueError("No snapshot. Call take() first.")

        if not self._current.validate_uid(uid):
            v = self._current.version
            raise ValueError(f"Stale UID '{uid}'. Current snapshot is v{v}. Call snapshot() for fresh UIDs.")

        backend_id = self._current.backend_id(uid)
        if not backend_id:
            raise ValueError(f"Element '{uid}' has no backend node ID")
        return backend_id

    def click(self, uid: str) -> bool:
        """Click element by UID with DOM stabilization."""
        backend_id = self.get_element(uid)

        def do_click():
            result = self.browser.cdp.send("DOM.resolveNode", {"backendNodeId": backend_id})
            obj_id = result.get("object", {}).get("objectId")
            if obj_id:
                box = self.browser.cdp.send("DOM.getBoxModel", {"backendNodeId": backend_id})
                content = box.get("model", {}).get("content", [])
                center = box_center(content)
                if center:
                    self.browser.mouse_click(center[0], center[1])
                    return True
                # Fallback: JS click (when element has no visual box)
                self.browser.cdp.send("Runtime.callFunctionOn", {
                    "objectId": obj_id,
                    "functionDeclaration": "function() { this.click(); }",
                })
                return True
            return False

        return self._get_wait_helper().wait_after_action(do_click)

    def type_text(self, uid: str, text: str, clear: bool = True) -> bool:
        """Type text into element."""
        backend_id = self.get_element(uid)

        def do_type():
            result = self.browser.cdp.send("DOM.resolveNode", {"backendNodeId": backend_id})
            obj_id = result.get("object", {}).get("objectId")
            if obj_id:
                self.browser.cdp.send("Runtime.callFunctionOn", {
                    "objectId": obj_id,
                    "functionDeclaration": f"""function() {{
                        this.focus();
                        if ({str(clear).lower()}) this.value = '';
                        this.value += {repr(text)};
                        this.dispatchEvent(new InputEvent('input', {{bubbles: true}}));
                    }}""",
                })
                return True
            return False

        return self._get_wait_helper().wait_after_action(do_type)

    def focus(self, uid: str) -> bool:
        """Focus element."""
        backend_id = self.get_element(uid)
        self.browser.cdp.send("DOM.focus", {"backendNodeId": backend_id})
        return True

    def hover(self, uid: str) -> bool:
        """Hover over element."""
        backend_id = self.get_element(uid)
        box = self.browser.cdp.send("DOM.getBoxModel", {"backendNodeId": backend_id})
        content = box.get("model", {}).get("content", [])
        center = box_center(content)
        if center:
            self.browser.mouse_move(center[0], center[1])
            return True
        return False

    @property
    def current(self) -> Optional[Snapshot]:
        return self._current

    @property
    def version(self) -> int:
        return self._version
