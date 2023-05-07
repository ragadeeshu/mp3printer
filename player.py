import vlc
import random
import yt_dlp

class Player:
    def __init__(self, juggler):
        self._juggler = juggler
        self.instance = vlc.Instance("--no-video")
        self.mediaplayer = self.instance.media_player_new()
        self._fallback = self.instance.media_new("http://relay3.slayradio.org:8000/")
        self._scratch = self.instance.media_new("shortscratch.wav")
        self.vlc_events = self.mediaplayer.event_manager()
        self.vlc_events.event_attach(vlc.EventType.MediaPlayerEndReached, juggler.song_finished, 1)
        self.vlc_events.event_attach(vlc.EventType.MediaPlayerEncounteredError, juggler.song_finished, 1)
        self._playingDubstep=False
        self._shouldPlayDubstep=False;
        self._dubstepPosition=[random.randint(0,2),random.random()]
        self._dubstep = [
            "https://www.youtube.com/watch?v=dLyH94jNau0",
            "https://www.youtube.com/watch?v=RRucF7ffPRE",
            "https://www.youtube.com/watch?v=nXaMKZApYDM"
        ]
        self.play_fallback()

    def handleDubstep(self):
        self._playingDubstep = False
        self._dubstepPosition=[random.randint(0,2),random.random()]
        self._shouldPlayDubstep = not self._shouldPlayDubstep

    def play(self, filename, path):
        self.handleDubstep()
        print("Now playing: "+filename)
        self.media = self.instance.media_new(path)
        self.mediaplayer.set_media(self.media)
        self.mediaplayer.play()

    def scratch(self):
        self.handleDubstep()
        self.mediaplayer.set_media(self._scratch)
        self.mediaplayer.play()

    def get_position(self):
        return self.mediaplayer.get_position()

    def play_fallback(self):
        if(self._shouldPlayDubstep):
            if(self._playingDubstep):
                self._dubstepPosition[0]=(self._dubstepPosition[0]+1)%len(self._dubstep)
                self._dubstepPosition[1]=0
            print("Now playing: Dubstep")
            self._playingDubstep = True;
            ydl_opts = {
            'quiet': "True",
            'format': 'bestaudio/best'}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(self._dubstep[self._dubstepPosition[0]], download=False)
                url = info_dict.get("url", None)
            self.media = self.instance.media_new(url)
            self.mediaplayer.set_media(self.media)
            self.mediaplayer.play()
            self.mediaplayer.set_position(self._dubstepPosition[1])
        else:
            print("Now playing: Slay radio")
            self.mediaplayer.set_media(self._fallback)
            self.mediaplayer.play()
