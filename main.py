import os
import base64
import tornado.httpserver
import tornado.websocket
import tornado.ioloop
import tornado.web
import socket
import json
import connections
from mp3Juggler import mp3Juggler
'''
This is a simple Websocket Echo server that uses the Tornado websocket handler.
Please run `pip install tornado` with python of version 2.7.9 or greater to install tornado.
This program will echo back the reverse of whatever it recieves.
Messages are output to the terminal for debuggin purposes.
'''
clients = connections.Connections()
juggler = mp3Juggler(clients)
__UPLOADS__ = "static/songs/"
class IndexHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(request):
        request.render("index.html")

class Upload(tornado.web.RequestHandler):
    def post(self):
        fh = open(__UPLOADS__ + self.request.headers.get('Filename'), 'wb')
        fh.write(self.request.body)
        self.finish()

class WSHandler(tornado.websocket.WebSocketHandler):

    def open(self):
        clients.add_conneciton(self)
        self.write_message(json.dumps(juggler.get_list()))

    def on_message(self, message):
        parsed_json = json.loads(message)
        parsed_json['path'] = __UPLOADS__+parsed_json['filename']
        juggler.juggle(parsed_json)

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
    http_server = tornado.httpserver.HTTPServer(application)
    http_server.listen(80)
    myIP = socket.gethostbyname(socket.gethostname())
    print('*** Websocket Server Started at %s***' % myIP)
    tornado.ioloop.IOLoop.instance().start()
