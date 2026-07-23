import random
from typing import NotRequired, TypedDict, cast

import vlc
import yt_dlp


class PlayerArgs(TypedDict):
    chromecast: NotRequired[tuple[str, int]]


class Player:

    SLAYRADIO = "http://relay3.slayradio.org:8000/"
    DUBSTEP = [
        "https://www.youtube.com/watch?v=dLyH94jNau0",
        "https://www.youtube.com/watch?v=RRucF7ffPRE",
        "https://www.youtube.com/watch?v=nXaMKZApYDM",
    ]
    SCRATCH = "shortscratch.wav"

    def __init__(self, juggler, args: PlayerArgs):
        self._juggler = juggler
        instance_opts = ["--no-video"]
        self._media_opts = []
        if chromecast := args.get("chromecast"):
            instance_opts.append("--no-sout-video")
            # These options don't work as instance options, for some reason...
            self._media_opts.append(":sout=#chromecast{ip=%s,port=%d}" % chromecast)
            self._media_opts.append(":demux-filter=demux_chromecast")
        self._instance = cast(vlc.Instance, vlc.Instance(*instance_opts))
        self._mediaplayer = self._instance.media_player_new()
        vlc_events = self._mediaplayer.event_manager()
        vlc_events.event_attach(
            vlc.EventType.MediaPlayerEndReached,  # pyright: ignore[reportAttributeAccessIssue]
            juggler.song_finished,
            1,
        )
        vlc_events.event_attach(
            vlc.EventType.MediaPlayerEncounteredError,  # pyright: ignore[reportAttributeAccessIssue]
            juggler.song_finished,
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

    def _get_link_url(self, link):
        with yt_dlp.YoutubeDL(
            {
                "cookiefile": "cookies.txt",
                "quiet": True,
                "format": "bestaudio/best",
            }
        ) as ydl:
            info_dict = ydl.extract_info(link, download=False)
            return info_dict.get("url", None)

    def _play_mrl(self, mrl):
        self._mediaplayer.set_mrl(mrl, *self._media_opts)
        self._mediaplayer.play()

    def play(self, track):
        try:
            self._handleDubstep()
            print("Now playing: " + track["filename"])
            mrl = track["mrl"]
            if track["type"] == "link":
                mrl = self._get_link_url(mrl)
            self._play_mrl(mrl)
        except Exception as err:
            print(err)
            self._juggler.song_finished()

    def pause(self):
        self._mediaplayer.pause()

    def scratch(self):
        self._handleDubstep()
        self._play_mrl(self.SCRATCH)

    def get_position(self):
        return self._mediaplayer.get_position()

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
                self._play_mrl(url)
                self._mediaplayer.set_position(position)
            else:
                print("Now playing: Slay radio")
                self._play_mrl(self.SLAYRADIO)
        except Exception as err:
            print(err)
            self._juggler.song_finished()
