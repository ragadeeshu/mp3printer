# pyright: strict

import argparse
import json
import os
import re
import shutil
import signal
import tempfile
import threading
import urllib.parse
from typing import IO, Any, Callable, cast

import tinytag
import tornado.httpserver
import tornado.ioloop
import tornado.web
import tornado.websocket
import yt_dlp

# optional libs
try:
    # Chromecast support
    import pychromecast.discovery
except ModuleNotFoundError:
    pychromecast = None
try:
    # Spotify "support"
    import spotify_scraper
    import youtube_search  # pyright: ignore[reportMissingTypeStubs]
except ModuleNotFoundError:
    spotify_scraper = None
    youtube_search = None

# local libs
import connections
import mp3Juggler
import player

loop = None
clients = None
juggler = None
http_server = None

ANSI_ESCAPE = re.compile(r"(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]")
ERROR_PREFIX = re.compile(r"^[Ee][Rr][Rr]([Oo][Rr])?:\s*")


def error_message(err: Any):
    return ERROR_PREFIX.sub("", ANSI_ESCAPE.sub("", str(err)))


def actual_remote_ip(request: tornado.httpserver.HTTPRequest):
    return str(request.remote_ip) if request.remote_ip else None


def forwarded_remote_ip(request: tornado.httpserver.HTTPRequest):
    return request.headers.get("X-Forwarded-For")


remote_ip: Callable[[tornado.httpserver.HTTPRequest], str | None] = actual_remote_ip


class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.render("index.html")


@tornado.web.stream_request_body
class AddFile(tornado.web.RequestHandler):
    def prepare(self):
        self.fh: IO[bytes] | None = None
        self.metadata: mp3Juggler.FileTrackInput | None = None
        self.error: Exception | None = None
        self.done = False
        try:
            free = shutil.disk_usage(tempfile.gettempdir()).free
            if int(self.request.headers.get("Content-Length", 0)) > free / 2:
                raise Exception("Uploaded file too large for current free space")
            file_type = self.request.headers.get("Content-Type", "")
            if not file_type.startswith("audio/") and not file_type.startswith(
                "video/"
            ):
                raise Exception("Only audio or video files, please")
            filename = self.request.headers.get("Filename")
            if filename is not None:
                base, extn = os.path.splitext(filename)
            else:
                base, extn = None, None
            tf = tempfile.NamedTemporaryFile(
                prefix=base, suffix=extn, delete_on_close=False
            )
            self.metadata = {
                "type": "file",
                "upload_id": self.request.headers.get("Upload-Id"),
                "nick": self.request.headers.get("Nick"),
                "title": filename or "Unknown",  # TODO
                "filename": filename,
                "extn": extn,
                "address": remote_ip(self.request),
                "mrl": tf.name,
                "handle": tf,  # This keeps the NamedTemporaryFile in scope
            }
            self.fh = tf
        except Exception as err:
            self.error = err

    def data_received(self, chunk: bytes):
        if self.error is None:
            try:
                assert self.fh is not None
                self.fh.write(chunk)
            except Exception as err:
                self.error = err

    def put(self):
        try:
            if self.error is not None:
                raise self.error
            assert self.fh is not None
            self.fh.close()
            assert juggler is not None
            assert self.metadata is not None
            try:
                tags = tinytag.TinyTag.get(self.fh.name)
                if tags.title:
                    title = tags.title
                    if tags.artist:
                        title = f"{tags.artist} - {title}"
                    self.metadata["title"] = title
            except:
                pass
            juggler.juggle(self.metadata, self.request.headers.get("Parent-Id"))
            self.done = True
            self.finish()  # pyright: ignore[reportUnknownMemberType]
        except Exception as err:
            print(err)
            self.clear()
            self.set_status(500)
            self.finish(  # pyright: ignore[reportUnknownMemberType]
                error_message(err),
            )

    def on_finish(self):
        if not self.done:
            try:
                if self.fh is not None:
                    self.fh.close()
            except:
                pass
            self.done = True

    def on_connection_close(self):
        self.on_finish()
        super().on_connection_close()


class AddLink(tornado.web.RequestHandler):
    def post(self):
        try:
            link = self.request.body.decode()
            if (
                spotify_scraper
                and youtube_search
                and (
                    link.startswith("spotify:track:")
                    or link.startswith("https://open.spotify.com/track/")
                )
            ):
                with spotify_scraper.SpotifyClient() as client:
                    spotify_track = client.get_track(link)
                    results = cast(
                        list[dict[str, Any]],
                        youtube_search.YoutubeSearch(
                            f"{', '.join(artist.name for artist in spotify_track.artists)} - {spotify_track.name}"
                        ).to_dict(),
                    )
                    if results and (youtube_id := results[0].get("id")):
                        link = f"https://youtu.be/{youtube_id}"
                    else:
                        raise Exception(
                            "Failed to find alternative link for Spotify track, sorry!"
                        )
            if not link.startswith("http://") and not link.startswith("https://"):
                raise Exception("Only web links, please")
            with yt_dlp.YoutubeDL(
                {
                    "cookiefile": "cookies.txt",
                    "quiet": True,
                    "format": "bestaudio/best",
                }
            ) as ydl:
                info_dict = ydl.extract_info(link, download=False)
                title = info_dict.get("title") or link
            assert juggler is not None
            juggler.juggle(
                {
                    "type": "link",
                    "upload_id": self.request.headers.get("Upload-Id"),
                    "nick": self.request.headers.get("Nick"),
                    "title": title,
                    "address": remote_ip(self.request),
                    "mrl": link,
                },
                self.request.headers.get("Parent-Id"),
            )
            self.finish()  # pyright: ignore[reportUnknownMemberType]
        except Exception as err:
            print(err)
            self.clear()
            self.set_status(500)
            self.finish(  # pyright: ignore[reportUnknownMemberType]
                error_message(err),
            )


class Download(tornado.web.RequestHandler):
    def get(self, track_id: str):
        try:
            assert juggler is not None
            info = juggler.download(track_id)
            if info is None:
                self.set_status(404)
                self.finish(  # pyright: ignore[reportUnknownMemberType]
                    "Not found",
                )
                return
            if info["type"] == "file":
                if info["filename"] is not None:
                    url_name = urllib.parse.quote(info["filename"])
                    self.add_header(
                        "Content-Disposition", 'attachment; filename="' + url_name + '"'
                    )
                with open(info["mrl"], "rb") as f:
                    chunk = f.read(1048576)
                    while chunk:
                        self.write(  # pyright: ignore[reportUnknownMemberType]
                            chunk,
                        )
                        chunk = f.read(1048576)
                self.finish()  # pyright: ignore[reportUnknownMemberType]
            elif info["type"] == "link":
                self.redirect(info["mrl"])
            else:
                raise Exception("Unknown type: " + info["type"])
        except Exception as err:
            print(err)
            self.clear()
            self.set_status(500)
            self.finish(  # pyright: ignore[reportUnknownMemberType]
                error_message(err),
            )


class WSHandler(tornado.websocket.WebSocketHandler):

    def open(self, *args: str, **kwargs: str):
        assert clients is not None
        assert juggler is not None
        clients.add_connection(self)
        self.write_message(
            json.dumps({"type": "address", "address": remote_ip(self.request)})
        )
        self.write_message(json.dumps(juggler.get_list()))

    def on_message(self, message: str | bytes):
        try:
            assert juggler is not None
            parsed_json = cast(dict[str, str], json.loads(message))
            assert isinstance(
                parsed_json, dict
            ), f"Expected dict, got {type(parsed_json).__name__}"
            match parsed_json.get("type"):
                case "skip":
                    juggler.cancel(
                        parsed_json.get("id", "ERR"), remote_ip(self.request)
                    )
                case other:
                    raise Exception(f"Unknown command: {other}")
        except Exception as err:
            print(err)
            self.write_message(
                json.dumps({"type": "error", "message": error_message(err)})
            )

    def on_close(self):
        assert clients is not None
        print("connection closed")
        clients.close_connection(self)


def start(
    port: int = 80,
    bind: str | None = None,
    player_args: player.PlayerArgs | None = None,
):
    global loop, clients, juggler, http_server
    loop = tornado.ioloop.IOLoop.current()

    clients = connections.Connections(loop)
    juggler = mp3Juggler.Juggler(clients, player_args)

    application = tornado.web.Application(
        [
            (r"/ws", WSHandler),
            (r"/", IndexHandler),
            (r"/add-file", AddFile),
            (r"/add-link", AddLink),
            (r"/download/(.*)", Download),
        ],
        # compiled_template_cache=False,  # Useful when editing index.html
        static_path=os.path.join(os.path.dirname(__file__), "static"),
    )

    http_server = tornado.httpserver.HTTPServer(
        application,
        max_body_size=1024 * 1024 * 1024,  # 1GiB
    )
    http_server.listen(port=port, address=bind)

    threading.Thread(target=loop.start).start()
    juggler.start()


def stop():
    if loop is not None:
        # Should use add_callback_from_signal according to documentation, but it's deprecated
        # on master (since 2023-05-02), and add_callback should have the same effect since 6.0.
        loop.add_callback(  # pyright: ignore[reportUnknownMemberType]
            lambda: loop.stop() if loop is not None else None
        )
    if http_server is not None:
        http_server.stop()
    if juggler is not None:
        juggler.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Musical democracy")
    parser.add_argument(
        "--proxied",
        action="store_true",
        help="Use X-Forwarded-For header instead of actual client IP to identify clients.",
    )
    parser.add_argument(
        "-b",
        "--bind",
        type=str,
        help="IP to run HTTP server on (default: any IP)",
        default=None,
    )
    if pychromecast:
        parser.add_argument(
            "-c",
            "--chromecast",
            type=str,
            help="Name of Chromecast (or Chromecast group) to cast to.",
            default=None,
        )
        parser.add_argument(
            "-C",
            "--chromecast-list",
            action="store_true",
            help="List available Chromecast (and Chromecast group) names and exit.",
        )
    parser.add_argument(
        "port",
        type=int,
        nargs="?",
        help="Port number to run HTTP server on (default 80)",
        default=80,
    )
    args = parser.parse_args()

    player_args: player.PlayerArgs = {}

    if pychromecast:
        if args.chromecast_list:
            print("Scanning for Chromecasts...")
            services, browser = pychromecast.discovery.discover_chromecasts()
            pychromecast.discovery.stop_discovery(browser)
            if services:
                print("Available Chromecast targets:")
                for service in services:
                    print('* "%s"' % service.friendly_name)
            else:
                print("No Chromecast targets found.")
            exit(0)

        if args.chromecast is not None:
            services, browser = pychromecast.discovery.discover_listed_chromecasts(
                friendly_names=[args.chromecast]
            )
            pychromecast.discovery.stop_discovery(browser)
            if len(services) < 1:
                print('Could not find Chromecast (or group) "%s"' % args.chromecast)
                exit(1)
            elif len(services) > 1:
                print(
                    'More than one Chromecast (or group) matched "%s"' % args.chromecast
                )
                exit(1)

            player_args["chromecast"] = (services[0].host, services[0].port)

    if args.proxied:
        remote_ip = forwarded_remote_ip

    def signal_handler(sig: int, _: Any):
        print(f"\nSignal {sig} caught, exiting...")
        stop()
        exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        start(args.port, args.bind, player_args)
        print("*** Web Server Started on %s:%s***" % (args.bind or "*", args.port))
    except Exception as err:
        print("Error starting web server:", err)
        exit(1)

    # Start console
    while True:
        match input():
            case "s" | "skip":
                if juggler is not None:
                    print("Skipping...")
                    juggler.skip()
            case "c" | "clear":
                if juggler is not None:
                    print("Clearing...")
                    juggler.clear()
            case "p" | "play" | "pause":
                if juggler is not None:
                    print("Toggling pause...")
                    juggler.pause()
            case other:
                print(f"Unknown command '{other}'")
