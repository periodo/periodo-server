from werkzeug.wsgi import LimitedStream


class StreamConsumingMiddleware(object):

    def __init__(self, app):
        self.app = app

    def __call__(self, env, start_response):
        stream = LimitedStream(env['wsgi.input'],
                               int(env.get('CONTENT_LENGTH', 0) or 0))
        env['wsgi.input'] = stream
        app_iter = self.app(env, start_response)
        try:
            stream.exhaust()
            for event in app_iter:
                yield event
        finally:
            if hasattr(app_iter, 'close'):
                app_iter.close()
