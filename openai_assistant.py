import os
import logging
import json
from openai import OpenAI
from models import InterviewData, Message, Conversation
from database import db
import time

logger = logging.getLogger(__name__)

class OpenAIAssistant:
    def __init__(self):
        try:
            self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            self.assistant_id = os.environ.get("OPENAI_ASSISTANT_ID")

            if not self.assistant_id:
                raise ValueError("OPENAI_ASSISTANT_ID environment variable is required")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {str(e)}", exc_info=True)
            raise

    def stream_response(self, user_message, thread_id=None, conversation_id=None):
        """Stream responses from the OpenAI Assistant API with conversation tracking"""
        try:
            # Create a new thread if none provided
            try:
                thread = self.client.beta.threads.create() if not thread_id else None
                thread_id = thread.id if thread else thread_id
                logger.info(f"Processing message in thread {thread_id}")
            except Exception as e:
                logger.error(f"Error creating thread: {str(e)}", exc_info=True)
                yield f"Error creating conversation thread: {str(e)}"
                return

            # Store user message in database
            try:
                if conversation_id:
                    message = Message(
                        conversation_id=conversation_id,
                        role='user',
                        content=user_message
                    )
                    db.session.add(message)
                    db.session.commit()
                    logger.debug(f"🔹 Stored user message in conversation {conversation_id}:\n{user_message}")
            except Exception as e:
                logger.error(f"Error storing user message: {str(e)}", exc_info=True)

            # Add the user message to the thread
            try:
                self.client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=user_message
                )
            except Exception as e:
                logger.error(f"Error adding message to thread: {str(e)}", exc_info=True)
                yield f"Error adding message to conversation: {str(e)}"
                return

            # Run the assistant
            try:
                logger.info("Starting assistant run")
                run = self.client.beta.threads.runs.create(
                    thread_id=thread_id,
                    assistant_id=self.assistant_id
                )
            except Exception as e:
                logger.error(f"Error starting assistant run: {str(e)}", exc_info=True)
                yield f"Error starting conversation: {str(e)}"
                return

            # Poll for response and stream it
            max_retries = 3
            retry_count = 0

            while True:
                try:
                    run_status = self.client.beta.threads.runs.retrieve(
                        thread_id=thread_id,
                        run_id=run.id
                    )

                    if run_status.status == 'completed':
                        messages = self.client.beta.threads.messages.list(
                            thread_id=thread_id
                        )

                        # Get the latest assistant message
                        for msg in messages.data:
                            if msg.role == "assistant":
                                try:
                                    content = msg.content[0].text.value if hasattr(msg.content[0], 'text') else str(msg.content[0])

                                    # Store assistant message in database
                                    if conversation_id:
                                        message = Message(
                                            conversation_id=conversation_id,
                                            role='assistant',
                                            content=content
                                        )
                                        db.session.add(message)
                                        db.session.commit()
                                        logger.debug(f"🔹 Stored assistant response in conversation {conversation_id}:\n{content[:200]}...")

                                    logger.info(f"Assistant response: {content[:100]}...")
                                    yield content
                                except Exception as e:
                                    error_msg = f"Error processing message: {str(e)}"
                                    logger.error(error_msg, exc_info=True)
                                    yield error_msg
                                break
                        break

                    elif run_status.status in ['failed', 'cancelled', 'expired']:
                        error_msg = f"Assistant run failed with status: {run_status.status}"
                        logger.error(error_msg)
                        yield error_msg
                        break

                    time.sleep(0.5)

                except Exception as e:
                    logger.error(f"Error checking run status: {str(e)}", exc_info=True)
                    retry_count += 1

                    if retry_count >= max_retries:
                        error_msg = f"Max retries reached, failed to get response: {str(e)}"
                        logger.error(error_msg)
                        yield error_msg
                        break

                    time.sleep(1)

        except Exception as e:
            error_msg = f"Error in OpenAI Assistant: {str(e)}"
            logger.error(error_msg, exc_info=True)
            yield error_msg

    def evaluate_interview_progress(self, conversation_id):
        """
        Evaluate the full interview session asynchronously
        Returns missing information and suggested follow-up questions
        """
        try:
            # Retrieve all messages for this conversation
            conversation = Conversation.query.get(conversation_id)
            if not conversation:
                raise ValueError(f"Conversation {conversation_id} not found")

            messages = Message.query.filter_by(conversation_id=conversation_id).order_by(Message.created_at).all()

            # Format conversation history
            conversation_history = []
            for msg in messages:
                logger.debug(f"🔹 Processing message: {msg.role} - {msg.content[:100]}...")
                conversation_history.append({
                    "role": msg.role,
                    "content": msg.content
                })

            logger.info(f"🔹 Evaluating interview progress for conversation {conversation_id}")
            logger.debug(f"🔹 Sending {len(conversation_history)} messages for evaluation")

            # Generate system message for evaluation
            system_message = """Analyze the interview conversation and identify:
            1. Key insights and patterns
            2. Missing or incomplete information
            3. Suggested follow-up questions
            4. Areas that need clarification

            Respond with a concise summary and specific recommendations."""

            # Request evaluation from OpenAI
            response = self.client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_message},
                    *conversation_history
                ]
            )

            evaluation = response.choices[0].message.content
            logger.info("🔹 Interview evaluation completed successfully")

            return evaluation

        except Exception as e:
            error_msg = f"Error evaluating interview progress: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return error_msg