import os
import re
import signal
import tempfile
import threading
import tornado.httpserver
import tornado.websocket
import tornado.ioloop
import tornado.web
import asyncio
import socket
import json
import connections
import yt_dlp
import urllib.parse

from tornado.platform.asyncio import AnyThreadEventLoopPolicy
from mp3Juggler import mp3Juggler

ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]')
error_prefix = re.compile(r'^[Ee][Rr][Rr]([Oo][Rr])?:\s*')

def error_message(err):
    return error_prefix.sub('', ansi_escape.sub('', str(err)))

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
                'address': self.request.remote_ip,
                'path': cachename,
                'mrl': cachename
            }
            with os.fdopen(fd, 'wb') as fh:
                fh.write(self.request.body)
            juggle_args = (infile, self.request.headers.get('Parent-Id'))
            threading.Thread(target=juggler.juggle, args=juggle_args).start()
            self.finish()
        except Exception as err:
            self.clear()
            self.set_status(500)
            self.finish(error_message(err))

class Download(tornado.web.RequestHandler):
    def get(self):
        try:
            infile = juggler.download(self.get_argument('id'))
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
                raise 'Unknown type: '+infile['type']
        except Exception as err:
            print(err)
            self.clear()
            self.set_status(500)
            self.finish(error_message(err))

class WSHandler(tornado.websocket.WebSocketHandler):

    def open(self):
        clients.add_connection(self)
        self.write_message(json.dumps(juggler.get_list()))

    def on_message(self, message):
        try:
            parsed_json = json.loads(message)
            if parsed_json['type'] == "link":
                ydl_opts = {
                    'quiet': "True",
                    'format': 'bestaudio/best'
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(parsed_json['link'], download=False)
                    video_title = info_dict.get('title', None)
                    url = info_dict.get("url", None)
                infile = {
                    'type': 'link',
                    'upload_id': parsed_json['id'],
                    'nick': parsed_json['nick'],
                    'filename': video_title,
                    'address': self.request.remote_ip,
                    'mrl': parsed_json['link'],
                    'path': url
                }
                parent = parsed_json['parent'] if 'parent' in parsed_json else None
                juggle_args = (infile, parent)
                threading.Thread(target=juggler.juggle, args=juggle_args).start()
            elif parsed_json['type'] == "skip":
                infile = {
                    'address': self.request.remote_ip,
                    'id': parsed_json['id']
                }
                juggler.cancel(infile)
            else:
                raise 'Unknown command: '+parsed_json['type']
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
    loop = tornado.ioloop.IOLoop.current()
    threading.Thread(target=loop.start).start()

    clients = connections.Connections(loop)
    juggler = mp3Juggler(clients)

    application = tornado.web.Application([
        (r'/ws', WSHandler),
        (r'/', IndexHandler),
        (r"/upload", Upload),
        (r"/download", Download),
    ], static_path=os.path.join(os.path.dirname(__file__), "static"))

    http_server = tornado.httpserver.HTTPServer(application, max_buffer_size=150*1024*1024)
    http_server.listen(80)
    myIP = socket.gethostbyname(socket.gethostname())
    print('*** Websocket Server Started at %s***' % myIP)

    def signal_handler(sig, frame):
        print("\nSignal caught, exiting...")
        loop.add_callback_from_signal(lambda: loop.stop())
        http_server.stop()
        juggler.stop()
        exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start console
    while True:
        inp = input()
        if (inp == "s"):
            print("Skipping...")
            juggler.skip()
        elif (inp == "c"):
            print("Clearing...")
            juggler.clear()
