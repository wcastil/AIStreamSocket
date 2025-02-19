import os
import logging
import json
from openai import OpenAI
from flask import current_app
from models import Message, Conversation, PersonModel
from database import db
import time
from session_evaluator import SessionEvaluator
from threading import Lock

logger = logging.getLogger(__name__)

class OpenAIAssistant:
    def __init__(self):
        try:
            self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            self.assistant_id = os.environ.get("OPENAI_ASSISTANT_ID")
            self.evaluator = SessionEvaluator()
            self._thread_cache = {}  # Session ID to Thread ID mapping
            self._cache_lock = Lock()  # Thread safety for cache operations
            self._message_batch_size = 10  # Number of messages to include in context
            self._min_messages_for_eval = 5  # Minimum messages before evaluation
            self._eval_cooldown = 300  # 5 minutes between evaluations
            self._last_eval_time = {}  # Track last evaluation time per session

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
        return any(phrase in message.lower() for phrase in trigger_phrases)

    def detect_second_pass_trigger(self, message):
        """Check if user message indicates starting second pass"""
        trigger_phrases = [
            "start second interview",
            "begin second pass",
            "start follow-up interview",
            "begin second interview phase",
            "proceed with second interview",
            "start second phase questions",
            "let's do the follow up",
            "ready for follow up",
            "continue with follow up",
            "move to second interview"
        ]
        return any(phrase in message.lower() for phrase in trigger_phrases)

    def get_or_create_conversation(self, session_id=None):
        """Get existing conversation or create a new one"""
        try:
            with current_app.app_context():
                if session_id:
                    conversation = Conversation.query.filter_by(session_id=session_id).first()
                    if conversation:
                        return conversation

                conversation = Conversation(session_id=session_id)
                db.session.add(conversation)
                db.session.commit()
                db.session.refresh(conversation)
                return conversation
        except Exception as e:
            logger.error(f"Error in get_or_create_conversation: {str(e)}", exc_info=True)
            raise

    def get_conversation_history(self, conversation_id):
        """Retrieve full conversation history"""
        with current_app.app_context():
            messages = Message.query.filter_by(conversation_id=conversation_id).order_by(Message.created_at).all()
            return [{
                "role": msg.role,
                "content": msg.content
            } for msg in messages]

    def handle_evaluation_trigger(self, conversation_id, session_id):
        """Process evaluation request with improved timing checks"""
        try:
            # Check if evaluation is appropriate
            if not self._can_run_evaluation(session_id, conversation_id):
                return ("I'd like to gather a bit more context before conducting an evaluation. "
                       "Let's continue with our conversation and I'll analyze it once we have "
                       "more substantial information to work with.")

            result = self.evaluator.analyze_conversation(session_id)

            if result['success']:
                # Update evaluation timestamp
                self._last_eval_time[session_id] = time.time()

                # Automatically mark first pass as complete when evaluation succeeds
                conversation = Conversation.query.get(conversation_id)
                if conversation:
                    conversation.first_pass_completed = True
                    db.session.commit()

                return (
                    "I've analyzed our conversation and identified several areas to explore further. "
                    "The first interview pass has been marked as complete. "
                    "When you're ready to continue with the follow-up interview, just say 'start second interview' "
                    "or use the button on the conversations page."
                )
            else:
                logger.error(f"Evaluation failed: {result['error']}")
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

            if not conversation.first_pass_completed:
                return ("The first interview pass needs to be completed and evaluated "
                       "before we can proceed with follow-up questions. Would you like "
                       "to complete the current interview first?")

            person_model = PersonModel.query.filter_by(conversation_id=conversation.id).first()
            if not person_model or not person_model.follow_up_questions:
                return ("I don't have any follow-up questions prepared yet. "
                       "Let's evaluate your responses first by saying 'evaluate interview'.")

            conversation.current_pass = 2
            db.session.commit()

            first_question = person_model.follow_up_questions[0]
            message = "Let's begin with the follow-up questions.\n\n"
            if isinstance(first_question, dict):
                message += first_question.get('question', '')
            else:
                message += first_question

            return message

        except Exception as e:
            logger.error(f"Error in second pass transition: {str(e)}")
            return "I encountered an error preparing the follow-up questions. Please try again."

    def get_next_follow_up_question(self, conversation_id):
        """Get the next follow-up question in sequence"""
        try:
            conversation = Conversation.query.get(conversation_id)
            if not conversation or not conversation.person_model:
                return None

            current_questions = conversation.person_model.follow_up_questions
            second_pass_messages = Message.query.filter(
                Message.conversation_id == conversation_id,
                Message.created_at >= conversation.updated_at
            ).count()

            # Calculate which question to ask next, cycling through the list
            question_index = (second_pass_messages // 2) % len(current_questions)

            next_question = current_questions[question_index]
            if isinstance(next_question, dict):
                return next_question.get('question', '')
            return next_question

        except Exception as e:
            logger.error(f"Error getting next follow-up question: {str(e)}")
            return None

    def detect_completion_trigger(self, message):
        """Check if user message indicates completing first pass"""
        trigger_phrases = [
            "mark interview complete",
            "complete first interview",
            "end first interview",
            "finish first pass",
            "mark first pass complete",
            "first interview done",
            "we can move on",
            "ready for second pass",
            "done with first interview"
        ]
        return any(phrase in message.lower() for phrase in trigger_phrases)

    def handle_completion_trigger(self, conversation_id):
        """Handle marking the first interview pass as complete"""
        try:
            conversation = Conversation.query.get(conversation_id)
            if not conversation:
                return "Unable to find the conversation."

            conversation.first_pass_completed = True
            db.session.commit()

            return ("First interview pass has been marked as complete. "
                   "You can now start the second interview by saying 'start second interview'.")

        except Exception as e:
            logger.error(f"Error marking interview complete: {str(e)}")
            return "I encountered an error while trying to mark the interview as complete."

    def detect_end_interview_trigger(self, message):
        """Check if user message indicates wanting to end the interview"""
        trigger_phrases = [
            "end interview",
            "finish interview",
            "conclude interview",
            "that's all",
            "we're done",
            "wrap up"
        ]
        return any(phrase in message.lower() for phrase in trigger_phrases)


    def _get_or_create_thread(self, session_id):
        """Get existing thread or create new one with thread safety"""
        with self._cache_lock:
            if session_id in self._thread_cache:
                try:
                    # Verify thread still exists
                    self.client.beta.threads.retrieve(self._thread_cache[session_id])
                    return self._thread_cache[session_id]
                except Exception:
                    logger.info(f"Thread expired for session {session_id}, creating new")
                    pass

            thread = self.client.beta.threads.create()
            self._thread_cache[session_id] = thread.id
            return thread.id

    def _load_recent_messages(self, conversation_id, limit=10):
        """Load only the most recent messages for context"""
        with current_app.app_context():
            messages = Message.query.filter_by(conversation_id=conversation_id)\
                .order_by(Message.created_at.desc())\
                .limit(limit)\
                .all()
            return [{
                "role": msg.role,
                "content": msg.content
            } for msg in reversed(messages)]  # Reverse to get chronological order

    def stream_response(self, user_message, session_id=None, conversation_id=None):
        """Optimized streaming response handler"""
        try:
            with current_app.app_context():
                # Get or create conversation with reduced DB operations
                conversation = None
                if conversation_id:
                    conversation = Conversation.query.get(conversation_id)
                elif session_id:
                    conversation = Conversation.query.filter_by(session_id=session_id).first()
                    if not conversation:
                        conversation = Conversation(session_id=session_id)
                        db.session.add(conversation)
                        db.session.commit()
                else:
                    raise ValueError("No session ID provided")

                # Check for special commands before creating/accessing thread
                if self.detect_completion_trigger(user_message):
                    return self.handle_completion_trigger(conversation.id)
                elif self.detect_second_pass_trigger(user_message):
                    return self.handle_second_pass_transition(conversation.id)
                elif self.detect_evaluation_trigger(user_message):
                    return self.handle_evaluation_trigger(conversation.id, conversation.session_id)

                # Get or create thread for session
                thread_id = self._get_or_create_thread(session_id)

                # Add message to database
                message = Message(
                    conversation_id=conversation.id,
                    role='user',
                    content=user_message
                )
                db.session.add(message)
                db.session.commit()

                # Load recent message history
                recent_messages = self._load_recent_messages(conversation.id, self._message_batch_size)

                # Add messages to thread efficiently
                for msg in recent_messages[-self._message_batch_size:]:  # Only latest messages
                    self.client.beta.threads.messages.create(
                        thread_id=thread_id,
                        role=msg["role"],
                        content=msg["content"]
                    )

                # Create and monitor run with optimized polling
                run = self.client.beta.threads.runs.create(
                    thread_id=thread_id,
                    assistant_id=self.assistant_id
                )

                poll_interval = 0.5
                max_polls = 60
                polls = 0

                while polls < max_polls:
                    try:
                        run_status = self.client.beta.threads.runs.retrieve(
                            thread_id=thread_id,
                            run_id=run.id
                        )

                        if run_status.status == 'completed':
                            messages = self.client.beta.threads.messages.list(
                                thread_id=thread_id,
                                limit=1  # Only get latest message
                            )

                            for msg in messages.data:
                                if msg.role == "assistant":
                                    content = msg.content[0].text.value if hasattr(msg.content[0], 'text') else str(msg.content[0])

                                    # Store response in database
                                    assistant_message = Message(
                                        conversation_id=conversation.id,
                                        role='assistant',
                                        content=content
                                    )
                                    db.session.add(assistant_message)
                                    db.session.commit()

                                    yield content
                                    return

                        elif run_status.status in ['failed', 'cancelled', 'expired']:
                            error_msg = f"Assistant run failed with status: {run_status.status}"
                            logger.error(error_msg)
                            yield error_msg
                            return

                        time.sleep(poll_interval)
                        polls += 1
                        poll_interval = min(poll_interval * 1.5, 2.0)  # Progressive backoff

                    except Exception as e:
                        logger.error(f"Error in run status check: {str(e)}", exc_info=True)
                        yield f"Error processing response: {str(e)}"
                        return

                yield "Response timeout exceeded"
                return

        except Exception as e:
            error_msg = f"Error in OpenAI Assistant: {str(e)}"
            logger.error(error_msg, exc_info=True)
            yield error_msg

    def evaluate_interview_progress(self, conversation_id):
        """Evaluate the full interview session and generate insights"""
        try:
            with current_app.app_context():
                conversation = Conversation.query.get(conversation_id)
                if not conversation:
                    raise ValueError(f"Conversation {conversation_id} not found")

                messages = Message.query.filter_by(conversation_id=conversation_id).order_by(Message.created_at).all()

                conversation_history = []
                for msg in messages:
                    conversation_history.append({
                        "role": msg.role,
                        "content": msg.content
                    })

                system_message = """Analyze the interview conversation and identify:
                1. Key insights and patterns
                2. Missing or incomplete information
                3. Suggested follow-up questions
                4. Areas that need clarification

                Respond with a concise summary and specific recommendations."""

                response = self.client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": system_message},
                        *conversation_history
                    ]
                )

                evaluation = response.choices[0].message.content
                return evaluation

        except Exception as e:
            error_msg = f"Error evaluating interview progress: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return error_msg

    def _can_run_evaluation(self, session_id, conversation_id):
        """Check if enough conversation has accumulated for evaluation"""
        try:
            # Check cooldown
            current_time = time.time()
            if session_id in self._last_eval_time:
                time_since_last_eval = current_time - self._last_eval_time[session_id]
                if time_since_last_eval < self._eval_cooldown:
                    logger.debug(f"Evaluation cooldown active for session {session_id}")
                    return False

            # Check message count
            message_count = Message.query.filter_by(conversation_id=conversation_id).count()
            if message_count < self._min_messages_for_eval:
                logger.debug(f"Not enough messages ({message_count}) for evaluation")
                return False

            # Check if previous evaluation exists
            person_model = PersonModel.query.filter_by(conversation_id=conversation_id).first()
            if person_model:
                # If we already have an evaluation, require more new messages
                messages_since_eval = Message.query.filter(
                    Message.conversation_id == conversation_id,
                    Message.created_at > person_model.created_at
                ).count()
                if messages_since_eval < self._min_messages_for_eval:
                    logger.debug(f"Not enough new messages since last evaluation")
                    return False

            return True

        except Exception as e:
            logger.error(f"Error checking evaluation eligibility: {str(e)}")
            return False