import os
import logging
from flask import Flask, render_template
from flask_sockets import Sockets
from geventwebsocket.websocket import WebSocket
from flask_cors import CORS
from database import init_db

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Flask and extensions
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")

# Initialize Flask-Sockets
sockets = Sockets(app)

# Configure CORS with WebSocket support
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "allow_headers": [
            "Content-Type",
            "Sec-WebSocket-Extensions",
            "Sec-WebSocket-Key",
            "Sec-WebSocket-Version",
            "Sec-WebSocket-Protocol"
        ],
        "expose_headers": [
            "Content-Type",
            "Sec-WebSocket-Accept"
        ],
        "supports_credentials": True
    }
})

# Initialize database
init_db(app)

# Import routes after app is initialized
from websocket_handler import handle_websocket  # noqa: E402

# WebSocket route
@sockets.route('/stream')
def stream_socket(ws):
    """Handle WebSocket connections"""
    try:
        if not ws or not isinstance(ws, WebSocket):
            logger.error("Invalid WebSocket connection")
            return

        logger.debug("WebSocket connection attempt from %s", ws.origin or 'Unknown')
        if ws.closed:
            logger.error("WebSocket is already closed")
            return

        handle_websocket(ws)
    except Exception as e:
        logger.error("WebSocket handler error: %s", str(e))
    finally:
        if ws and not ws.closed:
            try:
                ws.close()
            except Exception as e:
                logger.error("Error closing WebSocket: %s", str(e))

# Web interface route
@app.route('/')
def index():
    """Render the chat interface"""
    return render_template('index.html')

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    logger.error("404 error: %s", error)
    return "Page not found", 404

@app.errorhandler(500)
def internal_error(error):
    logger.error("500 error: %s", error)
    return "Internal server error", 500