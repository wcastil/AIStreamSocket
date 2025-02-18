from datetime import datetime
from database import db

class Conversation(db.Model):
    __tablename__ = 'conversations'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    messages = db.relationship('Message', backref='conversation', lazy=True, cascade='all, delete-orphan')
    interview_data = db.relationship('InterviewData', backref='conversation', uselist=False, cascade='all, delete-orphan')
    session_id = db.Column(db.String(100), unique=True)  # Added for session tracking
    person_model = db.relationship('PersonModel', backref='conversation', uselist=False, cascade='all, delete-orphan')

class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class InterviewData(db.Model):
    __tablename__ = 'interview_data'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Core values and priorities
    personal_values = db.Column(db.JSON, default=list)
    professional_values = db.Column(db.JSON, default=list)
    prioritization_rules = db.Column(db.JSON, default=list)

    # Personality and emotional profile
    emotional_regulation = db.Column(db.String(500))
    leadership_style = db.Column(db.String(500))
    decision_making_tendencies = db.Column(db.String(500))

    # Decision making framework
    analytical_intuitive_balance = db.Column(db.Float)
    risk_tolerance = db.Column(db.String(500))
    timeframe_focus = db.Column(db.String(500))

    # Behavioral patterns
    stress_response = db.Column(db.String(500))
    conflict_resolution = db.Column(db.String(500))
    work_life_balance = db.Column(db.String(500))

    # Relationships and interactions
    collaboration_style = db.Column(db.String(500))
    trust_building = db.Column(db.String(500))
    conflict_handling = db.Column(db.String(500))

    # Growth and learning
    preferred_learning = db.Column(db.String(500))
    reflection_tendencies = db.Column(db.String(500))
    openness_to_change = db.Column(db.Float)

    # Creativity and divergence
    divergent_thinking = db.Column(db.String(500))
    contrarian_tendencies = db.Column(db.String(500))
    paradox_handling = db.Column(db.String(500))
    deviation_conditions = db.Column(db.String(500))

    # Missing fields tracking
    missing_fields = db.Column(db.JSON, default=list)

class PersonModel(db.Model):
    """Stores structured person model data extracted from interviews"""
    __tablename__ = 'person_models'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    data_model = db.Column(db.JSON, nullable=False)  # Stores structured person model
    missing_topics = db.Column(db.JSON, default=list)  # Stores identified missing details
    follow_up_questions = db.Column(db.JSON, default=list)  # Suggested follow-ups