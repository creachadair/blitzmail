##
## Name:     berror.py
## Purpose:  Exceptions for communicating with BlitzMail.
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##


class SessionError(Exception):
    """Root class for errors in a line-oriented client session."""


class ProtocolError(SessionError):
    """An exception representing protocol errors encountered during
    interaction with a server.  The `key' field gives the numeric
    error code, the `value' field gives the descriptive text returned
    by the server."""

    def __init__(self, key, value=''):
        self.key = key
        self.value = value

    def __str__(self):
        return ` self.value `


class LostConnectionError(SessionError):
    """An exception raised when the connexion is terminated by the
    remote server."""


class NotConnectedError(SessionError):
    """An exception raised when a command is issued for a session
    that is not currently connected to a server.
    """


__all__ = [
    "SessionError", "ProtocolError", "LostConnectionError", "NotConnectedError"
]

# Here there be dragons
