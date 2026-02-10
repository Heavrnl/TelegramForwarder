from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, Enum, UniqueConstraint, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from enums.enums import ForwardMode, PreviewMode, MessageMode, AddMode, HandleMode
import logging
import os
from dotenv import load_dotenv

load_dotenv()
Base = declarative_base()

class Chat(Base):
    __tablename__ = 'chats'

    id = Column(Integer, primary_key=True)
    telegram_chat_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=True)
    current_add_id = Column(String, nullable=True)

    # Relationships
    source_rules = relationship('ForwardRule', foreign_keys='ForwardRule.source_chat_id', back_populates='source_chat')
    target_rules = relationship('ForwardRule', foreign_keys='ForwardRule.target_chat_id', back_populates='target_chat')

class ForwardRule(Base):
    __tablename__ = 'forward_rules'

    id = Column(Integer, primary_key=True)
    source_chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    target_chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    forward_mode = Column(Enum(ForwardMode), nullable=False, default=ForwardMode.BLACKLIST)
    use_bot = Column(Boolean, default=True)
    message_mode = Column(Enum(MessageMode), nullable=False, default=MessageMode.MARKDOWN)
    is_replace = Column(Boolean, default=False)
    is_preview = Column(Enum(PreviewMode), nullable=False, default=PreviewMode.FOLLOW)  # Three values: on, off, follow original message
    is_original_link = Column(Boolean, default=False)   # Whether to include original message link
    is_ufb = Column(Boolean, default=False)
    ufb_domain = Column(String, nullable=True)
    ufb_item = Column(String, nullable=True,default='main')
    is_delete_original = Column(Boolean, default=False)  # Whether to delete original message
    is_original_sender = Column(Boolean, default=False)  # Whether to include original message sender name
    userinfo_template = Column(String, default='**{name}**', nullable=True)  # User info template
    time_template = Column(String, default='{time}', nullable=True)  # Time template
    original_link_template = Column(String, default='Original link: {original_link}', nullable=True)  # Original link template
    is_original_time = Column(Boolean, default=False)  # Whether to include original message send time
    add_mode = Column(Enum(AddMode), nullable=False, default=AddMode.BLACKLIST) # Add mode, default blacklist
    enable_rule = Column(Boolean, default=True)  # Whether to enable rule
    is_filter_user_info = Column(Boolean, default=False)  # Whether to filter user info
    handle_mode = Column(Enum(HandleMode), nullable=False, default=HandleMode.FORWARD) # Handle mode, edit mode and forward mode, default forward
    enable_comment_button = Column(Boolean, default=False)  # Whether to add comment section shortcut button for corresponding message
    enable_media_type_filter = Column(Boolean, default=False)  # Whether to enable media type filter
    enable_media_size_filter = Column(Boolean, default=False)  # Whether to enable media size filter
    max_media_size = Column(Integer, default=os.getenv('DEFAULT_MAX_MEDIA_SIZE', 10))  # Media size limit, in MB
    is_send_over_media_size_message = Column(Boolean, default=True)  # Whether to send notification for media exceeding size limit
    enable_extension_filter = Column(Boolean, default=False)  # Whether to enable media extension filter
    extension_filter_mode = Column(Enum(AddMode), nullable=False, default=AddMode.BLACKLIST)  # Media extension filter mode, default blacklist
    enable_reverse_blacklist = Column(Boolean, default=False)  # Whether to reverse blacklist
    enable_reverse_whitelist = Column(Boolean, default=False)  # Whether to reverse whitelist
    media_allow_text = Column(Boolean, default=False)  # Whether to allow text through
    # Push related fields
    enable_push = Column(Boolean, default=False)  # Whether to enable push
    enable_only_push = Column(Boolean, default=False)  # Whether to only forward to push configuration

    # AI related fields
    is_ai = Column(Boolean, default=False)  # Whether to enable AI processing
    ai_model = Column(String, nullable=True)  # AI model in use
    ai_prompt = Column(String, nullable=True)  # AI processing prompt
    enable_ai_upload_image = Column(Boolean, default=False)  # Whether to enable AI image upload feature
    is_summary = Column(Boolean, default=False)  # Whether to enable AI summary
    summary_time = Column(String(5), default=os.getenv('DEFAULT_SUMMARY_TIME', '07:00'))
    summary_prompt = Column(String, nullable=True)  # AI summary prompt
    is_keyword_after_ai = Column(Boolean, default=False) # Whether to execute keyword filtering again after AI processing
    is_top_summary = Column(Boolean, default=True) # Whether to pin summary message
    enable_delay = Column(Boolean, default=False)  # Whether to enable delayed processing
    delay_seconds = Column(Integer, default=5)  # Delay processing seconds
    # RSS related fields
    only_rss = Column(Boolean, default=False)  # Whether to only forward RSS
    # Sync feature related
    enable_sync = Column(Boolean, default=False)  # Whether to enable rule sync feature

    # Add unique constraint
    __table_args__ = (
        UniqueConstraint('source_chat_id', 'target_chat_id', name='unique_source_target'),
    )

    # Relationships
    source_chat = relationship('Chat', foreign_keys=[source_chat_id], back_populates='source_rules')
    target_chat = relationship('Chat', foreign_keys=[target_chat_id], back_populates='target_rules')
    keywords = relationship('Keyword', back_populates='rule')
    replace_rules = relationship('ReplaceRule', back_populates='rule', cascade="all, delete-orphan")
    media_types = relationship('MediaTypes', uselist=False, back_populates='rule', cascade="all, delete-orphan")
    media_extensions = relationship('MediaExtensions', back_populates='rule', cascade="all, delete-orphan")
    rss_config = relationship('RSSConfig', uselist=False, back_populates='rule', cascade="all, delete-orphan")
    rule_syncs = relationship('RuleSync', back_populates='rule', cascade="all, delete-orphan")
    push_config = relationship('PushConfig', uselist=False, back_populates='rule', cascade="all, delete-orphan")

class Keyword(Base):
    __tablename__ = 'keywords'

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey('forward_rules.id'), nullable=False)
    keyword = Column(String, nullable=True)
    is_regex = Column(Boolean, default=False)
    is_blacklist = Column(Boolean, default=True)

    # Relationships
    rule = relationship('ForwardRule', back_populates='keywords')

    # Add unique constraint
    __table_args__ = (
        UniqueConstraint('rule_id', 'keyword','is_regex','is_blacklist', name='unique_rule_keyword_is_regex_is_blacklist'),
    )

class ReplaceRule(Base):
    __tablename__ = 'replace_rules'

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey('forward_rules.id'), nullable=False)
    pattern = Column(String, nullable=False)  # Replace pattern
    content = Column(String, nullable=True)   # Replace content

    # Relationships
    rule = relationship('ForwardRule', back_populates='replace_rules')

    # Add unique constraint
    __table_args__ = (
        UniqueConstraint('rule_id', 'pattern', 'content', name='unique_rule_pattern_content'),
    )

class MediaTypes(Base):
    __tablename__ = 'media_types'

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey('forward_rules.id'), nullable=False, unique=True)
    photo = Column(Boolean, default=False)
    document = Column(Boolean, default=False)
    video = Column(Boolean, default=False)
    audio = Column(Boolean, default=False)
    voice = Column(Boolean, default=False)

    # Relationships
    rule = relationship('ForwardRule', back_populates='media_types')


class MediaExtensions(Base):
    __tablename__ = 'media_extensions'

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey('forward_rules.id'), nullable=False)
    extension = Column(String, nullable=False)  # Store extension without dot, e.g. "jpg", "pdf"

    # Relationships
    rule = relationship('ForwardRule', back_populates='media_extensions')

    # Add unique constraint
    __table_args__ = (
        UniqueConstraint('rule_id', 'extension', name='unique_rule_extension'),
    )

class RuleSync(Base):
    __tablename__ = 'rule_syncs'

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey('forward_rules.id'), nullable=False)
    sync_rule_id = Column(Integer, nullable=False)

    # Relationships
    rule = relationship('ForwardRule', back_populates='rule_syncs')

class PushConfig(Base):
    __tablename__ = 'push_configs'

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey('forward_rules.id'), nullable=False)
    enable_push_channel = Column(Boolean, default=False)
    push_channel = Column(String, nullable=False)
    # Media send mode, one at a time Single or multiple Multiple
    media_send_mode = Column(String, nullable=False, default='Single')

    # Relationships
    rule = relationship('ForwardRule', back_populates='push_config')

class RSSConfig(Base):
    __tablename__ = 'rss_configs'

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey('forward_rules.id'), nullable=False, unique=True)
    enable_rss = Column(Boolean, default=False)  # Whether to enable RSS
    rule_title = Column(String, nullable=True)  # RSS feed title
    rule_description = Column(String, nullable=True)  # RSS feed description
    language = Column(String, default='zh-CN')  # RSS feed language
    max_items = Column(Integer, default=50)  # RSS feed maximum items
    # Whether to enable auto title and content extraction
    is_auto_title = Column(Boolean, default=False)
    is_auto_content = Column(Boolean, default=False)
    # Whether to enable AI title and content extraction
    is_ai_extract = Column(Boolean, default=False)
    # AI title and content extraction prompt
    ai_extract_prompt = Column(String, nullable=True)
    is_auto_markdown_to_html = Column(Boolean, default=False)
    # Whether to enable custom regex for title and content extraction
    enable_custom_title_pattern = Column(Boolean, default=False)
    enable_custom_content_pattern = Column(Boolean, default=False)

    # Relationships
    rule = relationship('ForwardRule', back_populates='rss_config')
    patterns = relationship('RSSPattern', back_populates='rss_config', cascade="all, delete-orphan")


class RSSPattern(Base):
    __tablename__ = 'rss_patterns'


    id = Column(Integer, primary_key=True)
    rss_config_id = Column(Integer, ForeignKey('rss_configs.id'), nullable=False)
    pattern = Column(String, nullable=False)  # Regex pattern
    pattern_type = Column(String, nullable=False)  # Pattern type: 'title' or 'content'
    priority = Column(Integer, default=0)  # Execution priority, lower number means higher priority


    # Relationships
    rss_config = relationship('RSSConfig', back_populates='patterns')

    # Add composite unique constraint
    __table_args__ = (
        UniqueConstraint('rss_config_id', 'pattern', 'pattern_type', name='unique_rss_pattern'),
    )

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False)
    password = Column(String, nullable=False)

def migrate_db(engine):
    """Database migration function, ensures new fields are added"""
    inspector = inspect(engine)

    # Get all tables in current database
    existing_tables = inspector.get_table_names()

    # Connect to database
    connection = engine.connect()

    try:
        with engine.connect() as connection:

            # If rule_syncs table does not exist, create it
            if 'rule_syncs' not in existing_tables:
                logging.info("Creating rule_syncs table...")
                RuleSync.__table__.create(engine)


            # If users table does not exist, create it
            if 'users' not in existing_tables:
                logging.info("Creating users table...")
                User.__table__.create(engine)

            # If rss_configs table does not exist, create it
            if 'rss_configs' not in existing_tables:
                logging.info("Creating rss_configs table...")
                RSSConfig.__table__.create(engine)


            # If rss_patterns table does not exist, create it
            if 'rss_patterns' not in existing_tables:
                logging.info("Creating rss_patterns table...")
                RSSPattern.__table__.create(engine)

            # If push_configs table does not exist, create it
            if 'push_configs' not in existing_tables:
                logging.info("Creating push_configs table...")
                PushConfig.__table__.create(engine)


            # If media_types table does not exist, create it
            if 'media_types' not in existing_tables:
                logging.info("Creating media_types table...")
                MediaTypes.__table__.create(engine)

                # If forward_rules table has selected_media_types column, migrate data to new table
                if 'selected_media_types' in forward_rules_columns:
                    logging.info("Migrating media type data to new table...")
                    # Query all rules
                    rules = connection.execute(text("SELECT id, selected_media_types FROM forward_rules WHERE selected_media_types IS NOT NULL"))

                    for rule in rules:
                        rule_id = rule[0]
                        selected_types = rule[1]
                        if selected_types:
                            # Create media type record
                            media_types_data = {
                                'photo': 'photo' in selected_types,
                                'document': 'document' in selected_types,
                                'video': 'video' in selected_types,
                                'audio': 'audio' in selected_types,
                                'voice': 'voice' in selected_types
                            }

                            # Insert data
                            connection.execute(
                                text("""
                                INSERT INTO media_types (rule_id, photo, document, video, audio, voice)
                                VALUES (:rule_id, :photo, :document, :video, :audio, :voice)
                                """),
                                {
                                    'rule_id': rule_id,
                                    'photo': media_types_data['photo'],
                                    'document': media_types_data['document'],
                                    'video': media_types_data['video'],
                                    'audio': media_types_data['audio'],
                                    'voice': media_types_data['voice']
                                }
                            )
            if 'media_extensions' not in existing_tables:
                logging.info("Creating media_extensions table...")
                MediaExtensions.__table__.create(engine)

    except Exception as e:
        logging.error(f'Error migrating media type data: {str(e)}')



    # Check existing columns of forward_rules table
    forward_rules_columns = {column['name'] for column in inspector.get_columns('forward_rules')}

    # Check existing columns of Keyword table
    keyword_columns = {column['name'] for column in inspector.get_columns('keywords')}

    # New columns to add and their default values
    forward_rules_new_columns = {
        'is_ai': 'ALTER TABLE forward_rules ADD COLUMN is_ai BOOLEAN DEFAULT FALSE',
        'ai_model': 'ALTER TABLE forward_rules ADD COLUMN ai_model VARCHAR DEFAULT NULL',
        'ai_prompt': 'ALTER TABLE forward_rules ADD COLUMN ai_prompt VARCHAR DEFAULT NULL',
        'is_summary': 'ALTER TABLE forward_rules ADD COLUMN is_summary BOOLEAN DEFAULT FALSE',
        'summary_time': 'ALTER TABLE forward_rules ADD COLUMN summary_time VARCHAR DEFAULT "07:00"',
        'summary_prompt': 'ALTER TABLE forward_rules ADD COLUMN summary_prompt VARCHAR DEFAULT NULL',
        'is_delete_original': 'ALTER TABLE forward_rules ADD COLUMN is_delete_original BOOLEAN DEFAULT FALSE',
        'is_original_sender': 'ALTER TABLE forward_rules ADD COLUMN is_original_sender BOOLEAN DEFAULT FALSE',
        'is_original_time': 'ALTER TABLE forward_rules ADD COLUMN is_original_time BOOLEAN DEFAULT FALSE',
        'is_keyword_after_ai': 'ALTER TABLE forward_rules ADD COLUMN is_keyword_after_ai BOOLEAN DEFAULT FALSE',
        'add_mode': 'ALTER TABLE forward_rules ADD COLUMN add_mode VARCHAR DEFAULT "BLACKLIST"',
        'enable_rule': 'ALTER TABLE forward_rules ADD COLUMN enable_rule BOOLEAN DEFAULT TRUE',
        'is_top_summary': 'ALTER TABLE forward_rules ADD COLUMN is_top_summary BOOLEAN DEFAULT TRUE',
        'is_filter_user_info': 'ALTER TABLE forward_rules ADD COLUMN is_filter_user_info BOOLEAN DEFAULT FALSE',
        'enable_delay': 'ALTER TABLE forward_rules ADD COLUMN enable_delay BOOLEAN DEFAULT FALSE',
        'delay_seconds': 'ALTER TABLE forward_rules ADD COLUMN delay_seconds INTEGER DEFAULT 5',
        'handle_mode': 'ALTER TABLE forward_rules ADD COLUMN handle_mode VARCHAR DEFAULT "FORWARD"',
        'enable_comment_button': 'ALTER TABLE forward_rules ADD COLUMN enable_comment_button BOOLEAN DEFAULT FALSE',
        'enable_media_type_filter': 'ALTER TABLE forward_rules ADD COLUMN enable_media_type_filter BOOLEAN DEFAULT FALSE',
        'enable_media_size_filter': 'ALTER TABLE forward_rules ADD COLUMN enable_media_size_filter BOOLEAN DEFAULT FALSE',
        'max_media_size': f'ALTER TABLE forward_rules ADD COLUMN max_media_size INTEGER DEFAULT {os.getenv("DEFAULT_MAX_MEDIA_SIZE", 10)}',
        'is_send_over_media_size_message': 'ALTER TABLE forward_rules ADD COLUMN is_send_over_media_size_message BOOLEAN DEFAULT TRUE',
        'enable_extension_filter': 'ALTER TABLE forward_rules ADD COLUMN enable_extension_filter BOOLEAN DEFAULT FALSE',
        'extension_filter_mode': 'ALTER TABLE forward_rules ADD COLUMN extension_filter_mode VARCHAR DEFAULT "BLACKLIST"',
        'enable_reverse_blacklist': 'ALTER TABLE forward_rules ADD COLUMN enable_reverse_blacklist BOOLEAN DEFAULT FALSE',
        'enable_reverse_whitelist': 'ALTER TABLE forward_rules ADD COLUMN enable_reverse_whitelist BOOLEAN DEFAULT FALSE',
        'only_rss': 'ALTER TABLE forward_rules ADD COLUMN only_rss BOOLEAN DEFAULT FALSE',
        'enable_sync': 'ALTER TABLE forward_rules ADD COLUMN enable_sync BOOLEAN DEFAULT FALSE',
        'userinfo_template': 'ALTER TABLE forward_rules ADD COLUMN userinfo_template VARCHAR DEFAULT "**{name}**"',
        'time_template': 'ALTER TABLE forward_rules ADD COLUMN time_template VARCHAR DEFAULT "{time}"',
        'original_link_template': 'ALTER TABLE forward_rules ADD COLUMN original_link_template VARCHAR DEFAULT "Original link: {original_link}"',
        'enable_push': 'ALTER TABLE forward_rules ADD COLUMN enable_push BOOLEAN DEFAULT FALSE',
        'enable_only_push': 'ALTER TABLE forward_rules ADD COLUMN enable_only_push BOOLEAN DEFAULT FALSE',
        'media_allow_text': 'ALTER TABLE forward_rules ADD COLUMN media_allow_text BOOLEAN DEFAULT FALSE',
        'enable_ai_upload_image': 'ALTER TABLE forward_rules ADD COLUMN enable_ai_upload_image BOOLEAN DEFAULT FALSE',
    }

    keywords_new_columns = {
        'is_blacklist': 'ALTER TABLE keywords ADD COLUMN is_blacklist BOOLEAN DEFAULT TRUE',
    }

    # Add missing columns
    with engine.connect() as connection:
        # Add columns to forward_rules table
        for column, sql in forward_rules_new_columns.items():
            if column not in forward_rules_columns:
                try:
                    connection.execute(text(sql))
                    logging.info(f'Column added: {column}')
                except Exception as e:
                    logging.error(f'Error adding column {column}: {str(e)}')


        # Add columns to keywords table
        for column, sql in keywords_new_columns.items():
            if column not in keyword_columns:
                try:
                    connection.execute(text(sql))
                    logging.info(f'Column added: {column}')
                except Exception as e:
                    logging.error(f'Error adding column {column}: {str(e)}')

        # First check if forward_rules table has forward_mode column
        if 'forward_mode' not in forward_rules_columns:
            # Rename mode column to forward_mode in forward_rules table
            connection.execute(text("ALTER TABLE forward_rules RENAME COLUMN mode TO forward_mode"))
            logging.info('Successfully renamed mode column to forward_mode in forward_rules table')

        # Update unique constraint for keywords table
        try:
            with engine.connect() as connection:
                # Check if index exists
                result = connection.execute(text("""
                    SELECT name FROM sqlite_master
                    WHERE type='index' AND name='unique_rule_keyword_is_regex_is_blacklist'
                """))
                index_exists = result.fetchone() is not None
                if not index_exists:
                    logging.info('Starting to update keywords table unique constraint...')
                    try:

                        with engine.begin() as connection:
                            # Create temporary table
                            connection.execute(text("""
                                CREATE TABLE keywords_temp (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    rule_id INTEGER,
                                    keyword TEXT,
                                    is_regex BOOLEAN,
                                    is_blacklist BOOLEAN
                                    -- If keywords table has other fields, define them here as well
                                )
                            """))
                            logging.info('Successfully created keywords_temp table structure')

                            # Copy original table data to temporary table, let database auto-generate id
                            result = connection.execute(text("""
                                INSERT INTO keywords_temp (rule_id, keyword, is_regex, is_blacklist)
                                SELECT rule_id, keyword, is_regex, is_blacklist FROM keywords
                            """))
                            logging.info(f'Successfully copied data to keywords_temp, rows affected: {result.rowcount}')

                            # Delete original keywords table
                            connection.execute(text("DROP TABLE keywords"))
                            logging.info('Successfully deleted original keywords table')

                            # Rename temporary table to keywords
                            connection.execute(text("ALTER TABLE keywords_temp RENAME TO keywords"))
                            logging.info('Successfully renamed keywords_temp to keywords')

                            # Add unique constraint
                            connection.execute(text("""
                                CREATE UNIQUE INDEX unique_rule_keyword_is_regex_is_blacklist
                                ON keywords (rule_id, keyword, is_regex, is_blacklist)
                            """))
                            logging.info('Successfully added unique constraint unique_rule_keyword_is_regex_is_blacklist')

                            logging.info('Successfully updated keywords table structure and unique constraint')
                    except Exception as e:
                        logging.error(f'Error updating keywords table structure: {str(e)}')
                else:
                    logging.info('Unique constraint already exists, skipping creation')

        except Exception as e:
            logging.error(f'Error updating unique constraint: {str(e)}')


def init_db():
    """Initialize database"""
    # Create database folder
    os.makedirs('./db', exist_ok=True)
    engine = create_engine('sqlite:///./db/forward.db')

    # First create all tables
    Base.metadata.create_all(engine)

    # Then perform necessary migrations
    migrate_db(engine)

    return engine

def get_session():
    """Create session factory"""
    engine = create_engine('sqlite:///./db/forward.db')
    Session = sessionmaker(bind=engine)
    return Session()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    engine = init_db()
    session = get_session()
    logging.info("Database initialization and migration completed.")