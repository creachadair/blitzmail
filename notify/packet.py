##
## Name:     packet.py
## Purpose:  Packet formats for BlitzNotify implementation.
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##

import struct as _struct
from operator import or_ as _or_

# Notification service codes
NOTIFY_SERVICE = {
    'control': 0,
    'ctrl': 0,
    'reset': 0,
    'mail': 1,
    'email': 1,
    'blitzmail': 1,
    'bulletin': 2,
    'news': 2,
    'talk': 3
}

# ATP packet types
ATP_TYPE = {'req': 0x40, 'rsp': 0x80, 'rel': 0xC0}

# ATP bitmask flags
ATP_FLAG = {
    'xo': 0x20,
    'eom': 0x10,
    'sts': 0x08,
    'xcall': 0x04,
    'tid': 0x02,
    'cksum': 0x01
}

DDP_ATP_PACKET = 0x03  # DDP code for ATP packets.
ATP_HEADER_LEN = 8  # Size of ATP header, bytes.


def make_notify_req(service, userid, messid, data=None):
    """Construct a notification request.

    service   -- service type (int or str).
    userid    -- user identifier (int).
    messid    -- message identifier (int).
    data      -- opaque message data (str or None).
    """
    svc = NOTIFY_SERVICE.get(service, service)
    uid = int(userid)
    mid = int(messid)

    out = _struct.pack('>III', svc, uid, mid)
    if data is None:
        return out
    else:
        return out + str(data)


def parse_notify_req(pkt):
    """Parse a notification request.  
    
    pkt     -- raw packet data (str).

    Returns:  (service, userid, messid, data)
    """
    NOTIFY_REQ_LEN = 12  # Minimum packet size for notifications

    if len(pkt) < NOTIFY_REQ_LEN:
        raise ValueError("Invalid packet data:  Truncated header")

    (svc, uid, mid) = _struct.unpack('>III', pkt[:NOTIFY_REQ_LEN])
    return (int(svc), int(uid), int(mid), pkt[NOTIFY_REQ_LEN:])


def make_register_req(services, userid, port=0):
    """Make a registration request.

    services   -- sequence of service tags (ints or strs).
    userid     -- user identifier (int or str).
    port       -- port number to register (int).
    """
    svc = [NOTIFY_SERVICE.get(s, s) for s in services]
    uid = str(userid)
    if isinstance(userid, (int, long)):
        uid = '#' + uid

    return chr(len(uid)) + uid + \
           _struct.pack('>HI%s' % ('I' * len(svc)),
                        port, len(svc), *svc)


def parse_register_req(pkt):
    """Parse a registration request.

    pkt     -- raw packet data to be parsed.

    Returns:  (uid, port, svcs)
    """
    ulen = ord(pkt[0])
    if len(pkt) < ulen + 1:
        raise ValueError("Invalid packet data:  Truncated UID")

    uid = pkt[1:ulen + 1]
    pkt = pkt[ulen + 1:]
    port, num_svc = _struct.unpack('>HI', pkt[:6])
    fmt = '>%s' % ('I' * num_svc)
    try:
        svcs = _struct.unpack(fmt, pkt[6:])
    except struct.error:
        raise ValueError("Invalid packet data:  Scrambled service codes")

    return (uid, port, svcs)


def make_clear_req(service, userid):
    """Make a request to clear sticky notifications.

    service   -- service tag to clear (int or str).
    userid    -- user identifier (int).
    """
    svc = NOTIFY_SERVICE.get(service, service)
    uid = int(userid)

    return _struct.pack('>II', uid, svc)


def parse_clear_req(pkt):
    """Parse a request to clear sticky notifications.

    pkt     -- raw packet data to be parsed.

    Returns:  (uid, service)
    """
    try:
        return _struct.unpack('>II', pkt)
    except struct.error:
        raise ValueError("Invalid packet data")


def make_atp_packet(kind, flags, seqno, tid, udata, pdata=None):
    """Construct an AppleTalk Transaction Protocol (ATP) packet.

    Flags may be specified as a single integer or as a sequence of
    integers or flag names.  See ATP_FLAG for the set of known flag
    labels.

    The pdata parameter may be any object, but it will be converted to
    a string before transmission.
    
    kind    -- packet type (int or str).
    flags   -- flags (int or sequence).
    seqno   -- sequence number (int).
    tid     -- transaction ID (int).
    udata   -- user data (4-byte str).
    pdata   -- opaque packet data [object].
    """
    knd = ATP_TYPE.get(kind, kind)
    if isinstance(flags, (int, long)):
        flg = int(flags)
    else:
        flg = reduce(_or_, (ATP_FLAG.get(f, f) for f in flags), 0)
    seq = int(seqno)
    tid = int(tid)

    if not isinstance(udata, str) or len(udata) != 4:
        raise ValueError("User data must be a 4-character string")

    out = _struct.pack('>BBBH4s', DDP_ATP_PACKET, knd | flg, seq, tid, udata)
    if pdata is None:
        return out
    else:
        return out + str(pdata)


def parse_atp_packet(pkt):
    """Parse a raw ATP packet.

    pkt     -- raw packet data to be parsed.
    
    Returns:  (kind, flags, seqno, tid, udata, pdata)
    """
    if len(pkt) < ATP_HEADER_LEN + 1:
        raise ValueError("Invalid packet data:  Truncated header")

    (ddp_tag, kfl, seq, tid, udata) = \
              _struct.unpack('>BBBH4s', pkt[:ATP_HEADER_LEN + 1])
    pdata = pkt[ATP_HEADER_LEN + 1:]

    if ddp_tag != DDP_ATP_PACKET:
        raise ValueError("Invalid packet data:  Packet type is not ATP (%s)" %
                         ddp_tag)

    knd = kfl & 0xC0  # Extract ATP type
    flg = kfl & 0x3F  # Extract ATP flags

    # Convert ATP type back into a name
    for name, val in ATP_TYPE.iteritems():
        if val == knd:
            knd = name
            break

    # Convert flag bits into a list of names
    flags = [name for (name, val) in ATP_FLAG.iteritems() if flg & val != 0]

    return (knd, flags, seq, tid, udata, pdata)


# Here there be dragons
