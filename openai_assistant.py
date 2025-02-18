import os
import logging
import json
from openai import OpenAI
from flask import current_app
from models import Message, Conversation, PersonModel
from database import db
import time
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
        return any(phrase in message.lower() for phrase in trigger_phrases)

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
        """Process evaluation request and generate follow-up questions"""
        try:
            result = self.evaluator.analyze_conversation(session_id)

            if result['success']:
                conversation = Conversation.query.get(conversation_id)
                if conversation:
                    conversation.first_pass_completed = True
                    db.session.commit()

                return (
                    "I've analyzed our conversation and identified several areas to explore further. "
                    "When you're ready to continue with the follow-up interview, just say 'start second interview'."
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

            question_index = (second_pass_messages // 2)

            if question_index >= len(current_questions):
                return "Thank you for sharing your experiences and insights. This concludes our interview. Your responses have been very helpful, and I appreciate your time and openness in discussing these topics."

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
            "mark first pass complete"
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

    def stream_response(self, user_message, session_id=None, conversation_id=None):
        """Stream responses from the OpenAI Assistant API with conversation tracking"""
        try:
            with current_app.app_context():
                try:
                    if conversation_id:
                        conversation = Conversation.query.get(conversation_id)
                        db.session.add(conversation)
                    elif session_id:
                        conversation = self.get_or_create_conversation(session_id)
                    else:
                        raise ValueError("No session ID provided")

                    if not conversation:
                        raise ValueError("Failed to create or retrieve conversation")

                    person_model = PersonModel.query.filter_by(conversation_id=conversation.id).first()
                    if person_model and conversation.first_pass_completed:
                        if "continue" in user_message.lower() or "let's begin" in user_message.lower():
                            transition_message = self.handle_second_pass_transition(conversation.id)
                            yield transition_message
                            return

                except Exception as e:
                    logger.error(f"Error managing conversation: {str(e)}", exc_info=True)
                    yield f"Error managing conversation: {str(e)}"
                    return

                if self.detect_completion_trigger(user_message):
                    completion_response = self.handle_completion_trigger(conversation.id)
                    yield completion_response
                    return

                if self.detect_evaluation_trigger(user_message):
                    evaluation_response = self.handle_evaluation_trigger(conversation.id, conversation.session_id)
                    yield evaluation_response
                    return

                if self.detect_second_pass_trigger(user_message):
                    transition_message = self.handle_second_pass_transition(conversation.id)
                    yield transition_message
                    return

                if conversation.current_pass == 2:
                    message = Message(
                        conversation_id=conversation.id,
                        role='user',
                        content=user_message
                    )
                    db.session.add(message)
                    db.session.commit()

                    should_probe_deeper = any(trigger in user_message.lower() for trigger in [
                        'because', 'when', 'after', 'during', 'while',
                        'situation', 'experience', 'example', 'instance',
                        'happened', 'occurred', 'felt', 'thought'
                    ])

                    if should_probe_deeper:
                        try:
                            follow_up = self.client.chat.completions.create(
                                model="gpt-4",
                                messages=[
                                    {"role": "system", "content": "Generate a natural follow-up question to learn more specific details about the user's response. Focus on understanding the context, emotions, and specific examples they mentioned."},
                                    {"role": "user", "content": user_message}
                                ]
                            )
                            probe_question = follow_up.choices[0].message.content

                            probe_message = Message(
                                conversation_id=conversation.id,
                                role='assistant',
                                content=probe_question
                            )
                            db.session.add(probe_message)
                            db.session.commit()

                            yield probe_question
                            return
                        except Exception as e:
                            logger.error(f"Error generating follow-up probe: {str(e)}")

                    next_question = self.get_next_follow_up_question(conversation.id)
                    if next_question:
                        yield next_question
                        return

                thread = self.client.beta.threads.create()
                message = Message(
                    conversation_id=conversation.id,
                    role='user',
                    content=user_message
                )
                db.session.add(message)
                db.session.commit()

                history = self.get_conversation_history(conversation.id)
                instructions = "[INSTRUCTIONS]\nConduct the initial structured interview following the standard protocol.\n[/INSTRUCTIONS]"

                self.client.beta.threads.messages.create(
                    thread_id=thread.id,
                    role="user",
                    content=instructions
                )

                for msg in history:
                    self.client.beta.threads.messages.create(
                        thread_id=thread.id,
                        role=msg["role"],
                        content=msg["content"]
                    )

                self.client.beta.threads.messages.create(
                    thread_id=thread.id,
                    role="user",
                    content=user_message
                )

                run = self.client.beta.threads.runs.create(
                    thread_id=thread.id,
                    assistant_id=self.assistant_id
                )

                max_retries = 3
                retry_count = 0
                max_poll_duration = 30
                poll_interval = 1.0
                start_time = time.time()

                while True:
                    try:
                        if time.time() - start_time > max_poll_duration:
                            yield "Response timeout exceeded"
                            break

                        run_status = self.client.beta.threads.runs.retrieve(
                            thread_id=thread.id,
                            run_id=run.id
                        )

                        if run_status.status == 'completed':
                            messages = self.client.beta.threads.messages.list(
                                thread_id=thread.id
                            )

                            for msg in messages.data:
                                if msg.role == "assistant":
                                    try:
                                        content = msg.content[0].text.value if hasattr(msg.content[0], 'text') else str(msg.content[0])
                                        assistant_message = Message(
                                            conversation_id=conversation.id,
                                            role='assistant',
                                            content=content
                                        )
                                        db.session.add(assistant_message)
                                        db.session.commit()
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