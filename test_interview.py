import logging
import os
from app import app, db
from models import Conversation, Message, PersonModel
from openai_assistant import OpenAIAssistant
from session_evaluator import SessionEvaluator
import json
import sys

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class InterviewTester:
    def __init__(self):
        self.app = app
        self.assistant = OpenAIAssistant()
        self.evaluator = SessionEvaluator()

    def load_test_conversation(self, session_id):
        """Load an existing conversation for testing"""
        with self.app.app_context():
            conversation = Conversation.query.filter_by(session_id=session_id).first()
            if not conversation:
                raise ValueError(f"No conversation found with session ID: {session_id}")

            messages = Message.query.filter_by(conversation_id=conversation.id).order_by(Message.created_at).all()
            logger.info(f"Loaded {len(messages)} messages from conversation {session_id}")
            return conversation, messages

    def replay_first_interview(self, session_id="7b7083dce103d9596c7e6c6a77d487b3"):
        """Replay the first interview to test second-pass functionality"""
        try:
            conversation, messages = self.load_test_conversation(session_id)
            logger.info(f"Starting test replay for conversation {session_id}")

            # Get user messages to simulate the interview
            user_messages = [msg for msg in messages if msg.role == 'user']
            assistant_responses = [msg for msg in messages if msg.role == 'assistant']

            logger.info(f"Found {len(user_messages)} user messages and {len(assistant_responses)} assistant responses")

            # Create a new test conversation
            test_session_id = f"test_{os.urandom(4).hex()}"
            logger.info(f"Creating test conversation with session ID: {test_session_id}")

            # Simulate the interview exchange
            with self.app.app_context():
                for i, user_msg in enumerate(user_messages):
                    logger.info(f"Processing message {i+1}/{len(user_messages)}")
                    logger.info(f"User message: {user_msg.content[:100]}...")

                    # Process through assistant
                    responses = []
                    for chunk in self.assistant.stream_response(user_msg.content, session_id=test_session_id):
                        if isinstance(chunk, str):
                            responses.append(chunk)

                    full_response = ''.join(responses)
                    logger.info(f"Assistant response: {full_response[:100]}...")

            logger.info("First interview pass completed. Running evaluation...")
            # Run evaluation to generate follow-up questions
            evaluation_result = self.evaluator.analyze_conversation(test_session_id)

            if evaluation_result['success']:
                logger.info("Evaluation completed successfully")
                logger.info(f"Generated {len(evaluation_result['follow_up_questions'])} follow-up questions")
                logger.info(f"Missing topics: {evaluation_result['missing_topics']}")
                logger.info("Follow-up questions:")
                for q in evaluation_result['follow_up_questions']:
                    logger.info(f"- {q}")

                # Verify storage in database
                with self.app.app_context():
                    conversation = Conversation.query.filter_by(session_id=test_session_id).first()
                    if not conversation:
                        raise ValueError(f"Conversation not found for session {test_session_id}")

                    person_model = PersonModel.query.filter_by(conversation_id=conversation.id).first()
                    if not person_model:
                        raise ValueError(f"Person model not found for conversation {conversation.id}")

                    logger.info("📊 Database verification:")
                    logger.info(f"- Model ID: {person_model.id}")
                    logger.info(f"- Missing topics count: {len(person_model.missing_topics)}")
                    logger.info(f"- Follow-up questions count: {len(person_model.follow_up_questions)}")
                    logger.info(f"- Data model size: {len(str(person_model.data_model))} chars")

                # Write test results to a file for reference
                with open(f'test_results_{test_session_id}.json', 'w') as f:
                    json.dump({
                        'test_session_id': test_session_id,
                        'conversation_id': conversation.id,
                        'person_model_id': person_model.id,
                        'follow_up_questions': person_model.follow_up_questions,
                        'missing_topics': person_model.missing_topics,
                    }, f, indent=2)
                logger.info(f"✅ Test results saved to test_results_{test_session_id}.json")
            else:
                logger.error(f"Evaluation failed: {evaluation_result['error']}")

            return test_session_id

        except Exception as e:
            logger.error(f"Error in replay_first_interview: {str(e)}", exc_info=True)
            raise

    def run_second_pass(self, test_session_id):
        """Run a second interview pass using generated follow-up questions"""
        try:
            logger.info(f"Starting second-pass interview for session {test_session_id}")

            # Verify follow-up questions are available
            with self.app.app_context():
                conversation = Conversation.query.filter_by(session_id=test_session_id).first()
                if not conversation:
                    raise ValueError(f"Conversation not found for session {test_session_id}")

                person_model = PersonModel.query.filter_by(conversation_id=conversation.id).first()
                if not person_model:
                    raise ValueError(f"Person model not found for conversation {conversation.id}")

                logger.info("Stored follow-up questions:")
                for q in person_model.follow_up_questions:
                    logger.info(f"- {q}")

            # Simulate a simple response to trigger the follow-up questions
            responses = []
            for chunk in self.assistant.stream_response(
                "Let's continue with the follow-up questions.",
                session_id=test_session_id
            ):
                if isinstance(chunk, str):
                    responses.append(chunk)

            full_response = ''.join(responses)
            logger.info(f"Second-pass initial response: {full_response[:100]}...")

            # Verify the response includes follow-up question(s)
            found_questions = any(q in full_response for q in person_model.follow_up_questions)
            logger.info(f"Response contains follow-up questions: {found_questions}")

            return full_response

        except Exception as e:
            logger.error(f"Error in second-pass interview: {str(e)}", exc_info=True)
            raise

    def test_no_followup_scenario(self):
        """Test scenario where there are no follow-up questions"""
        try:
            test_session_id = f"test_no_followup_{os.urandom(4).hex()}"
            logger.info(f"Testing no-followup scenario with session {test_session_id}")

            # Create an empty conversation
            with self.app.app_context():
                conversation = Conversation(session_id=test_session_id)
                db.session.add(conversation)
                db.session.commit()

                # Create person model with no follow-ups
                person_model = PersonModel(
                    conversation_id=conversation.id,
                    data_model={},
                    missing_topics=[],
                    follow_up_questions=[]
                )
                db.session.add(person_model)
                db.session.commit()

            # Try to start a second pass
            responses = []
            for chunk in self.assistant.stream_response(
                "Let's continue our conversation.",
                session_id=test_session_id
            ):
                if isinstance(chunk, str):
                    responses.append(chunk)

            full_response = ''.join(responses)
            logger.info(f"No-followup scenario response: {full_response[:100]}...")

            return test_session_id

        except Exception as e:
            logger.error(f"Error in no-followup scenario: {str(e)}", exc_info=True)
            raise

def load_test_session(test_session_id):
    """Load a test session and prepare it for continuation"""
    try:
        logger.info(f"Loading test session {test_session_id} for continuation")
        tester = InterviewTester()

        with app.app_context():
            # Verify the test session exists
            conversation = Conversation.query.filter_by(session_id=test_session_id).first()
            if not conversation:
                logger.error(f"Test session {test_session_id} not found")
                return None

            # Load test results if they exist
            test_results_file = f'test_results_{test_session_id}.json'
            if os.path.exists(test_results_file):
                with open(test_results_file, 'r') as f:
                    test_data = json.load(f)
                logger.info(f"Loaded test data from {test_results_file}")
            else:
                logger.warning(f"No test results file found for {test_session_id}")
                test_data = {}

            # Verify person model exists
            person_model = PersonModel.query.filter_by(conversation_id=conversation.id).first()
            if person_model:
                logger.info(f"Found person model with {len(person_model.follow_up_questions)} follow-up questions")
            else:
                logger.warning("No person model found for test session")

            # Return session information
            return {
                'session_id': test_session_id,
                'conversation_id': conversation.id,
                'messages_count': len(conversation.messages),
                'has_person_model': bool(person_model),
                'follow_up_questions': person_model.follow_up_questions if person_model else [],
                'test_data': test_data
            }

    except Exception as e:
        logger.error(f"Error loading test session: {str(e)}", exc_info=True)
        return None

def run_first_pass_only():
    """Run only the first interview pass test"""
    try:
        logger.info("🚀 Running first-pass interview test only")
        tester = InterviewTester()
        test_session = tester.replay_first_interview()
        logger.info(f"✅ First pass completed successfully. Test session ID: {test_session}")
        logger.info(f"Results saved to test_results_{test_session}.json")
        return test_session
    except Exception as e:
        logger.error(f"❌ Test failed: {str(e)}", exc_info=True)
        return None

def run_full_test():
    """Run the complete interview test suite"""
    try:
        tester = InterviewTester()

        # Run first interview pass
        test_session = tester.replay_first_interview()
        logger.info(f"First pass completed. Test session ID: {test_session}")

        # Run second interview pass
        second_pass_response = tester.run_second_pass(test_session)
        logger.info("Second pass initiated successfully")
        logger.info(f"Initial response: {second_pass_response[:100]}")

        # Test no-followup scenario
        no_followup_session = tester.test_no_followup_scenario()
        logger.info(f"No-followup scenario completed. Test session ID: {no_followup_session}")

        return test_session
    except Exception as e:
        logger.error(f"Test failed: {str(e)}", exc_info=True)
        return None

if __name__ == "__main__":
    with app.app_context():
        # Check command line arguments
        if len(sys.argv) > 1:
            if sys.argv[1] == "--first-pass":
                run_first_pass_only()
            elif sys.argv[1] == "--load-session" and len(sys.argv) > 2:
                session_info = load_test_session(sys.argv[2])
                if session_info:
                    logger.info("✅ Test session loaded successfully:")
                    logger.info(f"Session ID: {session_info['session_id']}")
                    logger.info(f"Messages: {session_info['messages_count']}")
                    logger.info(f"Has person model: {session_info['has_person_model']}")
                    if session_info['has_person_model']:
                        logger.info(f"Follow-up questions: {len(session_info['follow_up_questions'])}")
                else:
                    logger.error("❌ Failed to load test session")
            else:
                run_full_test()
        else:
            run_full_test()