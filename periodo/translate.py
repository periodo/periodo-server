import httpx
import random
import time
from uuid import uuid4
from periodo import app


MAXIMUM_BACKOFF = 32.0
MAXIMUM_POLLS = 10


class RDFTranslationError(Exception):
    def __init__(self, code=500):
        self.code = code
        super().__init__(
            (
                "The server is currently too busy to process this request."
                + " Try again in a few minutes."
            )
            if code == 503
            else ("RDF translation failed; please contact us!")
        )


def wait_for_translation(client: httpx.Client, url: str) -> str:
    for n in range(0, MAXIMUM_POLLS):
        try:
            response = client.get(url)
            match response.status_code:
                case httpx.codes.ACCEPTED:
                    pass
                case httpx.codes.OK:
                    return response.text
                case _:
                    app.logger.error(
                        f"Translation failed with {response.status_code}: {response.text}"
                    )
                    raise RDFTranslationError()
        except httpx.RequestError:
            pass
        wait_time = min(((2 ^ n) + (random.randrange(1000) / 1000.0)), MAXIMUM_BACKOFF)
        time.sleep(wait_time)
    app.logger.error("Translation timed out")
    raise RDFTranslationError()


def jsonld_to(serialization: str, jsonld: dict | list) -> str:
    uuid = uuid4()
    path = f"{uuid}.{serialization}"
    url = f"{app.config['TRANSLATION_SERVICE']}/{path}"

    with httpx.Client() as client:
        try:
            # wake up the translator service
            client.get(url)
        except httpx.RequestError:
            pass
        try:
            response = client.put(
                url,
                json=jsonld,
                headers={"Content-Type": "application/ld+json; charset=UTF-8"},
            )
            match response.status_code:
                case httpx.codes.ACCEPTED:
                    return wait_for_translation(client, url)
                case _:
                    app.logger.error(
                        f"Translation failed with {response.status_code}: {response.text}"
                    )
                    raise RDFTranslationError()
        except httpx.RequestError as e:
            raise RDFTranslationError() from e


def jsonld_to_turtle(jsonld: dict | list) -> str:
    return jsonld_to("ttl", jsonld)


def jsonld_to_csv(jsonld: dict | list) -> str:
    return jsonld_to("csv", jsonld)
