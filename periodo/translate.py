import json
import os
import subprocess
from pathlib import Path
from periodo import app
from tempfile import NamedTemporaryFile, gettempdir


TMPDIR = gettempdir()


class RDFTranslationError(Exception):
    def __init__(self, code=500):
        self.code = code
        super().__init__(
            ('The server is currently too busy to process this request.'
             + ' Try again in a few minutes.') if code == 503 else
            ('RDF translation failed; please contact us!')
        )


def read_file(filename):
    with open(filename, encoding='utf8') as f:
        return f.read()


def run_subprocess(command_line, out_suffix):
    sentinel = Path(TMPDIR) / 'running-jvm'
    try:
        sentinel.touch(exist_ok=False)
        try:
            app.logger.debug(
                'Running subprocess:\n%s' % ' '.join(command_line)
            )
            with NamedTemporaryFile(suffix=out_suffix, delete=False) as out:
                with NamedTemporaryFile(suffix='.err', delete=False) as err:
                    subprocess.run(
                        command_line,
                        stdout=out,
                        stderr=err,
                        encoding='utf8',
                        env={'JVM_ARGS': '-Xms256M -Xmx512M'}
                    )
                    app.logger.debug('stdout: %s' % out.name)
                    app.logger.debug('stderr: %s' % err.name)
                    return (out.name, err.name)
        finally:
            try:
                sentinel.unlink()
            except FileNotFoundError:
                pass
    except FileExistsError:
        app.logger.debug('jvm is already running; returning 503')
        raise RDFTranslationError(code=503)


def triples_to_csv(triples_file):
    return run_subprocess(
        [app.config['ARQ'],
         '--data', triples_file,
         '--query', app.config['CSV_QUERY'],
         '--results=CSV'],
        '.csv'
    )


def jsonld_to(serialization, jsonld):
    with NamedTemporaryFile(suffix='.jsonld') as f:
        f.write(json.dumps(jsonld).encode())
        f.flush()
        return run_subprocess(
            [app.config['RIOT'],
             '--syntax=jsonld',
             '--formatted=%s' % serialization,
             f.name],
            '.' + serialization
        )


def looks_like(serialization, data):
    # checking the return code is not reliable, because riot/arq will return 1
    # even if there are only warnings. So we look at the first character of
    # output as a hint
    if len(data) == 0:
        return False
    if serialization == 'ttl':
        return data[0] == '@'  # @prefix
    if serialization == 'csv':
        return data[0] == 'p'  # period
    if serialization == 'nt':
        return (data[0] == '<' or data[0] == '_')  # URI or blank node
    return False


def log_error(stdout, stderr):
    app.logger.error('stdout:\n%s' % stdout)
    app.logger.error('stderr:\n%s' % stderr)


def jsonld_to_turtle(jsonld):
    turtle_file, errors_file = jsonld_to('ttl', jsonld)
    try:
        turtle = read_file(turtle_file)
        if not looks_like('ttl', turtle):
            log_error(turtle, read_file(errors_file))
            raise RDFTranslationError()
        return turtle
    finally:
        os.remove(turtle_file)
        os.remove(errors_file)


def jsonld_to_csv(jsonld):
    triples_file, errors_file_1 = jsonld_to('nt', jsonld)
    try:
        triples = read_file(triples_file)
        if not looks_like('nt', triples):
            log_error(triples, read_file(errors_file_1))
            raise RDFTranslationError()
        csv_file, errors_file_2 = triples_to_csv(triples_file)
        try:
            csv = read_file(csv_file)
            if not looks_like('csv', csv):
                log_error(csv, read_file(errors_file_2))
                raise RDFTranslationError()
            return csv
        finally:
            os.remove(csv_file)
            os.remove(errors_file_2)
    finally:
        os.remove(triples_file)
        os.remove(errors_file_1)
