from gevent import monkey
monkey.patch_all()

import os
import logging
from gevent.pywsgi import WSGIServer
from geventwebsocket.handler import WebSocketHandler
from app import app

if __name__ == "__main__":
    # Configure detailed logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

    logger.info("Starting WebSocket server...")

    # Create server with proper WebSocket handler
    server = WSGIServer(
        ('0.0.0.0', 5000),
        app,
        handler_class=WebSocketHandler,
        log=logger
    )

    logger.info("WebSocket server is running on port 5000")
    server.serve_forever()