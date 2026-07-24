# pyright: strict

import collections
import threading
import time
import uuid
from typing import IO, Literal, NotRequired, TypeAlias, TypedDict

# local libs
import connections
import player


class ListResponseEntry(TypedDict):
    id: str
    title: str
    nick: str | None
    address: str | None
    prio: int


class ListResponse(TypedDict):
    type: Literal["list"]
    position: float
    list: list[ListResponseEntry]


class FallbackResponse(TypedDict):
    type: Literal["fallback"]
    description: str


class TrackInputCommon(TypedDict):
    upload_id: NotRequired[str | None]
    nick: NotRequired[str | None]
    address: str | None
    title: str
    mrl: str


class FileTrackInput(TrackInputCommon):
    type: Literal["file"]
    filename: str | None
    extn: str | None
    handle: IO[bytes]


class LinkTrackInput(TrackInputCommon):
    type: Literal["link"]


class TrackAssigned(TypedDict):
    id: str
    prio: int


class FileTrack(TrackAssigned, FileTrackInput): ...


class LinkTrack(TrackAssigned, LinkTrackInput): ...


TrackInput: TypeAlias = FileTrackInput | LinkTrackInput
Track: TypeAlias = FileTrack | LinkTrack


class DownloadInfo(TypedDict):
    type: Literal["file", "link"]
    filename: str | None
    mrl: str


class _ParentWaiter:
    def __init__(self, lock: threading.RLock) -> None:
        self._cond = threading.Condition(lock)
        self._success = False

    def wait(self, timeout: float | None = None):
        if self._cond.wait(timeout):
            return self._success
        return False

    def done(self, success: bool):
        self._success = success
        self._cond.notify_all()


class Juggler(player.PlayerListener):
    def __init__(
        self,
        clients: connections.Connections,
        player_args: player.PlayerArgs | None = None,
    ):
        self._clients = clients
        self._player_args: player.PlayerArgs = player_args or {}
        self._songlist: list[Track] = []
        self._counts: collections.Counter[str | None] = collections.Counter()
        self._event = threading.Event()
        self._waiting: dict[str, _ParentWaiter] = {}
        self._running = False
        self.lock = threading.RLock()

    def _remove_song(self, index: int, song: Track | None = None):
        if song is None:
            song = self._songlist[index]
        self._counts[song["address"]] -= 1
        del self._songlist[index]

    def start(self):
        if not self._running:
            self._player = player.Player(self, self._player_args)
            self._next_thread = threading.Thread(target=self.play_next, args=())
            self._progress_thread = threading.Thread(target=self.time_change, args=())
            self._running = True
            self._next_thread.start()
            self._progress_thread.start()
            self._clients.message_clients(self.get_list())

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

    def pause(self):
        self.lock.acquire()
        try:
            self._player.pause()
        finally:
            self.lock.release()

    def juggle(self, infile: TrackInput, parent_id: str | None = None):
        if not self._running:
            raise Exception("Queue is not running")

        threading.Thread(target=self._juggle, args=(infile, parent_id)).start()

    def _juggle(self, track_input: TrackInput, parent_id: str | None = None):
        self.lock.acquire()
        try:
            if parent_id is not None:
                for song in reversed(self._songlist):
                    if "upload_id" in song and song["upload_id"] == parent_id:
                        break
                else:  # Not found
                    if not parent_id in self._waiting:
                        self._waiting[parent_id] = _ParentWaiter(self.lock)
                    if not (self._waiting[parent_id].wait(30)):
                        return

            self._counts[track_input["address"]] += 1
            prio = max(self._counts[track_input["address"]] - 3, 0)
            index = 0
            if len(self._songlist) > 0:
                index = 1
                for item in self._songlist[1:]:
                    if item["prio"] > prio:
                        break
                    index += 1
            extn = track_input["extn"] if "extn" in track_input else None
            juggle_data: TrackAssigned = {
                "id": str(uuid.uuid4()) + (extn or ""),
                "prio": prio,
            }
            # Apparently, the typing is a bit too complicated for pyright.
            # This seemingly redundant structure is needed to not confuse it.
            match track_input["type"]:
                case "file":
                    track: Track = {**juggle_data, **track_input}
                case "link":
                    track: Track = {**juggle_data, **track_input}
            self._songlist.insert(index, track)

            if len(self._songlist) == 1:
                self._player.play(track)

            if "upload_id" in track_input and track_input["upload_id"] in self._waiting:
                self._waiting[track_input["upload_id"]].done(True)
                del self._waiting[track_input["upload_id"]]
        finally:
            self.lock.release()
        self._clients.message_clients(self.get_list())

    def download(self, track_id: str) -> DownloadInfo | None:
        self.lock.acquire()
        try:
            for song in self._songlist:
                if song["id"] == track_id:
                    return {
                        "type": song["type"],
                        "filename": (
                            song["filename"] if song["type"] == "file" else None
                        ),
                        "mrl": song["mrl"],
                    }
            else:  # Not found
                return None
        finally:
            self.lock.release()

    def cancel(self, track_id: str, address: str | None):
        self.lock.acquire()
        try:
            for i, song in list(enumerate(self._songlist)):
                if song["id"] == track_id and song["address"] == address:
                    if i == 0:
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
                wait.done(False)
            self._waiting.clear()
            for i, song in reversed(list(enumerate(self._songlist))):
                if i == 0:
                    self.skip()
                self._remove_song(i, song)
        finally:
            self.lock.release()
        self._clients.message_clients(self.get_list())

    def song_finished(self):
        self._event.set()

    def time_change(self):
        while self._running:
            time.sleep(1)
            self.send_progress()

    def send_progress(self):
        self.lock.acquire()
        try:
            position = self._player.get_position()
        finally:
            self.lock.release()
        if position > 0:
            self._clients.message_clients({"type": "progress", "position": position})

    def play_next(self):
        while self._running:
            self._event.wait()
            self._event.clear()
            if not self._running:
                break
            self.lock.acquire()
            try:
                if not self._songlist:
                    self._player.play_fallback()
                else:
                    self._remove_song(0)
                    if not self._songlist:
                        self._player.play_fallback()
                    else:
                        self._player.play(self._songlist[0])
            finally:
                self.lock.release()
            self._clients.message_clients(self.get_list())

    def _sanitize_item(self, item: Track) -> ListResponseEntry:
        return {
            "id": item["id"],
            "title": item["title"],
            "nick": item.get("nick", ""),
            "address": item["address"],
            "prio": item["prio"],
        }

    def get_list(self) -> ListResponse | FallbackResponse:
        self.lock.acquire()
        try:
            if self._songlist:
                position = self._player.get_position()
                return {
                    "type": "list",
                    "position": position,
                    "list": list(map(self._sanitize_item, self._songlist)),
                }
            else:
                if self._running:
                    message = f"Now playing {self._player.fallback_type}..."
                else:
                    message = "Not active"
                return {"type": "fallback", "description": message}
        finally:
            self.lock.release()
