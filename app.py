import os
import logging
from flask import Flask, render_template
from flask_sockets import Sockets
from database import init_db
from geventwebsocket.websocket import WebSocket
from flask_cors import CORS

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
        "expose_headers": ["Content-Type"],
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
    if not ws or not isinstance(ws, WebSocket):
        logger.error("Invalid WebSocket connection")
        return

    try:
        logger.info("New WebSocket connection started")
        handle_websocket(ws)
    except Exception as e:
        logger.error(f"Error in WebSocket connection: {str(e)}")
    finally:
        if ws and not ws.closed:
            try:
                ws.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket: {str(e)}")

# Web interface route
@app.route('/')
def index():
    """Render the chat interface"""
    return render_template('index.html')

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    logger.error(f"404 error: {error}")
    return "Page not found", 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {error}")
    return "Internal server error", 500