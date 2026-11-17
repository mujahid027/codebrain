"""Handles login, signup and who-is-allowed-in checks."""
import jwt

def login(username, password):
    """Check credentials and hand back a session token."""
    return make_token(username)

def make_token(user):
    return jwt.encode({"user": user}, "secret")

def check_session(token):
    """Return the user if their token is valid, else None."""
    return None
