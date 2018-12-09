##
## Name:     bwarn.py
## Purpose:  BlitzMail warning classes
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##
## Warnings are posted by the BlitzMail server to notify the client of
## various events such as the arrival of new mail, impending server
## shutdown, and general messages for the human user.  The server
## informs the client of the existence of warnings, and it is then the
## client's responsibility to download them.
##
import berror
import re


class BlitzWarning(object):
    """Base class for all the various warning types.  Warnings have a
    .message field that contains data provided by the server; the
    subclasses add additional behaviours as necessary.
    """

    def __init__(self, msg):
        self.message = msg

    def __repr__(self):
        return '<%s: "%s">' % (type(self).__name__, self.message)

    def __str__(self):
        return self.message


class BlitzNewMailWarning(BlitzWarning):
    """Represents a new mail message that arrives during the session.
    Objects of this class have the following fields:

    .message    -- the original status line sent by the server
    .message_id -- the message ID of the newly arrived message
    .folder_id  -- the folder ID in which the message arrived
    .position   -- the position of the new message in the folder
    """

    def __init__(self, info):
        super(BlitzNewMailWarning, self).__init__(info)
        self._parse(info)

    def _parse(self, info):
        match = re.match(r'(\d+) (\d+) (\d+)$', info)
        if not match:
            raise berror.ProtocolError('invalid new mail warning '
                                       '"%s"' % info)

        self.message_id = int(match.group(1))
        self.folder_id = int(match.group(2))
        self.position = int(match.group(3))

    def __repr__(self):
        return "<BlitzNewMailWarning: MessageID=%d, FolderID=%d, Pos=%d>" % \
               (self.message_id, self.folder_id, self.position)


class BlitzUnreadWarning(BlitzWarning):
    """This warning is posted to inform the client that there is new
    unread mail.  It appears at the beginning of a session, and also
    in concert with a "new mail" warning during a session.
    """


class BlitzMessageWarning(BlitzWarning):
    """Represents a string of human-readable text that the server
    wishes to convey to the human on whose behalf the client is
    communicating with the BlitzMail server.
    """


class BlitzShutdownWarning(BlitzWarning):
    """Represents a warning that the server is closing down soon."""


__all__ = [
    "BlitzWarning", "BlitzNewMailWarning", "BlitzUnreadWarning",
    "BlitzMessageWarning", "BlitzShutdownWarning"
]

# Here there be dragons
