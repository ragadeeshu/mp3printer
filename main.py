import os
import re
import signal
import tempfile
import threading
import tornado.httpserver
import tornado.websocket
import tornado.ioloop
import tornado.web
import socket
import json
import yt_dlp
import argparse
import urllib.parse


# optional lib
try:
    import pychromecast.discovery
    HAS_PYCHROMECAST = True
except ModuleNotFoundError:
    HAS_PYCHROMECAST = False

# local libs
from connections import Connections
from mp3Juggler import mp3Juggler

loop = None
clients = None
juggler = None
http_server = None

ANSI_ESCAPE = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]')
ERROR_PREFIX = re.compile(r'^[Ee][Rr][Rr]([Oo][Rr])?:\s*')

def error_message(err):
    return ERROR_PREFIX.sub('', ANSI_ESCAPE.sub('', str(err)))

def actual_remote_ip(request):
    return request.remote_ip
def forwarded_remote_ip(request):
    return request.headers.get('X-Forwarded-For')
remote_ip = actual_remote_ip

class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.render("index.html")

class Upload(tornado.web.RequestHandler):
    def post(self):
        try:
            filename = self.request.headers.get('Filename')
            extn = os.path.splitext(filename)[-1]
            fd, cachename = tempfile.mkstemp(suffix=extn)
            infile = {
                'type': 'file',
                'upload_id': self.request.headers.get('Upload-Id'),
                'nick': self.request.headers.get('Nick'),
                'filename': filename,
                'extn': extn,
                'address': remote_ip(self.request),
                'mrl': cachename,
                'path': cachename
            }
            with os.fdopen(fd, 'wb') as fh:
                fh.write(self.request.body)
            juggler.juggle(infile, self.request.headers.get('Parent-Id'))
            self.finish()
        except Exception as err:
            self.clear()
            self.set_status(500)
            self.finish(error_message(err))

class Download(tornado.web.RequestHandler):
    def get(self, track_id):
        try:
            infile = juggler.download(track_id)
            if infile is None:
                self.set_status(404)
                self.finish("Not found")
                return
            if infile['type'] == 'file':
                url_name = urllib.parse.quote(infile['filename'])
                self.add_header('Content-Disposition',
                    'attachment; filename="'+url_name+'"')
                with open(infile['mrl'], 'rb') as f:
                    chunk = f.read(1048576)
                    while chunk:
                        self.write(chunk)
                        chunk = f.read(1048576)
                self.finish()
            elif infile['type'] == 'link':
                self.redirect(infile['mrl'])
            else:
                raise Exception('Unknown type: '+infile['type'])
        except Exception as err:
            print(err)
            self.clear()
            self.set_status(500)
            self.finish(error_message(err))

class WSHandler(tornado.websocket.WebSocketHandler):

    def open(self):
        clients.add_connection(self)
        self.write_message(json.dumps({
            'type': 'address',
            'address': remote_ip(self.request)
        }))
        self.write_message(json.dumps(juggler.get_list()))

    def on_message(self, message):
        try:
            parsed_json = json.loads(message)
            if parsed_json['type'] == "link":
                ydl_opts = {
                    'quiet': True,
                    'format': 'bestaudio/best'
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(parsed_json['link'], download=False)
                    title = info_dict.get('title', None)
                infile = {
                    'type': 'link',
                    'upload_id': parsed_json['id'],
                    'nick': parsed_json['nick'],
                    'filename': title,
                    'address': remote_ip(self.request),
                    'mrl': parsed_json['link']
                }
                parent = parsed_json['parent'] if 'parent' in parsed_json else None
                juggler.juggle(infile, parent)
            elif parsed_json['type'] == "skip":
                infile = {
                    'address': remote_ip(self.request),
                    'id': parsed_json['id']
                }
                juggler.cancel(infile)
            else:
                raise Exception('Unknown command: '+parsed_json['type'])
        except Exception as err:
            print(err)
            self.write_message(json.dumps({
                'type': 'error',
                'message': error_message(err)
            }))


    def on_close(self):
        print('connection closed')
        clients.close_connection(self)

def start(port=80, bind=None, player_args=None):
    global loop, clients, juggler, http_server
    loop = tornado.ioloop.IOLoop.current()

    clients = Connections(loop)
    juggler = mp3Juggler(clients, player_args)

    application = tornado.web.Application(
        [
            (r'/ws', WSHandler),
            (r'/', IndexHandler),
            (r"/upload", Upload),
            (r"/download/(.*)", Download),
        ],
        #compiled_template_cache=False,  # Useful when editing index.html
        static_path=os.path.join(os.path.dirname(__file__), "static")
    )

    http_server = tornado.httpserver.HTTPServer(application, max_buffer_size=150*1024*1024)
    http_server.listen(port=port, address=bind)

    threading.Thread(target=loop.start).start()
    juggler.start()

def stop():
    if loop is not None:
        # Should use add_callback_from_signal according to documentation, but it's deprecated
        # on master (since 2023-05-02), and add_callback should have the same effect since 6.0.
        loop.add_callback(lambda: loop.stop())
    if http_server is not None:
        http_server.stop()
    if juggler is not None:
        juggler.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Musical democracy'
    )
    parser.add_argument(
        '--proxied',
        action='store_true',
        help='Use X-Forwarded-For header instead of actual client IP to identify clients.'
    )
    parser.add_argument(
        '-b', '--bind',
        type=str,
        help='IP to run HTTP server on (default: any IP)',
        default=None
    )
    if HAS_PYCHROMECAST:
        parser.add_argument(
            '-c', '--chromecast',
            type=str,
            help='Name of Chromecast (or Chromecast group) to cast to.',
            default=None
        )
        parser.add_argument(
            '-C', '--chromecast-list',
            action='store_true',
            help='List available Chromecast (and Chromecast group) names and exit.'
        )
    parser.add_argument(
        'port',
        type=int,
        nargs='?',
        help='Port number to run HTTP server on (default 80)',
        default=80
    )
    args = parser.parse_args()

    player_args = {}

    if HAS_PYCHROMECAST:
        if args.chromecast_list:
            print('Available Chromecast targets:')
            services, browser = pychromecast.discovery.discover_chromecasts()
            pychromecast.discovery.stop_discovery(browser)
            for service in services:
                print('* \"%s\"' % service.friendly_name)
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
                print('More than one Chromecast (or group) matched "%s"' % args.chromecast)
                exit(1)

            player_args['chromecast'] = (services[0].host, services[0].port)

    if args.proxied:
        remote_ip = forwarded_remote_ip

    def signal_handler(sig, frame):
        print("\nSignal caught, exiting...")
        stop()
        exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        start(args.port, args.bind, player_args)
        print('*** Web Server Started on %s:%s***' % (
            args.bind or '*',
            args.port
        ))
    except Exception as err:
        print('Error starting web server:', err)
        exit(1)


    # Start console
    while True:
        inp = input()
        if (inp == "s"):
            print("Skipping...")
            juggler.skip()
        elif (inp == "c"):
            print("Clearing...")
            juggler.clear()
        elif (inp == "p"):
            print("Toggling pause...")
            juggler.pause()
