# pyright: strict

import random
from typing import Any, Literal, NotRequired, Protocol, TypeAlias, TypedDict, cast

import vlc  # pyright: ignore[reportMissingTypeStubs]
import yt_dlp


class PlayerListener(Protocol):
    def song_finished(self) -> None: ...


class PlayerArgs(TypedDict):
    chromecast: NotRequired[tuple[str, int]]


class CommonTrackInfo(TypedDict):
    title: str
    mrl: str


class FileTrackInfo(CommonTrackInfo):
    type: Literal["file"]


class LinkTrackInfo(CommonTrackInfo):
    type: Literal["link"]


TrackInfo: TypeAlias = FileTrackInfo | LinkTrackInfo


class Player:

    SLAYRADIO = "http://relay3.slayradio.org:8000/"
    DUBSTEP = [
        "https://www.youtube.com/watch?v=dLyH94jNau0",
        "https://www.youtube.com/watch?v=RRucF7ffPRE",
        "https://www.youtube.com/watch?v=nXaMKZApYDM",
    ]
    SCRATCH = "shortscratch.wav"

    def __init__(self, listener: PlayerListener, args: PlayerArgs):
        self._listener = listener
        instance_opts = ["--no-video"]
        self._media_opts: list[str] = []
        if chromecast := args.get("chromecast"):
            instance_opts.append("--no-sout-video")
            # These options don't work as instance options, for some reason...
            self._media_opts.append(":sout=#chromecast{ip=%s,port=%d}" % chromecast)
            self._media_opts.append(":demux-filter=demux_chromecast")
        self._instance = cast(vlc.Instance, vlc.Instance(*instance_opts))
        self._mediaplayer = cast(
            vlc.MediaPlayer,
            self._instance.media_player_new(),  # pyright: ignore[reportUnknownMemberType]
        )
        vlc_events = cast(
            vlc.EventManager,
            self._mediaplayer.event_manager(),  # pyright: ignore[reportUnknownMemberType]
        )

        def _event_wrapper(*args: Any):
            listener.song_finished()

        vlc_events.event_attach(  # pyright: ignore[reportUnknownMemberType]
            vlc.EventType.MediaPlayerEndReached,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType]
            _event_wrapper,
            1,
        )
        vlc_events.event_attach(  # pyright: ignore[reportUnknownMemberType]
            vlc.EventType.MediaPlayerEncounteredError,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType]
            _event_wrapper,
            1,
        )

        self._playingDubstep = False
        self._shouldPlayDubstep = random.randint(0, 1) == 1
        self.play_fallback()

    def release(self):
        self._mediaplayer.stop()
        self._instance.release()

    def _handleDubstep(self):
        self._playingDubstep = False
        self._shouldPlayDubstep = not self._shouldPlayDubstep

    def _get_link_url(self, link: str):
        with yt_dlp.YoutubeDL(
            {
                "cookiefile": "cookies.txt",
                "quiet": True,
                "format": "bestaudio/best",
            }
        ) as ydl:
            info_dict = ydl.extract_info(link, download=False)
            return info_dict.get("url", None)

    def _play_mrl(self, mrl: str):
        self._mediaplayer.set_mrl(  # pyright: ignore[reportUnknownMemberType]
            mrl, *self._media_opts
        )
        self._mediaplayer.play()

    def play(self, track: TrackInfo):
        try:
            self._handleDubstep()
            print("Now playing: " + track["title"])
            mrl = track["mrl"]
            if (
                track["type"] == "link"
                and (link_mrl := self._get_link_url(mrl)) is not None
            ):
                mrl = link_mrl
            self._play_mrl(mrl)
        except Exception as err:
            print(err)
            self._listener.song_finished()

    def pause(self):
        self._mediaplayer.pause()

    def scratch(self):
        self._handleDubstep()
        self._play_mrl(self.SCRATCH)

    def get_position(self):
        return cast(float, self._mediaplayer.get_position())

    @property
    def fallback_type(self):
        if self._playingDubstep:
            return "dubstep"
        else:
            return "Slay Radio"

    def play_fallback(self):
        try:
            if self._shouldPlayDubstep:
                if self._playingDubstep:
                    self._dubstepTrack = (self._dubstepTrack + 1) % len(self.DUBSTEP)
                    position = 0
                else:
                    self._dubstepTrack = random.randint(0, len(self.DUBSTEP) - 1)
                    position = random.random()
                self._playingDubstep = True
                print("Now playing: Dubstep")
                url = self._get_link_url(self.DUBSTEP[self._dubstepTrack])
                assert url is not None, "Error getting fallback URL"
                self._play_mrl(url)
                self._mediaplayer.set_position(  # pyright: ignore[reportUnknownMemberType]
                    position
                )
            else:
                print("Now playing: Slay Radio")
                self._play_mrl(self.SLAYRADIO)
        except Exception as err:
            print(err)
            self._listener.song_finished()
