from threading import Lock
import json

class Connections:
    def __init__(self):
        self.lock = Lock()
        self._clients = []

    def add_conneciton(self, handler):
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
      		        client.write_message(json.dumps(message))
        finally:
            self.lock.release()
