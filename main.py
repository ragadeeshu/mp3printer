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
class IndexHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(request):
        request.render("index.html")

class WSHandler(tornado.websocket.WebSocketHandler):


    def open(self):
        clients.add_conneciton(self)
        # print('new connection')
        self.write_message(json.dumps(juggler.get_list()))

    def on_message(self, message):
        parsed_json = json.loads(message)
        # print(parsed_json.keys())
        parsed_json['file'] = base64.b64decode(parsed_json['file'])
        parsed_json['path'] = "static/songs/"+parsed_json['filename']
        with open(parsed_json['path'], "wb") as text_file:
            text_file.write(parsed_json.pop('file', None))  #this just writes the ASCII for the string

        juggler.juggle(parsed_json)

    def on_close(self):
        print('connection closed')
        clients.close_connection(self)

    # def check_origin(self, origin):
    #     return True

settings = {
    "static_path": os.path.join(os.path.dirname(__file__), "static"),
    # "cookie_secret": "__TODO:_GENERATE_YOUR_OWN_RANDOM_VALUE_HERE__",
    # "login_url": "/login",
    # "xsrf_cookies": True,
}

application = tornado.web.Application([
    (r'/ws', WSHandler), (r'/', IndexHandler)
], **settings)


if __name__ == "__main__":
    http_server = tornado.httpserver.HTTPServer(application)
    http_server.listen(8888)
    myIP = socket.gethostbyname(socket.gethostname())
    print('*** Websocket Server Started at %s***' % myIP)
    tornado.ioloop.IOLoop.instance().start()
