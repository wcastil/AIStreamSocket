import json
import logging
import gevent
from database import db
from models import Conversation, Message
from openai_assistant import OpenAIAssistant

logger = logging.getLogger(__name__)

def handle_websocket(ws):
    """Handle WebSocket connections and messages."""
    try:
        if ws.closed:
            logger.error("WebSocket connection is already closed")
            return

        logger.info("Initializing new WebSocket connection")
        assistant = OpenAIAssistant()

        # Create a new conversation for this WebSocket connection
        conversation = Conversation()
        db.session.add(conversation)
        db.session.commit()
        logger.info(f"Created new conversation with ID: {conversation.id}")

        # Start ping-pong to keep connection alive
        def ping():
            while not ws.closed:
                try:
                    ws.send_frame('', ws.OPCODE_PING)
                    gevent.sleep(15)  # Send ping every 15 seconds
                except Exception as e:
                    logger.error(f"Error sending ping: {e}")
                    break

        gevent.spawn(ping)

        while not ws.closed:
            try:
                # Set a longer timeout for receiving messages
                message = ws.receive(timeout=30)

                if message is None:
                    logger.debug("Received heartbeat/ping")
                    continue

                try:
                    data = json.loads(message)
                    user_message = data.get('message')

                    if not user_message:
                        logger.warning("Received message without content")
                        ws.send(json.dumps({
                            "error": "Message field is required"
                        }))
                        continue

                    logger.info(f"Processing user message: {user_message[:50]}...")

                    # Store user message in database
                    db_message = Message(
                        conversation_id=conversation.id,
                        role='user',
                        content=user_message
                    )
                    db.session.add(db_message)
                    db.session.commit()

                    # Stream the response from OpenAI
                    full_response = ""
                    for response_chunk in assistant.stream_response(user_message):
                        if ws.closed:
                            logger.warning("WebSocket closed during response streaming")
                            break
                        full_response += response_chunk
                        ws.send(json.dumps({
                            "chunk": response_chunk,
                            "done": False
                        }))

                    if not ws.closed and full_response:
                        # Store assistant's response in database
                        assistant_message = Message(
                            conversation_id=conversation.id,
                            role='assistant',
                            content=full_response.strip()
                        )
                        db.session.add(assistant_message)
                        db.session.commit()

                        # Send completion message
                        ws.send(json.dumps({
                            "chunk": "",
                            "done": True
                        }))

                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON message: {str(e)}")
                    if not ws.closed:
                        ws.send(json.dumps({
                            "error": "Invalid JSON message"
                        }))
                except Exception as e:
                    logger.error(f"Error processing message: {str(e)}")
                    if not ws.closed:
                        ws.send(json.dumps({
                            "error": f"Error processing message: {str(e)}"
                        }))

            except Exception as e:
                if "timed out" in str(e).lower():
                    continue  # This is normal for ping/pong
                logger.error(f"Error in message loop: {str(e)}")
                if not ws.closed:
                    try:
                        ws.send(json.dumps({
                            "error": "Internal server error"
                        }))
                    except:
                        pass
                break

    except Exception as e:
        logger.error(f"WebSocket handler error: {str(e)}")
    finally:
        logger.info("WebSocket connection closed")
        if not ws.closed:
            try:
                ws.close()
            except:
                pass