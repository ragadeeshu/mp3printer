import os
from threading import Thread, Event, RLock, Condition
import time
import uuid

# local libs
from player import Player

class mp3Juggler:
    def __init__(self, clients):
        self._clients = clients
        self._songlist = []
        self._counts = {}
        self._event = Event()
        self._waiting = {}
        self._running = False
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

    def start(self):
        if not self._running:
            self._running = True
            self._player = Player(self);
            self._next_thread = Thread(target=self.play_next, args=())
            self._next_thread.start()
            self._progress_thread = Thread(target=self.time_change, args=())
            self._progress_thread.start()

    def stop(self):
        if self._running:
            self._running = False
            self._event.set()
            self.clear()
            self._next_thread.join()
            self._progress_thread.join()
            self._player.release()

    def skip(self):
        self.lock.acquire()
        try:
            self._player.scratch()
        finally:
            self.lock.release()

    def juggle(self, infile, parent_id = None):
        if not self._running:
            raise Exception('Queue is not running')

        Thread(target=self._juggle, args=(infile, parent_id)).start()

    def _juggle(self, infile, parent_id):
        self.lock.acquire()
        try:
            if parent_id is not None:
                for i, song in reversed(list(enumerate(self._songlist))):
                    if 'upload_id' in song and song['upload_id'] == parent_id:
                        break
                else:  # Not found
                    remove = True
                    try:
                        if not parent_id in self._waiting:
                            self._waiting[parent_id] = [Condition(self.lock), False]
                        wait = self._waiting[parent_id]
                        if wait[0].wait(30) and wait[1]:
                            remove = False
                        else:
                            return False
                    finally:
                        if remove:
                            try:
                                os.remove(infile['path'])
                            except:
                                pass

            infile['prio'] = self._counts.get(infile['address'], 0) + 1
            self._counts[infile['address']] = self._counts.get(infile['address'], 0) + 1
            infile['prio'] = max(infile['prio'] - 3, 0)
            index = 0
            if len(self._songlist) > 0:
                index = 1
                for item in self._songlist[1:]:
                    if(item['prio']>infile['prio']):
                        break
                    index+= 1
            extn = infile['extn'] if 'extn' in infile else ''
            infile['id'] = str(uuid.uuid4()) + extn
            self._songlist.insert(index, infile)

            if len(self._songlist) == 1:
                self._player.play(infile['filename'], infile['path'])

            if 'upload_id' in infile and infile['upload_id'] in self._waiting:
                wait = self._waiting[infile['upload_id']]
                wait[1] = True
                wait[0].notify_all()
                del(self._waiting[infile['upload_id']])
        finally:
            self.lock.release()
        self._clients.message_clients(self.get_list())

    def download(self, track_id):
        self.lock.acquire()
        try:
            for song in self._songlist:
                if song['id'] == track_id:
                    return {
                        'type': song['type'],
                        'filename': song['filename'],
                        'mrl': song['mrl']
                    }
            else:  # Not found
                return None
        finally:
            self.lock.release()

    def cancel(self, infile):
        self.lock.acquire()
        try:
            for i, song in list(enumerate(self._songlist)):
                if(song['id']==infile['id'] and song['address']==infile['address']):
                    if(i==0):
                        self.skip()
                    else:
                        self._remove_song(i, song)
                    break
        finally:
            self.lock.release()
        self._clients.message_clients(self.get_list())

    def clear(self):
        self.lock.acquire()
        try:
            for wait in self._waiting.values():
                wait[1] = False
                wait[0].notify_all()
            self._waiting.clear()
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
            self._clients.message_clients({'type': 'progress', 'position': position})


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

    def _sanitize_item(self, item):
        return {
            'id': item['id'],
            'filename': item['filename'],
            'nick': item['nick'],
            'address': item['address'],
            'prio': item['prio']
        }

    def get_list(self):
        self.lock.acquire()
        try:
            if(self._songlist):
                position = self._player.get_position();
                return {
                    'type': 'list',
                    'position': position,
                    'list': list(map(self._sanitize_item, self._songlist))
                }
            else:
                if(self._player._playingDubstep):
                    message = "Now playing dubstep..."
                else:
                    message = "Now playing Slay Radio..."
                return { 'type': 'fallback', 'filename': message}
        finally:
            self.lock.release()
