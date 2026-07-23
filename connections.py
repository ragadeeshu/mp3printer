# pyright: strict

import json
import threading
from typing import Any

import tornado.ioloop
import tornado.websocket


class Connections:
    def __init__(self, ioloop: tornado.ioloop.IOLoop):
        self.lock = threading.Lock()
        self._ioloop = ioloop
        self._clients: list[tornado.websocket.WebSocketHandler] = []

    def add_connection(self, handler: tornado.websocket.WebSocketHandler):
        self.lock.acquire()
        try:
            self._clients.append(handler)
        finally:
            self.lock.release()

    def close_connection(self, handler: tornado.websocket.WebSocketHandler):
        self.lock.acquire()
        try:
            self._clients.remove(handler)
        finally:
            self.lock.release()

    def message_clients(self, message: Any):
        self.lock.acquire()
        try:
            for client in self._clients:
                self._ioloop.add_callback(  # pyright: ignore[reportUnknownMemberType]
                    client.write_message, json.dumps(message)
                )
        finally:
            self.lock.release()
