from app import app
from gevent import pywsgi
from geventwebsocket.handler import WebSocketHandler

if __name__ == "__main__":
    server = pywsgi.WSGIServer(
        ('0.0.0.0', 5000),
        app,
        handler_class=WebSocketHandler
    )
    print("WebSocket server is running on port 5000")
    server.serve_forever()