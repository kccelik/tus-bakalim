"""TusBakalım - TUS question bank with login, progress and spaced repetition."""
import os


def create_app():
    from flask import Flask

    from . import config
    from .storage import progress
    from .web import auth, questions, study

    os.makedirs(config.INSTANCE_DIR, exist_ok=True)
    app = Flask(__name__)
    auth.configure(app)
    progress.init_db()

    app.register_blueprint(auth.bp)
    app.register_blueprint(questions.bp)
    app.register_blueprint(study.bp)
    app.teardown_appcontext(progress.close_db)
    return app
