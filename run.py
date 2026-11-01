"""Start TusBakalım.

    python run.py                     # development, http://localhost:5050
    gunicorn -w 2 -b 0.0.0.0:5050 run:app   # on the Pi
"""
from tusbakalim import config, create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=config.DEBUG)
