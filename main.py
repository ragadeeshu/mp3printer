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

# local libs
from connections import Connections
from mp3Juggler import mp3Juggler

ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]')
error_prefix = re.compile(r'^[Ee][Rr][Rr]([Oo][Rr])?:\s*')

def error_message(err):
    return error_prefix.sub('', ansi_escape.sub('', str(err)))

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
    parser.add_argument(
        'port',
        type=int,
        nargs='?',
        help='Port number to run HTTP server on (default 80)',
        default=80
    )
    args = parser.parse_args()
    if args.proxied:
        remote_ip = forwarded_remote_ip

    loop = tornado.ioloop.IOLoop.current()

    clients = Connections(loop)
    juggler = mp3Juggler(clients)

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

    try:
        http_server = tornado.httpserver.HTTPServer(application, max_buffer_size=150*1024*1024)
        http_server.listen(port=args.port, address=args.bind)
        print('*** Web Server Started on %s:%s***' % (args.bind or '*', args.port))
    except Exception as err:
        print('Error starting web server:', err)
        exit(1)

    def signal_handler(sig, frame):
        print("\nSignal caught, exiting...")
        loop.add_callback_from_signal(lambda: loop.stop())
        http_server.stop()
        juggler.stop()
        exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    threading.Thread(target=loop.start).start()
    juggler.start()

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
