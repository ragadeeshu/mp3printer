import os
import re
import uuid
import _thread
import tempfile
import tornado.httpserver
import tornado.websocket
import tornado.ioloop
import tornado.web
import asyncio
import socket
import json
import connections
import yt_dlp

from tornado.platform.asyncio import AnyThreadEventLoopPolicy
from mp3Juggler import mp3Juggler

clients = connections.Connections()
juggler = mp3Juggler(clients)

ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]')
error_prefix = re.compile(r'^[Ee][Rr][Rr]([Oo][Rr])?:\s*')

def skipper ():
    while True:
        if (input() == "s"):
            print("Skipping...")
            juggler.skip()

def error_message(err):
    return error_prefix.sub('', ansi_escape.sub('', str(err)))


class IndexHandler(tornado.web.RequestHandler):
    def get(request):
        request.render("index.html")

class Upload(tornado.web.RequestHandler):
    def post(self):
        try:
            filename = self.request.headers.get('Filename')
            extn = os.path.splitext(filename)[-1]
            fd, cachename = tempfile.mkstemp(suffix=extn)
            infile = {'nick':self.request.headers.get('nick'),
            'filename':filename,
            'address':self.request.remote_ip,
            'path':cachename,
            'mrl':cachename}
            with os.fdopen(fd, 'wb') as fh:
                fh.write(self.request.body)
            self.finish()
            juggler.juggle(infile)
        except Exception as err:
            self.clear()
            self.set_status(500)
            self.finish(error_message(err))

class WSHandler(tornado.websocket.WebSocketHandler):

    def open(self):
        clients.add_conneciton(self)
        self.write_message(json.dumps(juggler.get_list()))

    def on_message(self, message):
        try:
            parsed_json = json.loads(message)
            if parsed_json['type'] == "link":
                ydl_opts = {
                'quiet': "True",
                'format': 'bestaudio/best'}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(parsed_json['link'], download=False)
                    video_title = info_dict.get('title', None)
                    url = info_dict.get("url", None)
                infile = {'nick':parsed_json['nick'],
                'filename':video_title,
                'address':self.request.remote_ip,
                'mrl':parsed_json['link'],
                'path':url}
                juggler.juggle(infile)
            else:
                infile = {
                    'address':self.request.remote_ip,
                    'mrl':parsed_json['mrl']
                }
                juggler.cancel(infile)
        except Exception as err:
            self.write_message(json.dumps({
                'type': 'error',
                'message': error_message(err)
            }))


    def on_close(self):
        print('connection closed')
        clients.close_connection(self)

settings = {
    "static_path": os.path.join(os.path.dirname(__file__), "static"),
}

application = tornado.web.Application([
    (r'/ws', WSHandler), (r'/', IndexHandler), (r"/upload", Upload),
], **settings)


if __name__ == "__main__":
    asyncio.set_event_loop_policy(AnyThreadEventLoopPolicy())
    _thread.start_new_thread(skipper, ())
    http_server = tornado.httpserver.HTTPServer(application)
    http_server.listen(80)
    myIP = socket.gethostbyname(socket.gethostname())
    print('*** Websocket Server Started at %s***' % myIP)
    tornado.ioloop.IOLoop.instance().start()
