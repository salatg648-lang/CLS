"""Local text clipboard through the desktop's existing Tk event loop.

The UI installs a dispatcher; headless callers can inject a backend. No provider
or shell receives clipboard content. Missing desktop access fails explicitly.
"""
from config.agent import MAX_FILE_BYTES
from tools.safety import ToolBlocked


class Clipboard:
    def __init__(self):
        self.dispatch = None

    def read(self):
        if self.dispatch is None:
            raise ToolBlocked('Clipboard benötigt eine laufende Desktop-Sitzung.')
        text = self.dispatch('read', None)
        if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_FILE_BYTES:
            raise ToolBlocked('Clipboard enthält keinen begrenzten Text.')
        return text

    def write(self, content):
        if self.dispatch is None:
            raise ToolBlocked('Clipboard benötigt eine laufende Desktop-Sitzung.')
        if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_FILE_BYTES:
            raise ToolBlocked('Clipboard benötigt begrenzten Text.')
        self.dispatch('write', content)
        return self.read() == content


def attach(root, clipboard):
    """Tk calls stay on the UI thread; task workers exchange data via a queue."""
    import queue
    import threading
    requests = queue.Queue()
    ui_thread = threading.get_ident()
    def perform(operation, content):
        try:
            if operation == 'read':
                return root.clipboard_get()
            root.clipboard_clear()
            root.clipboard_append(content)
            return None
        except Exception as exc:
            raise ToolBlocked('Clipboard ist nicht als Text verfügbar.') from exc
    def dispatch(operation, content):
        if threading.get_ident() == ui_thread:
            return perform(operation, content)
        result = queue.Queue(maxsize=1)
        cancelled = threading.Event()
        requests.put((operation, content, result, cancelled))
        try:
            value = result.get(timeout=10)
        except queue.Empty:
            cancelled.set()
            raise ToolBlocked('Desktop antwortet nicht auf Clipboard-Anfrage.') from None
        if isinstance(value, Exception):
            raise value
        return value
    def poll():
        while True:
            try:
                operation, content, result, cancelled = requests.get_nowait()
            except queue.Empty:
                break
            if cancelled.is_set():
                continue
            try:
                result.put(perform(operation, content))
            except Exception as exc:
                result.put(exc)
        root.after(50, poll)
    clipboard.dispatch = dispatch
    root.after(50, poll)
