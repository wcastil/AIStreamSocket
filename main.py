from gevent import monkey
monkey.patch_all()

import os
import logging
from gevent.pywsgi import WSGIServer
from app import app

if __name__ == "__main__":
    # Configure detailed logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger(__name__)

    try:
        # Get port from environment variable (Replit sets this)
        port = int(os.environ.get('PORT', 8080))
        logger.info(f"Starting server on port {port} with host 0.0.0.0")

        # Create and run the WSGI server
        http_server = WSGIServer(('0.0.0.0', port), app)
        logger.info("Server initialized, starting to serve requests...")
        http_server.serve_forever()

    except Exception as e:
        logger.error(f"Failed to start server: {str(e)}", exc_info=True)
        raise