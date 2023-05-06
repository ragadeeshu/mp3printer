import player
import os
# import connections
from threading import Thread
from threading import Event
from threading import RLock
import time
class mp3Juggler:
    def __init__(self, clients):
        self._player = player.Player(self);
        self._clients = clients
        self._songlist = []
        self._counts = {}
        self._event = Event()
        self._running = True
        self._t = Thread(target=self.play_next, args=())
        self._t.start()
        self._t2 = Thread(target=self.time_change, args=())
        self._t2.start()
        self.lock = RLock()

    def _remove_song(self, i, song = None):
        if song is None:
            song = self._songlist[i]
        self._counts[song['address']]-= 1
        try:
            os.remove(song['path'])
        except:
            pass
        del(self._songlist[i])

    def stop(self):
        self._running = False
        self._event.set()
        self.clear()

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
            self._counts[file['address']] = self._counts.get(file['address'], 0) + 1
            file ['prio'] = max( file ['prio'] - 3 , 0 )
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

    def cancel(self, infile):
        self.lock.acquire()
        try:
            for i, song in reversed(list(enumerate(self._songlist))):
                if(song['mrl']==infile['mrl'] and song['address']==infile['address']):
                    if(i==0):
                        self.skip()
                    else:
                        self._remove_song(i, song)
        finally:
            self.lock.release()
        self._clients.message_clients(self.get_list())

    def clear(self):
        self.lock.acquire()
        try:
            for i, song in reversed(list(enumerate(self._songlist))):
                if(i==0):
                    self.skip()
                self._remove_song(i, song)
        finally:
            self.lock.release()
        self._clients.message_clients(self.get_list())

    def song_finished(self, event, player):
        self._event.set()

    def time_change(self):
        while self._running:
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
        while self._running:
            self._event.wait()
            self._event.clear()
            if not self._running:
                break
            self.lock.acquire()
            try:
                if(not self._songlist):
                    self._player.play_fallback()
                else:
                    self._remove_song(0)
                    if(not self._songlist):
                        self._player.play_fallback()
                    else:
                        nxt = self._songlist[0]
                        self._player.play(nxt['filename'], nxt['path'] )
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
                if(self._player._playingDubstep):
                    message = "Now playing dubstep..."
                else:
                    message = "Now playing Slay Radio..."
                return {'type':'fallback', 'filename': message}
        finally:
            self.lock.release()
