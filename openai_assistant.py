import os
import logging
import json
from openai import OpenAI
from models import InterviewData, Message, Conversation, PersonModel
from database import db
import time
from flask import current_app

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

    def get_or_create_conversation(self, session_id=None):
        """Get existing conversation or create a new one"""
        try:
            with current_app.app_context():
                if session_id:
                    # First try to find an existing conversation with this session ID
                    conversation = Conversation.query.filter_by(session_id=session_id).first()
                    if conversation:
                        logger.info(f"Retrieved existing conversation for session {session_id}")
                        return conversation

                # Create new conversation with the session ID
                conversation = Conversation(session_id=session_id)
                db.session.add(conversation)
                db.session.commit()

                # Refresh the conversation object to ensure it's bound to the session
                db.session.refresh(conversation)

                logger.info(f"Created new conversation with session ID: {session_id}")
                return conversation
        except Exception as e:
            logger.error(f"Error in get_or_create_conversation: {str(e)}", exc_info=True)
            raise

    def get_conversation_history(self, conversation_id):
        """Retrieve full conversation history"""
        with current_app.app_context():
            messages = Message.query.filter_by(conversation_id=conversation_id).order_by(Message.created_at).all()
            history = []
            for msg in messages:
                history.append({
                    "role": msg.role,
                    "content": msg.content
                })
            logger.info(f"Retrieved conversation history for ID {conversation_id}: {len(history)} messages")
            logger.debug(f"Full conversation history: {json.dumps(history, indent=2)}")
            return history

    def get_follow_up_questions(self, conversation_id):
        """Retrieve stored follow-up questions for the conversation"""
        try:
            person_model = PersonModel.query.filter_by(conversation_id=conversation_id).first()
            if person_model and person_model.follow_up_questions:
                logger.info(f"Found {len(person_model.follow_up_questions)} follow-up questions")
                return person_model.follow_up_questions
            return None
        except Exception as e:
            logger.error(f"Error retrieving follow-up questions: {str(e)}")
            return None

    def is_second_pass(self, conversation_id):
        """Determine if this is a second-pass interview based on message history"""
        try:
            messages = Message.query.filter_by(conversation_id=conversation_id).count()
            return messages > 0  # If there are previous messages, consider it a second pass
        except Exception as e:
            logger.error(f"Error checking interview pass: {str(e)}")
            return False

    def stream_response(self, user_message, session_id=None, conversation_id=None):
        """Stream responses from the OpenAI Assistant API with conversation tracking"""
        try:
            # Get or create conversation within app context
            with current_app.app_context():
                try:
                    if conversation_id:
                        conversation = Conversation.query.get(conversation_id)
                    elif session_id:
                        conversation = self.get_or_create_conversation(session_id)
                    else:
                        raise ValueError("No session ID provided")

                    if not conversation:
                        raise ValueError("Failed to create or retrieve conversation")

                    logger.info(f"🔹 Processing message in conversation {conversation.id} with session {conversation.session_id}")
                except Exception as e:
                    logger.error(f"Error managing conversation: {str(e)}", exc_info=True)
                    yield f"Error managing conversation: {str(e)}"
                    return

                # Check if this is a second pass and get follow-up questions
                is_second = self.is_second_pass(conversation.id)
                follow_up_questions = None
                if is_second:
                    follow_up_questions = self.get_follow_up_questions(conversation.id)
                    if follow_up_questions:
                        logger.info("Using follow-up questions for second pass interview")

                # Create a new thread
                try:
                    thread = self.client.beta.threads.create()
                    logger.info(f"Created new thread {thread.id} for session {session_id}")
                except Exception as e:
                    logger.error(f"Error creating thread: {str(e)}", exc_info=True)
                    yield f"Error creating conversation thread: {str(e)}"
                    return

                # Store user message in database
                try:
                    message = Message(
                        conversation_id=conversation.id,
                        role='user',
                        content=user_message
                    )
                    db.session.add(message)
                    db.session.commit()
                    logger.info(f"🔹 Stored user message in conversation {conversation.id}")
                except Exception as e:
                    logger.error(f"Error storing user message: {str(e)}", exc_info=True)
                    yield f"Error storing message: {str(e)}"
                    return

                # Get conversation history and add to thread
                try:
                    history = self.get_conversation_history(conversation.id)
                    logger.info(f"🔹 Loading conversation history ({len(history)} messages) into thread {thread.id}")

                    # Prepare system message based on interview pass
                    if is_second and follow_up_questions:
                        system_content = f"""This is a follow-up interview session. Focus on asking these specific questions to gather missing information:

{json.dumps(follow_up_questions, indent=2)}

Guidelines:
1. Only ask questions from the provided list
2. Ask one question at a time
3. Acknowledge and incorporate the user's previous responses
4. If a topic is sufficiently covered, move to the next question
5. Once all follow-up questions are addressed, conclude the interview"""
                    else:
                        system_content = """Conduct the initial structured interview following the standard protocol."""

                    # Add system message to thread
                    self.client.beta.threads.messages.create(
                        thread_id=thread.id,
                        role="system",
                        content=system_content
                    )

                    # Add conversation history
                    for msg in history:
                        self.client.beta.threads.messages.create(
                            thread_id=thread.id,
                            role=msg["role"],
                            content=msg["content"]
                        )
                except Exception as e:
                    logger.error(f"Error adding history to thread: {str(e)}", exc_info=True)

                # Add the user message to the thread
                try:
                    self.client.beta.threads.messages.create(
                        thread_id=thread.id,
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
                        thread_id=thread.id,
                        assistant_id=self.assistant_id
                    )
                except Exception as e:
                    logger.error(f"Error starting assistant run: {str(e)}", exc_info=True)
                    yield f"Error starting conversation: {str(e)}"
                    return

                # Poll for response and stream it
                max_retries = 3
                retry_count = 0
                max_poll_duration = 30
                poll_interval = 1.0
                start_time = time.time()

                while True:
                    try:
                        current_time = time.time()
                        if current_time - start_time > max_poll_duration:
                            logger.warning(f"Polling timeout after {max_poll_duration} seconds")
                            yield "Response timeout exceeded"
                            break

                        run_status = self.client.beta.threads.runs.retrieve(
                            thread_id=thread.id,
                            run_id=run.id
                        )
                        logger.debug(f"Run status check: {run_status.status}")

                        if run_status.status == 'completed':
                            messages = self.client.beta.threads.messages.list(
                                thread_id=thread.id
                            )

                            # Get the latest assistant message
                            for msg in messages.data:
                                if msg.role == "assistant":
                                    try:
                                        content = msg.content[0].text.value if hasattr(msg.content[0], 'text') else str(msg.content[0])

                                        # Store assistant message in database
                                        assistant_message = Message(
                                            conversation_id=conversation.id,
                                            role='assistant',
                                            content=content
                                        )
                                        db.session.add(assistant_message)
                                        db.session.commit()

                                        logger.info(f"Stored assistant response in conversation {conversation.id}")
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

                        # Exponential backoff for polling interval
                        poll_interval = min(poll_interval * 1.5, 3.0)
                        time.sleep(poll_interval)

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
            with current_app.app_context():
                # Retrieve all messages for this conversation
                conversation = Conversation.query.get(conversation_id)
                if not conversation:
                    raise ValueError(f"Conversation {conversation_id} not found")

                messages = Message.query.filter_by(conversation_id=conversation_id).order_by(Message.created_at).all()

                # Format conversation history
                conversation_history = []
                for msg in messages:
                    logger.debug(f"Processing message: {msg.role} - {msg.content[:100]}...")
                    conversation_history.append({
                        "role": msg.role,
                        "content": msg.content
                    })

                logger.info(f"Evaluating interview progress for conversation {conversation_id}")
                logger.debug(f"Sending {len(conversation_history)} messages for evaluation")

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
                logger.info("Interview evaluation completed successfully")

                return evaluation
        except Exception as e:
            error_msg = f"Error evaluating interview progress: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return error_msg