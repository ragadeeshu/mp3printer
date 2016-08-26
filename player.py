import mp3Juggler
import vlc

class Player:
    def __init__(self, juggler):
        self._juggler = juggler
        # creating a basic vlc instance
        self.instance = vlc.Instance()
        # creating an empty vlc media player
        self.mediaplayer = self.instance.media_player_new()
        self._fallback = self.instance.media_new("http://relay1.slayradio.org:8000/")
        self.vlc_events = self.mediaplayer.event_manager()
        self.vlc_events.event_attach(vlc.EventType.MediaPlayerEndReached, juggler.song_finished, 1)
        self.play_fallback()

    def play(self, filename, path):
        print("Now playing: "+filename)
        self.media = self.instance.media_new(path)
        self.mediaplayer.set_media(self.media)
        self.mediaplayer.play()

    def get_position(self):
        return self.mediaplayer.get_position()

    def play_fallback(self):
        print("Now playing: Slay radio")
        self.mediaplayer.set_media(self._fallback)
        self.mediaplayer.play()
