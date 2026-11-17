"""Entry point for the shop backend. Boots the server and wires routes."""
from src.api.auth import login, check_session
from src.middleware.cache import cached_response

def start_app():
    """Start the web server and register all routes."""
    register_routes()
    run_server(port=8000)

def register_routes():
    pass

def run_server(port):
    pass
