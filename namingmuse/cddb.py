"""
Simple library speaking CDDBP to CDDB servers.
This code has NOT been cleaned up yet. It's ugly.
$Id: cddb.py,v 1.39 2008/09/04 12:34:10 emh Exp $
"""

import getpass
import os
import re
import socket
from musexceptions import *

defaultserver = "freedb.freedb.org"
defaultport = 8880
defaultprotocol = 6
version = '1.28'

DEBUG = os.getenv('DEBUG')

NLTERM = '\r\n'
DOTTERM = '\r\n.\r\n'

# Socket options
BUFFERSIZE = 8192
FLUSHTIMEOUT = 0.5
REPLYTIMEOUT = 20

# General CDDB codes
CDDB_CONNECTION_TIMEOUT = 530
CDDB_ALREADY_READ = 502
CDDB_QUIT = 230

# For use before we know the context.
# What it means depends on context.
CDDB_ERROR_401 = 401 

# CDDB read reply codes
READ_OK = 210

# CDDB query reply codes
QUERY_EXACT = 200
QUERY_NOMATCH = 202
QUERY_MULTIPLE_EXACT = 210
QUERY_INEXACT = 211

# All message codes > 399 are errors
ERROR_THRESHOLD = 399

class CDDBPException(NamingMuseException):

    def __init__(self,code,resp):
        Exception.__init__(self)
        self.code=code
        self.resp=resp
        self.value = "CDDBP exception: %d %s" % (self.code, self.resp)

class SmartSocket:
    """Simple socket-like class with some extra intelligence for telnet-based
    protocols."""

    def __init__(self, dbg = False, recvsize = BUFFERSIZE):
        self.dbg = dbg
        self.recvsize = recvsize
        self.sock = None
        self.restdata = ""
        self.lastsend = ""

    def connect(self, server, port):
        "Connects to the server at the given port."
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((server, port))
        except socket.error, (errno, errstr):
            raise NamingMuseError(errstr)
            
    def flush(self):
        if self.dbg:
            print "Trashing restdata:", self.restdata
        self.restdata = ""
        self.sock.settimeout(FLUSHTIMEOUT)
        while True:
            flushed = ""
            try:
                flushed = self.sock.recv(self.recvsize)
            except socket.timeout:
                break
            if self.dbg:
                print "Trashing data:", flushed
            if flushed == "": break
        self.sock.settimeout(None)

    def send(self, message, term):
        """Sends a string to the server, returning the response terminated
        by 'term'."""
        if not self.sock:
            raise CDDBPException("trying to use smartsocket with no connection")
        
        # flush old data
        self.restdata = ""

        self.lastsend = message

        self.sock.send(message+"\n")
        if self.dbg:
            print "Send: "+message

        return self.receive(term)

    
    def receive(self,term):
        """Receives a string from the server. Blocks until 'term' has been
        received."""
        data = self.restdata
        self.sock.settimeout(REPLYTIMEOUT)
        while True:
            if term in data:
                break
            try:
                newdata = self.sock.recv(self.recvsize)
            except socket.timeout:
                raise CDDBPException(-1, "timed out waiting for reply, send: %s\nterm: '%s'\ndata: %s" %
                                (self.lastsend, term, data))
            data = data + newdata

        if self.dbg:
            print "Recv: "+data

        self.sock.settimeout(None)
        data, rest = data.split(term, 1)
        self.restdata = rest
        return data

    def disconnect(self):
        "Disconnects from the remote server."
        self.sock.close()

    def __del__(self):
        if self.sock:
            self.disconnect()

class CDDBP(object):
    "This class can speak the CDDBP protocol, level 6."
    __connected = False

    def __init__(self, user='nmuse', localhost='localhost'):
        self.sock = SmartSocket(DEBUG, BUFFERSIZE)
        self.user = getpass.getuser()
        self.localhost = socket.gethostname()
        self.client = 'namingmuse'
        
    def __decode(self,resp):
        code = int(resp[:3])
        result = resp[4:]
        return (code,result)

    def __getattribute__(self, name):
        if name in ("lscat", "sites", "query", "setproto",
                    "getRecord", "motd", "stat", "ver", "whom"):
            if not self.__connected:
                self.connect()
        return super(CDDBP, self).__getattribute__(name)
        
    def connect(self, server=defaultserver, port=defaultport):
        "Connects to the server and does the initial handshake."
        self.server = server
        self.port = port
        self.sock.connect(self.server, self.port)
        self.__connected = True
        code, resp = self.__decode(self.sock.receive("\r\n"))

        if code > ERROR_THRESHOLD:
            raise CDDBPException(code,resp)

        code, resp = self.__decode(self.sock.send("cddb hello %s %s %s %s" % \
                                                 (self.user,self.localhost,
                                                  self.client,version),
                                                 "\r\n"))
        if code > ERROR_THRESHOLD:
            raise CDDBPException(code,resp)

        #set the server proto
        self.setproto()

    def reconnect(self, server=defaultserver, port=defaultport):
        'Disconnect from server and connect again.'
        self.sock.disconnect()
        self.connect(server, port)

    def setproto(self,proto=defaultprotocol):
        '''Sets the proto level on the server.
           5 is the goodest
           6 is the goodest with UTF8 strings
        '''
        
        (code,resp)=self.__decode(self.sock.send("proto %d "%proto, "\r\n"))

        if code > ERROR_THRESHOLD:
            raise CDDBPException(code,resp)

    def lscat(self):
        "Returns a list of the CDDB music categories."
        code, resp = self.__decode(self.sock.send("cddb lscat", DOTTERM))

        if code > ERROR_THRESHOLD:
            raise CDDBPException(code,resp)

        return resp.splitlines()[1:-2]

    def sites(self):
        """Returns a list of the public CDDB servers, as (server, port,
        latitude, longitude, description) tuples."""
        code, resp = self.__decode(self.sock.send("sites", DOTTERM))

        if code > ERROR_THRESHOLD:
            raise CDDBPException(code,resp)

        res = []
        for item in resp.splitlines()[1:-2]:
            items = item.split()
            res.append((items[0],items[1],items[2],items[3],
                        ' '.join(items[4:])))

        return res

    def query(self, query):
        '''
        Query the cddb database for albums that match
        a CD Table Of Contents, consisting of playlengths in
        seconds and frames, and a generated TOC hash (cddbid).
        '''
        cddbid = query[0]
        num_tracks = query[1]

        query_str = (('%08lx %d ') % (cddbid, num_tracks))
        for i in query[2:]:
            query_str = query_str + ('%d ' % i)

        response = self.sock.send("cddb query %s" % query_str, "\r\n")
        code, data = self.__decode(response)

        if code == QUERY_NOMATCH:
            return (code, data)
        elif code in (QUERY_EXACT, QUERY_INEXACT, QUERY_MULTIPLE_EXACT):
            if code == QUERY_EXACT:
                albumlist = [data]
            else:
                recievedalbumlist = self.sock.receive(DOTTERM)
                albumlist = recievedalbumlist.splitlines()[:-2]
                if not albumlist:
                    albumlist = recievedalbumlist.splitlines()
            data = []
            for line in albumlist:
                genreid, cddbid, title = line.split(" ", 2)
                data.append({
                        "genreid": genreid,
                        "cddbid": cddbid,
                        "title": title
                        })
        elif code > ERROR_THRESHOLD:
            raise CDDBPException(code, data)
        else:
            raise NotImplementedError("unimplemented cddb code.\n" +
                "please notify namingmuse developers.\n" +
                "cddb code: %u, message: %s" % (code, data))
        
        return (code, data)

    def getRecord(self, genre, cddbid):
        'Read raw freedb record from database'
        response = self.sock.send("cddb read %s %s" \
                %(genre, cddbid), NLTERM)

        code, resp = self.__decode(response)

        if code > ERROR_THRESHOLD:
            raise CDDBPException(code, resp)
        elif code == READ_OK:
            freedbrecord = self.sock.receive(DOTTERM)
        elif code == 202: # should this happen at all?
            raise NotImplementedError("cddb202read: code %u" % code)
        else:
            raise NotImplementedError("cddb read: code %u" % code)
        freedbrecord = freedbrecord.decode('UTF-8')
        #freedbrecord = freedbrecord.encode(self.encoding, 'replace')
        return freedbrecord
        
    def motd(self):
        "Returns the message of the day from the server."
        code, resp = self.__decode(self.sock.send("motd", DOTTERM))

        if code > ERROR_THRESHOLD:
            raise CDDBPException(code,resp)

        pos = resp.find("\n")
        return resp[pos+1:-3]

    def stat(self):
        "Returns a hash table of the different server properties."
        code, resp = self.__decode(self.sock.send("stat", DOTTERM))

        if code > ERROR_THRESHOLD:
            raise CDDBPException(code,resp)

        res={}
        for item in resp.splitlines()[1:-2]:
            items = item.split(":")
            if len(items) >= 2:
                item1 = items[1].strip()
                if item1 != "":
                    res[items[0].strip()] = item1

        return res

    def ver(self):
        "Returns a (servername, version, copyright) tuple."
        code, resp = self.__decode(self.sock.send("ver", NLTERM))

        if code > ERROR_THRESHOLD:
            raise CDDBPException(code,resp)

        items = resp.split(2)
        return items

    def flush(self):
        return self.sock.flush()

    def whom(self):
        "Returns a list of (pid, client, user, ip) tuples."
        code, resp = self.__decode(self.sock.send("whom", DOTTERM))

        if code > ERROR_THRESHOLD:
            raise CDDBPException(code,resp)
        
        res = []
        for item in resp.splitlines()[2:-2]:
            items = item.split()
            if len(items) > 3:
                res.append((items[0],items[1],items[2],items[3][1:-1]))

        return res
        
    def quit(self):
        self.sock.send("quit", NLTERM)

    def __del__(self):
        try:
            self.sock.disconnect()
        except:
            pass

    # Missing: update, write
