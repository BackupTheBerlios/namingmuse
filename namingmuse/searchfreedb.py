"""A module for searching the freedb albums using
a full text search interface, and tagging an album
with the resulting information. Fields that can be
searched are artist, title, track and rest.
"""

import htmllib
import os
import re
import sys
import terminal
import urllib
from HTMLParser import HTMLParser

from providers import FreeDBAlbumInfo
from providers import LocalAlbumInfo

from musexceptions import *

DEBUG = os.getenv('DEBUG')

baseurl = "http://www.freedb.org/"
allfields = ("artist", "title", "track", "rest")
defaultfields = ('artist', 'title')

class FreedbSearchParser(HTMLParser):
    "Class for parsing the search page"

    def __init__(self):
        HTMLParser.__init__(self)
        self.albums = []    # for using (keeps sort order)
        self.albumdict = {} # for uniqueness checking
        adr = baseurl + "freedb/"
        #self.rexadr = re.compile(adr + "\?cat=(?P<genreid>[^\s]+)\&id=(?P<cddbid>[a-f0-9]+)")
        self.rexadr = re.compile(adr + r'(?P<genreid>[a-z]+)/(?P<cddbid>[a-f0-9]+)')

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            dattrs = dict(attrs)
            if 'href' in dattrs:
                match = self.rexadr.match(dattrs["href"])
                if match:
                    album = match.groups()
                    if not self.albumdict.has_key(album):
                        self.albums.append(album)
                        self.albumdict[album] = True
    
    def getAlbums(self):
        return self.albums
    
    albums = property(getAlbums)

def searchalbums(albumdir, searchwords, searchfields, cddb):
    if len(searchfields) == 0:
        searchfields = defaultfields

    doc = baseurl + "freedb_search.php"
    query = [
             ("words", " ".join(searchwords)),
             ("allcats", "YES"),
             ("grouping", "none"),
             ("x", 0),
             ("y", 0)
            ] + [
             ("fields", f) for f in searchfields
            ]
    querystr = urllib.urlencode(query)
    url = doc + "?" + querystr

    searchres = urllib.urlopen(url)
    htmldata = searchres.read()
    searchres.close()

    if DEBUG:
        fd = file("search.html", "w")
        fd.write(htmldata)
        fd.close()

    # Parse HTML for album links
    parser = FreedbSearchParser()
    parser.feed(htmldata)
    
    # Filter and make FreeDBAlbumInfos
    songcount = len(LocalAlbumInfo(albumdir).tracks)
    albums = filterBySongCount(parser.albums, songcount)
    albums = [FreeDBAlbumInfo(cddb, genre, cddbid) for genre, cddbid in albums]
    return albums

def filterBySongCount(albums, songcount):
    retalbums = []
    for album in albums:
        genre, cddbid = album
        try:
            cddbid = int(cddbid, 16)
        except ValueError:
            raise NamingMuseError("invalid cddbid " + cddbid)
        sct = cddbid % 0x100
        if sct == songcount:
            retalbums.append(album)
        elif DEBUG:
            print "%s filtered, had %u tracks, wanted %u" % (cddbid, sct, songcount)
           
    return retalbums
