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

# Configure CORS to allow WebSocket connections
CORS(app)

# Initialize database
init_db(app)

# Initialize Sockets
sockets = Sockets(app)

# Import routes after app is initialized
from websocket_handler import handle_websocket  # noqa: E402

# WebSocket route
@sockets.route('/stream')
def stream_socket(ws: WebSocket):
    """Handle WebSocket connections"""
    if not ws:
        logger.error("No WebSocket connection available")
        return

    try:
        logger.info("New WebSocket connection started")
        handle_websocket(ws)
    except Exception as e:
        logger.error(f"Error in WebSocket connection: {str(e)}")
        if not ws.closed:
            ws.close()

# Web interface route
@app.route('/')
def index():
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