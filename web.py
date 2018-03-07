#!/usr/bin/env python

"""
Tornado Web based site template

Copyright 2010-2015 Carlos Neves <cn@sueste.net>
"""

import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket
import tornado.autoreload

import os
import logging

rootlogger = logging.getLogger()
formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s:%(message)s', '%y%m%dT%H:%M:%S')
handler = logging.handlers.TimedRotatingFileHandler('log/web.log', 'D', 1)
handler.setFormatter(formatter)
rootlogger.addHandler(handler)
rootlogger.setLevel(logging.DEBUG)

import simplejson
import datetime
import time

def json_default (o):
    if isinstance(o, datetime.datetime):
        return int(time.mktime(o.timetuple())*1000)

class BaseHandler (tornado.web.RequestHandler):
    def get_server_time(self):
        return datetime.datetime.utcnow()

    def redirect (self, where, h=None):
        if h and h.has_key('X-Scheme'):
            super(BaseHandler, self).redirect("https://%s%s" % (h['Host'], where))
        else:
            super(BaseHandler, self).redirect('%s' % where)

def finishjson (self, val):
    return self.finish(simplejson.dumps(val, use_decimal=True, default=json_default))

def finishjsonwrapper (func):
    def wrapped (self, *args, **kwargs):
        return finishjson(func(self, *args, **kwargs))
    return wrapped

class UnhandledPath (Exception):
    pass

class MainHandler(BaseHandler):
    """
    Base class for handling root paths.
    Class functions prefixed with get_ will be called with urls where the
    full path matches the remainder of the function name.
    """
    STATIC_REDIRS = ['.ico']
    HANDLE_SUBPATHS = True

    def get(self, call, x={}):
        h = self.request.headers
        if self.HANDLE_SUBPATHS:
            parsedcall = call.split('/')
            basepath = parsedcall[:-1]
            call = parsedcall[-1]
        else:
            basepath = None
        if len(call) == 0:
            call = "index"
        if hasattr(self, 'https_%s' % call):
            if h.has_key('X-Scheme') and h['X-Scheme'] != 'https':
                self.redirect("https://%s%s" % (h['Host'], h['X-Uri']))
                return
        if hasattr(self, 'get_' + str(call)):
            try:
                return getattr(self, 'get_' + str(call))(basepath)
            except UnhandledPath:
                pass
        if hasattr(self, 'json_' + str(call)):
            try:
                return finishjson(self, getattr(self, 'json_' + str(call))(basepath))
            except UnhandledPath:
                pass
        if len(filter(lambda x: call.lower().endswith(x), self.STATIC_REDIRS)):
            self.redirect('/static/' + call)
            return
        try:
            r = self.request.arguments
            r.update(x)
            self.render("%s.html" % (call), **r)
        except IOError:
            rootlogger.debug("",exc_info=True)
            raise tornado.web.HTTPError(404)

    def post (self, call="index"):
        if hasattr(self, 'https_%s' % call):
            h = self.request.headers
            if h.has_key('X-Scheme') and h['X-Scheme'] != 'https':
                raise tornado.web.HTTPError(405)
        if hasattr(self, 'post_' + str(call)):
            return getattr(self, 'post_' + str(call))()
        if hasattr(self, 'json_' + str(call)):
            return finishjson(getattr(self, 'json_' + str(call))())
        raise tornado.web.HTTPError(405)

class WebSocketHandler (tornado.websocket.WebSocketHandler):
    def register_listener (self, prefix):
        pool = self.application.websockets.setdefault(prefix, [])
        if self not in pool:
            pool.append(self)
        print 'register "%s" %d' % (prefix, len(pool))

    def unregister_listener (self, prefix=''):
        for k,v in self.application.websockets.items():
            if k.startswith(prefix):
                try:
                    v.remove(self)
                    print 'unregister "%s" %d' % (prefix, len(v))
                except ValueError:
                    pass

    def send_to_listeners (self, prefix, message):
        for k,v in self.application.websockets.items():
            print prefix, k, v
            if prefix.startswith(k):
                for l in v:
                    l.write_message('%s %s' % (prefix, message))

    def open (self):
        print 'open',len(self.application.websockets)

    def process_message (self, message):
        # Override me, simple echo as example
        self.write_message(message)

    def on_message (self, message):
        message = message.split(' ')
        if message[0] == 'listen':
            if len(message) == 1:
                message.append('')
            self.register_listener(message[1])
            self.write_message('listening on "%s"' % message[1])
        elif message[0] == 'say' and len(message) > 1:
            message = message[1:2] + [' '.join(message[2:])]
            self.send_to_listeners(message[0], message[1])
        else:
            self.process_message(' '.join(message))

    def on_close (self):
        print "close"
        self.unregister_listener()

class Application(tornado.web.Application):
    # You can use MainHandler as a base or a self contained class for handling root path
    MainHandler = None
    WebSocketHandler = None

    def __init__(self, handlers=None, mainhandler=None, wshandler=None):
        if mainhandler is not None:
            self.MainHandler = mainhandler
        if wshandler is not None:
            self.WebSocketHandler = wshandler
        handlers, settings = self.__setup__(handlers=handlers)
        tornado.options.options.logging = 'none'
        tornado.web.Application.__init__(self, handlers, **settings)
        self.websockets = {}
        self.running = True

    def __setup__ (self, BASEPATH=None, handlers=None):
        if BASEPATH is None:
            BASEPATH = os.getcwd()
        if handlers is None:
            handlers = []
        if self.WebSocketHandler is not None:
            handlers.append((r"/ws", self.WebSocketHandler))
        if self.MainHandler is not None:
            handlers.append((r"/(.*)", self.MainHandler))
        settings = dict(
            template_path=os.path.join(BASEPATH, "templates"),
            static_path=os.path.join(BASEPATH, "static"),
            debug=True,
            cookie_secret="dLu6g1QERsWsC/I44JPCRD13Niw0KUOSijLgSU2nIAs=",
        )
        return handlers, settings

    def send_to_listeners (self, prefix, message):
        for k,v in self.websockets.items():
            print prefix, k, v
            if prefix.startswith(k):
                for l in v:
                    l.write_message('%s %s' % (prefix, message))

def main(klass=None, WEBPORT=8080, handlers=None, mainhandler=None, wshandler=None):
    if klass is None:
        klass = Application
    tornado.options.options.logging = 'none'
    tornado.options.define("port", default=WEBPORT, help="run on the given port", type=int)
    tornado.options.parse_command_line()
    app = klass(handlers=handlers, mainhandler=mainhandler, wshandler=wshandler)
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.listen(tornado.options.options.port)
    logging.getLogger('tornado.access').disabled = True
    tornado.ioloop.IOLoop.instance().start()

if __name__ == "__main__":
    main(Application)
