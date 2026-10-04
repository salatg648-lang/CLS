"""Kleine synchrone Event-Schnittstelle; Payloads enthalten nur IDs."""


class EventBus:
    def __init__(self):
        self._listeners = []

    def subscribe(self, listener):
        self._listeners.append(listener)

    def emit(self, event, **payload):
        for listener in tuple(self._listeners):
            listener(event=event, **payload)
