##
## Name:     blist.py
## Purpose:  BlitzMail mailing list classes
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##

import re, weakref

# Permission masks for group mailing lists
_list_read = 4  # Allows LIST command
_list_write = 2  # Allows LDEF and LREM commands
_list_send = 1  # Allows RCPT command

# List types
_list_group = 2
_list_private = 1


class BlitzList(object):
    def __init__(self, session, name):
        self.session = weakref.ref(session)
        self.name = name

        # This will be true if the list has not been created on the
        # server side yet.  Used to distinguish "new" lists from
        # existing ones.
        self.fresh = False
        self.cache = None

    def __repr__(self):
        return '<BlitzList: "%s">' % self.name

    def __len__(self):
        """Return the number of members currently in the list."""

        return len(self.get_members())  # Must override

    def __iter__(self):
        """Return an iterator over the membership of the list."""
        return iter(self.get_members())

    def __contains__(self, other):
        """Return true if the given object is in the list."""
        return other in self.get_members()

    def __getitem__(self, pos):
        return self.get_members()[pos]

    def match(self, who):
        """Return a list of all the positions in the members list
        which match the given expression (uses sre), empty list if not
        found."""

        expr = re.compile(who)
        return [
            p for (p, x) in enumerate(self.get_members()) if expr.search(x)
        ]

    def _save_members(self, type, lst):
        udata = str.join('\n', lst)
        if len(udata) == 0 or udata[-1] != '\n':
            udata += '\n'

        self.session()._cmd1('LDAT', '%d' % len(udata))
        self.session()._expect(50)
        self.session()._send(udata)
        self.session()._expect(10)
        self.session()._cmd2('LDEF', self.name, str(type))
        self.session()._expect(10)

        self.fresh = False

    def _remove_list(self, type):
        if not self.fresh:
            self.session()._cmd2('LREM', self.name, str(type))
            self.session()._expect(10)

        key = self.name.lower()
        if self.session().pl_cache is not None:
            try:
                del self.session().pl_cache[key]
            except KeyError:
                pass

    def _load_members(self, type):
        if self.fresh:
            return []

        self.session()._cmd2('LIST', self.name, str(type))

        out = []
        (key, data) = self.session()._expect(00, 01)

        while key != 0:
            out.append(data)
            (key, data) = self.session()._expect(00, 01)

        out.append(data)
        return out


class BlitzGroupList(BlitzList):
    def __init__(self, session, name, perms):
        BlitzList.__init__(self, session, name)

        if perms is not None:
            perms = int(perms)
            self.read = (perms & _list_read != 0)
            self.write = (perms & _list_write != 0)
            self.send = (perms & _list_send != 0)
        else:
            self.read = None
            self.write = None
            self.send = None

    def get_members(self, force=False):
        """Return a list of the members of the list, as strings."""

        if self.cache is None or force:
            self.cache = self._load_members(_list_group)

        return self.cache

    def remove(self):
        """Delete this group list from the server."""

        return self._remove_list(_list_group)

    def set_members(self, lst):
        """Set the contents of the list to the given list of strings."""

        return self._save_members(_list_group, lst)


class BlitzPrivateList(BlitzList):
    def __init__(self, session, name):
        BlitzList.__init__(self, session, name)

    def get_members(self, force=False):
        """Return a list of the members of the list, as strings."""

        if self.cache is None or force:
            self.cache = self._load_members(_list_private)

        return self.cache

    def remove(self):
        """Delete this private list from the server."""

        return self._remove_list(_list_private)

    def set_members(self, lst):
        """Set the contents of the list to the given list of strings."""
        return self._save_members(_list_private, lst)


# Here there be dragons
