from threading import Lock
import json

class Connections:
    def __init__(self, ioloop):
        self.lock = Lock()
        self._ioloop = ioloop
        self._clients = []

    def add_connection(self, handler):
        self.lock.acquire()
        try:
            self._clients.append(handler)
        finally:
            self.lock.release()

    def close_connection(self, handler):
        self.lock.acquire()
        try:
            self._clients.remove(handler)
        finally:
            self.lock.release()

    def message_clients(self, message):
        self.lock.acquire()
        try:
            for client in self._clients:
                self._ioloop.add_callback(client.write_message, json.dumps(message))
        finally:
            self.lock.release()
