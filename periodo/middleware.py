class RemoveTransferEncodingHeaderMiddleware(object):
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        environ.pop("HTTP_TRANSFER_ENCODING", None)
        return self.app(environ, start_response)
