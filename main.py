from gevent import monkey
monkey.patch_all(thread=False)

import os
import logging
import signal
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
        port = int(os.environ.get('PORT', 5000))
        logger.info(f"Starting Flask development server on port {port}")

        # Run the Flask development server with gevent
        from gevent.pywsgi import WSGIServer

        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}. Performing graceful shutdown...")
            http_server.stop(timeout=5)
            logger.info("Server stopped gracefully")

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        http_server = WSGIServer(('0.0.0.0', port), app, log=logger)
        logger.info("Server initialization complete, starting WSGI server")
        http_server.serve_forever()

    except Exception as e:
        logger.error(f"Failed to start server: {str(e)}", exc_info=True)
        raise