import monkey  # noqa: F401
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

    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting WebSocket server on port {port}...")

    try:
        server = WSGIServer(
            ('0.0.0.0', port),
            app,
            handler_class=WebSocketHandler,
            log=logger
        )
        logger.info("Server initialized, starting to serve...")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise