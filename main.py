import os
import uuid
import tornado.httpserver
import tornado.websocket
import tornado.ioloop
import tornado.web
import socket
import json
import connections
from mp3Juggler import mp3Juggler

clients = connections.Connections()
juggler = mp3Juggler(clients)
__UPLOADS__ = "static/songs/"
class IndexHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(request):
        request.render("index.html")

class Upload(tornado.web.RequestHandler):
    def post(self):
        filename = self.request.headers.get('Filename')
        extn = os.path.splitext(filename)[1]
        infile = {'nick':self.request.headers.get('nick'),
        'filename':filename,
        'address':self.request.remote_ip,
        'path':__UPLOADS__ + str(uuid.uuid4()) + extn}
        fh = open(infile['path'], 'wb')
        fh.write(self.request.body)
        self.finish()
        juggler.juggle(infile)

class WSHandler(tornado.websocket.WebSocketHandler):

    def open(self):
        clients.add_conneciton(self)
        self.write_message(json.dumps(juggler.get_list()))

    # def on_message(self, message):
        # parsed_json = json.loads(message)
        # parsed_json['path'] = __UPLOADS__+parsed_json['filename']
        # juggler.juggle(parsed_json)

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
