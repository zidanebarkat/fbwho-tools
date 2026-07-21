"""App factory — creates and configures the Flask application."""
from flask import Flask, redirect, url_for
from config import Config


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder=str(Config.BASE_DIR / 'app' / 'templates'),
        static_folder=str(Config.BASE_DIR / 'app' / 'static'),
    )
    app.config.from_object(config_class)

    # Ensure data directory exists
    config_class.DATA_DIR.mkdir(exist_ok=True)

    # Ensure encryption key exists
    if not app.config.get('ENCRYPTION_KEY'):
        from cryptography.fernet import Fernet
        key_path = config_class.DATA_DIR / '.encryption_key'
        if key_path.exists():
            app.config['ENCRYPTION_KEY'] = key_path.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            key_path.write_text(key)
            app.config['ENCRYPTION_KEY'] = key
        # Validate the key is proper Fernet
        Fernet(app.config['ENCRYPTION_KEY'].encode() if isinstance(app.config['ENCRYPTION_KEY'], str) else app.config['ENCRYPTION_KEY'])

    # Make CSRF token available in all templates
    from app.security import generate_csrf_token
    app.jinja_env.globals['csrf_token'] = generate_csrf_token

    # Register blueprints
    from app.auth.routes import auth_bp
    from app.setup.routes import setup_bp
    from app.stream.routes import stream_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(stream_bp)

    @app.route('/')
    def root():
        from flask import session as flask_session
        from app.models.channel_config import load_channel_config
        from app.models.session import load_session

        if not flask_session.get('authenticated'):
            return redirect(url_for('auth.login'))

        config = load_channel_config()
        if not config.is_setup_done:
            return redirect(url_for('setup.setup_page'))

        tiktok = load_session()
        if not tiktok.is_active:
            return redirect(url_for('auth.qr_page'))

        return redirect(url_for('stream.dashboard'))

    return app
