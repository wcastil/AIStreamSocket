import os
import logging
from flask import Flask, render_template, request
from geventwebsocket.websocket import WebSocket
from flask_cors import CORS
from database import init_db

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Flask
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")

# Configure CORS with WebSocket support
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "allow_headers": [
            "Content-Type",
            "Authorization",
            "Upgrade",
            "Connection",
            "Sec-WebSocket-Key",
            "Sec-WebSocket-Version",
            "Sec-WebSocket-Extensions"
        ],
        "expose_headers": [
            "Upgrade",
            "Connection",
            "Sec-WebSocket-Accept"
        ]
    }
})

# Initialize database
init_db(app)

# Import routes after app is initialized
from websocket_handler import handle_websocket  # noqa: E402

@app.route('/stream')
def stream_socket():
    """WebSocket endpoint"""
    logger.debug("New WebSocket connection request")
    if 'wsgi.websocket' not in request.environ:
        logger.error("Not a WebSocket request")
        return 'WebSocket connection required', 400

    ws = request.environ['wsgi.websocket']
    if not ws:
        logger.error("Could not create WebSocket connection")
        return 'Could not create WebSocket connection', 400

    try:
        logger.info("WebSocket connection established")
        handle_websocket(ws)
    except Exception as e:
        logger.error("WebSocket error: %s", str(e))
    finally:
        if not ws.closed:
            ws.close()
    return ''

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