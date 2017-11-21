import player
import os
# import connections
from threading import Thread
from threading import Event
from threading import Lock
import time
class mp3Juggler:
    def __init__(self, clients):
        self._player = player.Player(self);
        self._clients = clients
        self._songlist = []
        self._counts = {}
        self._event = Event()
        self._t = Thread(target=self.play_next, args=())
        self._t.start()
        self._t2 = Thread(target=self.time_change, args=())
        self._t2.start()
        self.lock = Lock()

    def skip(self):
        self.lock.acquire()
        try:
            self._player.scratch()
        finally:
            self.lock.release()

    def juggle(self, file):
        self.lock.acquire()
        try:
            file['prio'] = self._counts.get(file['address'], 0)+ 1
            self._counts[file['address']] = file ['prio']
            index = 0
            if (len(self._songlist)) > 0:
                index = 1
                for item in self._songlist[1:]:
                    if(item['prio']>file['prio']):
                        break
                    index+= 1
            self._songlist.insert(index, file)

            if(len(self._songlist)) == 1:
                self._player.play(file['filename'], file['path'])
        finally:
            self.lock.release()
        self._clients.message_clients(self.get_list())


    def song_finished(self, event, player):
        self._event.set()

    def time_change(self):
        while True:
            time.sleep(1)
            self.send_progress()

    def send_progress(self):
        self.lock.acquire()
        try:
            position = self._player.get_position();
        finally:
            self.lock.release()
        if position > 0:
            self._clients.message_clients({'type':'progress', 'position':position})


    def play_next(self):
        while True:
            self._event.wait()
            self._event.clear()
            self.lock.acquire()
            try:
                if(not self._songlist):
                    self._player.play_fallback()
                else:
                    self._counts[self._songlist[0]['address']]-= 1
                    os.remove(self._songlist[0]['path'])
                    del(self._songlist[0])
                    if(not self._songlist):
                        self._player.play_fallback()
                    else:
                        next = self._songlist[0]
                        self._player.play(next['filename'], next['path'] )
            finally:
                self.lock.release()
            self._clients.message_clients(self.get_list())


    def get_list(self):
        self.lock.acquire()
        try:
            if(self._songlist):
                position = self._player.get_position();
                return {'type':'list', 'position':position, 'list':self._songlist}
            else:
                return {'type':'fallback', 'filename': "Now playing Slay Radio..."}
        finally:
            self.lock.release()
