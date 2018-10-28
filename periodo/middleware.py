class RemoveTransferEncodingHeaderMiddleware(object):

    def __init__(self, app):
        self.app = app

    def __call__(self, env, start_response):
        self.app.logger.error(env)
