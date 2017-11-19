from datetime import datetime
from uuid import UUID
from werkzeug.routing import BaseConverter


def isoformat(value):
    return datetime.utcfromtimestamp(value).isoformat() + '+00:00'


class UUIDConverter(BaseConverter):

    def to_python(self, s):
        return UUID(s)

    def to_url(self, uuid):
        return str(uuid)
