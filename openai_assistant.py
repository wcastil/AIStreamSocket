import os
import logging
import json
from openai import OpenAI
from models import InterviewData, Message, Conversation, PersonModel
from database import db
import time
from flask import current_app
from session_evaluator import SessionEvaluator

logger = logging.getLogger(__name__)

class OpenAIAssistant:
    def __init__(self):
        try:
            self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            self.assistant_id = os.environ.get("OPENAI_ASSISTANT_ID")
            self.evaluator = SessionEvaluator()

            if not self.assistant_id:
                raise ValueError("OPENAI_ASSISTANT_ID environment variable is required")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {str(e)}", exc_info=True)
            raise

    def detect_evaluation_trigger(self, message):
        """Check if user message requests evaluation"""
        trigger_phrases = [
            "evaluate interview",
            "run evaluation",
            "analyze responses",
            "check my answers",
            "evaluate session",
            "assess interview"
        ]
        message_lower = message.lower()
        triggered = any(phrase in message_lower for phrase in trigger_phrases)
        if triggered:
            logger.info(f"Evaluation trigger detected in message: {message}")
        return triggered

    def detect_second_pass_trigger(self, message):
        """Check if user message indicates starting second pass"""
        trigger_phrases = [
            "start second interview",
            "begin second pass",
            "start follow-up interview",
            "begin second interview phase",
            "proceed with second interview",
            "start second phase questions"
        ]
        message_lower = message.lower()
        triggered = any(phrase in message_lower for phrase in trigger_phrases)
        if triggered:
            logger.info(f"Second pass trigger detected in message: {message}")
        return triggered

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
        """Determine if this is a second-pass interview based on evaluation status"""
        try:
            conversation = Conversation.query.get(conversation_id)
            if not conversation:
                return False

            # Check if first pass is completed and has evaluation results
            return (conversation.first_pass_completed and 
                    conversation.person_model is not None and 
                    conversation.current_pass > 1)
        except Exception as e:
            logger.error(f"Error checking interview pass: {str(e)}")
            return False

    def handle_evaluation_trigger(self, conversation_id, session_id):
        """Process evaluation request and generate follow-up questions"""
        try:
            logger.info(f"🔍 Running evaluation for session {session_id}")

            # First check if we already have evaluation results
            with current_app.app_context():
                person_model = PersonModel.query.filter_by(conversation_id=conversation_id).first()
                if person_model:
                    questions_count = len(person_model.follow_up_questions)
                    topics_count = len(person_model.missing_topics)
                    logger.info(f"✅ Found existing evaluation with {questions_count} follow-up questions for {topics_count} topics")

                    # Mark first pass as completed since evaluation exists
                    conversation = Conversation.query.get(conversation_id)
                    if conversation and not conversation.first_pass_completed:
                        conversation.first_pass_completed = True
                        db.session.commit()
                        logger.info(f"Marked first pass as completed for conversation {conversation_id}")

                    return (f"I've previously analyzed our conversation and identified {topics_count} areas to explore further. "
                           f"I've prepared {questions_count} follow-up questions. When you're ready to continue, "
                           "just let me know and we'll address these areas in detail.")

            # If no existing evaluation, run a new one
            result = self.evaluator.analyze_conversation(session_id)

            if result['success']:
                questions_count = len(result['follow_up_questions'])
                topics_count = len(result['missing_topics'])
                logger.info(f"✅ Evaluation successful - Generated {questions_count} follow-up questions for {topics_count} topics")

                # Mark first pass as completed
                conversation = Conversation.query.get(conversation_id)
                if conversation:
                    conversation.first_pass_completed = True
                    db.session.commit()
                    logger.info(f"Marked first pass as completed for conversation {conversation_id}")

                return (f"I've analyzed our conversation and identified {topics_count} areas to explore further. "
                       f"I've prepared {questions_count} follow-up questions. When you're ready to continue, "
                       "just let me know and we'll address these areas in detail.")
            else:
                logger.error(f"❌ Evaluation failed: {result['error']}")
                return "I apologize, but I encountered an error while evaluating our conversation. Would you like to continue with the standard interview format?"

        except Exception as e:
            logger.error(f"Error in handle_evaluation_trigger: {str(e)}", exc_info=True)
            return "I encountered an error while trying to evaluate our conversation. Would you like to continue with the standard interview format?"

    def handle_second_pass_transition(self, conversation_id):
        """Handle the transition to second pass interview"""
        try:
            conversation = Conversation.query.get(conversation_id)
            if not conversation:
                return "Unable to find the conversation."

            # Verify first pass completion and evaluation
            if not conversation.first_pass_completed:
                return ("The first interview pass needs to be completed and evaluated "
                       "before we can proceed with follow-up questions. Would you like "
                       "to complete the current interview first?")

            person_model = conversation.person_model
            if not person_model or not person_model.follow_up_questions:
                return ("I don't have any follow-up questions prepared yet. "
                       "Let's evaluate your responses first by saying 'evaluate interview'.")

            # Update pass tracking
            conversation.current_pass = 2
            db.session.commit()

            # Format transition message with question preview
            questions_preview = person_model.follow_up_questions[:2]
            message = (
                "Great! Let's proceed with the follow-up questions. "
                f"I have {len(person_model.follow_up_questions)} questions prepared. "
                "Here's what we'll be exploring:\n\n"
            )
            if questions_preview:
                message += "\n".join(f"• {q}" for q in questions_preview)
                if len(person_model.follow_up_questions) > 2:
                    message += "\n\n...and more."

            return message

        except Exception as e:
            logger.error(f"Error in second pass transition: {str(e)}")
            return "I encountered an error preparing the follow-up questions. Please try again."


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

                # Check for evaluation trigger
                if self.detect_evaluation_trigger(user_message):
                    logger.info("Evaluation trigger detected, running evaluation...")
                    evaluation_response = self.handle_evaluation_trigger(conversation.id, conversation.session_id)
                    logger.info(f"Evaluation response: {evaluation_response[:100]}...")

                    # Store evaluation trigger response
                    try:
                        evaluation_message = Message(
                            conversation_id=conversation.id,
                            role='assistant',
                            content=evaluation_response
                        )
                        db.session.add(evaluation_message)
                        db.session.commit()
                        logger.info("Stored evaluation response in database")
                    except Exception as e:
                        logger.error(f"Error storing evaluation response: {str(e)}")

                    yield evaluation_response
                    return

                # Check for second pass trigger and get follow-up questions
                if self.detect_second_pass_trigger(user_message):
                    transition_message = self.handle_second_pass_transition(conversation.id)
                    yield transition_message
                    return

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

                    # Format instructions based on conversation state
                    instructions = "[INSTRUCTIONS]\nConduct the initial structured interview following the standard protocol.\n[/INSTRUCTIONS]"


                    # Add instructions as first user message
                    self.client.beta.threads.messages.create(
                        thread_id=thread.id,
                        role="user",
                        content=instructions
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