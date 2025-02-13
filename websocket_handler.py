import json
import logging
from openai_assistant import OpenAIAssistant

logger = logging.getLogger(__name__)

def handle_websocket(ws):
    """Handle WebSocket connections and messages."""
    logger.info("New WebSocket connection established")
    assistant = OpenAIAssistant()

    try:
        while not ws.closed:
            message = ws.receive()
            
            if message is None:
                continue

            try:
                data = json.loads(message)
                user_message = data.get('message')
                
                if not user_message:
                    ws.send(json.dumps({
                        "error": "Message field is required"
                    }))
                    continue

                # Stream the response from OpenAI
                for response_chunk in assistant.stream_response(user_message):
                    if ws.closed:
                        break
                    ws.send(json.dumps({
                        "chunk": response_chunk,
                        "done": False
                    }))

                # Send completion message
                if not ws.closed:
                    ws.send(json.dumps({
                        "chunk": "",
                        "done": True
                    }))

            except json.JSONDecodeError:
                ws.send(json.dumps({
                    "error": "Invalid JSON message"
                }))
            except Exception as e:
                logger.error(f"Error processing message: {str(e)}")
                ws.send(json.dumps({
                    "error": f"Error processing message: {str(e)}"
                }))

    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        logger.info("WebSocket connection closed")
