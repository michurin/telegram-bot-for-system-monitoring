#!/usr/bin/python2
# coding: U8


import os
import sys
import json
import string
import random
import collections
import logging
from ConfigParser import ConfigParser

from twisted.internet import reactor, protocol, defer
from twisted.web import server, resource, client, http_headers, iweb
from zope.interface import implements


__version__ = '0.0.5'


API_ROOT_URL = 'https://api.telegram.org/'


state = type('State', (), {'offset': None})()
configuration = type('Configuration', (), {
    'port': None,
    'env': {},
    'script': None,
    'echo_command': None
})()


logger = logging.getLogger(__name__)
agent = client.Agent(reactor)


# API Request: data types


class DataType(object):
    pass


class MessageText(DataType):

    def __init__(self, text):
        text_len = len(text)
        if text_len > 4096:  # Telegram API limit
            text = text[:4095] + '…'
        elif text_len < 1:  # API limitation: message can not be empty
            text = '(empty message)'
        self.value = text


class PhotoData(DataType):

    def __init__(self, data):
        self.mime_type = self.detect(data)
        if self.mime_type is None:
            raise ValueError('Can not detect image type. First bytes: {!r}'.format(data[:16]))
        self.value = data

    @staticmethod
    def detect(data):
        if data.startswith('\x89PNG\r\n\x1a\n'):
            return 'image/png'
        if data.startswith('\xff\xd8\xff'):
            return 'image/jpeg'
        if data.startswith('GIF89a'):
            return 'image/gif'
        return None


# API Request: low data level


class TypedBody(object):

    def build_headers(self, content_type):
        self.headers = {
            'User-Agent': ['Bot'],
            'Accept': ['*/*'],
            'Content-type': [content_type],
        }


class JsonBody(TypedBody):

    def __init__(self, data):
        self.body = json.dumps(data, default=lambda v: v.value)
        self.build_headers('application/json')


class MultipartBody(TypedBody):

    def __init__(self, data):
        bound = '-' * 24 + ''.join(random.choice(string.digits) for _ in range(16))
        self.build_headers('multipart/form-data; boundary=' + bound)
        parts = []
        bound_ = '--' + bound
        for data_name, data_value in data.items():
            parts.append(bound_)
            if type(data_value) is PhotoData:
                parts.append('Content-Disposition: form-data; name="{0}"; filename="{0}.png"'.format(data_name))
                parts.append('Content-Type: ' + data_value.mime_type)
            else:
                parts.append('Content-Disposition: form-data; name="{}"'.format(data_name))
            parts.append('')
            if isinstance(data_value, DataType):
                parts.append(data_value.value)
            else:
                parts.append(str(data_value))
        parts.append(bound_ + '--')
        parts.append('')
        self.body = '\r\n'.join(parts)


# API Request: high data level


class APISendRequest(object):

    def __init__(self, **data):
        self.typed_body = self.body_encoder(data)

    @property
    def url_tail(self):
        return self.api_url_part

    @property
    def headers(self):
        return self.typed_body.headers

    @property
    def body(self):
        return self.typed_body.body


class APISendMessage(APISendRequest):
    api_url_part = 'sendMessage'
    body_encoder = JsonBody


class APISendPhoto(APISendRequest):
    api_url_part = 'sendPhoto'
    body_encoder = MultipartBody


class APIGetUpdates(APISendRequest):
    api_url_part = 'getUpdates'
    body_encoder = JsonBody


# API Request: network level


class StringProducer(object):

    implements(iweb.IBodyProducer)

    def __init__(self, body):
        self.body = body
        self.length = len(self.body)  # IBodyProducer required

    def startProducing(self, consumer):
        r = consumer.write(self.body)
        return defer.succeed(None)

    def pauseProducing(self):
        pass

    def stopProducing(self):
        pass


def api_request(request):
    logger.debug('\n'.join(map(str, (
        'api_request:',
        type(request), len(request.body),
        request.url_tail,
        request.headers,
        request.body[:100])))),
    d = agent.request(
        'POST',
        configuration.base_api_url + request.url_tail,
        http_headers.Headers(request.headers),
        StringProducer(request.body)
    )
    set_timeout(d, configuration.api_request_timeout)
    return d


class CollectResponseBody(protocol.Protocol):

    def __init__(self, finished):
        self.finished = finished
        self.data = ''

    def dataReceived(self, data):
        self.data += data

    def connectionLost(self, reason):
        self.finished.callback(self.data)


def process_api_response(response):
    finished = defer.Deferred()
    response.deliverBody(CollectResponseBody(finished))
    finished.addCallback(lambda v: byteify(json.loads(v)))
    return finished


def api_communicate(data, chat_id):
    if data is None:
        return None  # Generally, it have to be Deferred, but data=None can come only from stdout of subprocess
    image_type = PhotoData.detect(data)
    if image_type is not None:
        request = APISendPhoto(chat_id=chat_id, photo=PhotoData(data))
    else:
        request = APISendMessage(chat_id=chat_id, text=MessageText(data))
    d = api_request(request)
    d.addCallback(process_api_response)
    return d


# Polling loop


def make_polling_request():
    params = {'timeout': configuration.api_polling_period}
    if state.offset is not None:
        params['offset'] = state.offset
    d = api_request(APIGetUpdates(**params))
    d.addCallback(polling_response)
    d.addErrback(polling_error)
    d.addBoth(polling_recall)


def polling_response(response):
    d = client.readBody(response)
    d.addCallback(polling_body_processor)
    return d


def polling_error(error):
    logger.warning('Polling error: %s: %s', str(error), repr(error))  # TODO sleep?


def polling_recall(ignored):
    logger.debug('Recall')
    make_polling_request()


# Processor


ChildResult = collections.namedtuple('ChildResult', ('exit_code', 'stdout', 'stderr'))


class ChildProtocol(protocol.ProcessProtocol):

    def __init__(self, finished):
        self.stdout = ''
        self.stderr = ''
        self.finished = finished

    def outReceived(self, data):
        self.stdout += data

    def errReceived(self, data):
        self.stderr += data

    def processEnded(self, status):
        self.finished.callback(ChildResult(status.value.exitCode, self.stdout, self.stderr))


def process_child_result(process_result):
    if process_result.exit_code == 0:
        # TODO: check stderr? now we left stderr if exit_code == 0
        data = process_result.stdout
        if data.rstrip() == '.':
            return None  # See special case in very beginning of api_communicate
        return process_result.stdout  # TODO: check stderr? now we left stderr if exit_code == 0
    return 'SUBPROCESS EXIT CODE: {0.exit_code}\nSTDERR: {0.stderr!r}\nSTDOUT: {0.stdout!r}'.format(process_result)


def check_user(user_id, user_name):
    if user_id in configuration.allowed_ids:
        return False  # valid user
    if user_name is None:
        return True
    if user_name in configuration.allowed_usernames:
        return False
    return True


def process_one_message(message):
    logger.debug('Polling message: %s', repr(message))
    chat_id = message['chat']['id']
    user_id = message['from']['id']
    user_name = message['from'].get('username')
    if check_user(user_id, user_name):
        api_request(APISendMessage(chat_id=chat_id, text=MessageText('User not allowed')))
        return
    text = message.get('text')
    if text is None:
        api_request(APISendMessage(chat_id=chat_id, text=MessageText('No text in message')))
        return
    if text == configuration.echo_command:
        api_request(APISendMessage(chat_id=chat_id, text=MessageText(json.dumps(message, sort_keys=True, indent=4, separators=(',', ': '), ensure_ascii=False))))
        return
    cmd = [configuration.script] + text.split()
    # TODO: timeout for subprocess? and for all it's childs? setpgrp?
    finished = defer.Deferred()
    protocol = ChildProtocol(finished)
    finished.addCallback(process_child_result)
    finished.addCallback(api_communicate, chat_id)
    finished.addErrback(lambda r, cid: api_communicate('SUBPROCESS ERROR: ' + str(r), cid), chat_id)
    env = {
        'API_CHAT_ID': str(chat_id),
        'API_USER_ID': str(user_id),
    }
    if user_name is not None:
        env['API_USERNAME'] = user_name
    env.update(configuration.env)
    reactor.spawnProcess(protocol, cmd[0], cmd, env=env, childFDs={0: 'w', 1: 'r', 2: 'r'}, uid=None, gid=None, usePTY=False)


def polling_body_processor(body_text):
    body = byteify(json.loads(body_text))
    for item in body['result']:
        state.offset = max(item['update_id'] + 1, state.offset)
        process_one_message(item['message'])


# Util


def byteify(input):
    if isinstance(input, dict):
        return {byteify(key): byteify(value) for key, value in input.iteritems()}
    elif isinstance(input, list):
        return [byteify(element) for element in input]
    elif isinstance(input, unicode):
        return input.encode('utf-8')
    else:
        return input


def timeout_canceler(passthrough, timeout_call):
    if timeout_call.active():
        timeout_call.cancel()
    return passthrough


def set_timeout(d, timeout):
    timeout_call = reactor.callLater(timeout, d.cancel)
    d.addBoth(timeout_canceler, timeout_call)


# Logging


class PrettyFormatter(logging.Formatter):

    levelcolors = {
        'DEBUG': '34',
        'INFO': '32',
        'WARNING': '33',
        'ERROR': '31',
        'CRITICAL': '41;33',
    }

    def format(self, record):
        record.level_hi_color = '\033[1;' + self.levelcolors.get(record.levelname, '43;31') + 'm'
        record.level_color = '\033[0;' + self.levelcolors.get(record.levelname, '43;31') + 'm'
        record.drop_color = '\033[0m'
        return super(PrettyFormatter, self).format(record)


def setup_logging():
    stream = getattr(sys, configuration.log_stream)
    logging.basicConfig(
        stream=stream,
        level=configuration.log_level,
        format='%(asctime)s.%(msecs)03d %(levelname)s [%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    if stream.isatty():
        for h in logging.getLogger().handlers:
            f = h.formatter
            h.setFormatter(PrettyFormatter(
                '%(level_color)s%(asctime)s.%(msecs)03ds%(drop_color)s %(level_hi_color)s%(levelname)s%(drop_color)s [%(lineno)d] %(message)s',
                f.datefmt
            ))


# HTTP server


class HTTPServer(resource.Resource):

    isLeaf = True  # any url

    def _delayedResponse(self, data, request):
        request.write(repr(data))
        request.finish()

    def render_POST(self, request):
        chat_id = request.args['chat_id'][0]
        message = request.content.read()
        d = api_communicate(message, chat_id)
        d.addCallback(self._delayedResponse, request)
        return server.NOT_DONE_YET


# MAIN


def comma_separated_config_line(l, tp=None):
    if tp is None:
        tp = str
    return set([tp(x.strip()) for x in l.split(',')])


def configure():
    cfg = ConfigParser()
    cfg.read('mbot.ini')
    configuration.base_api_url = '{}bot{}/'.format(API_ROOT_URL, cfg.get('api', 'token'))
    configuration.api_polling_period = int(cfg.get('api', 'polling_period'))
    configuration.api_request_timeout = int(cfg.get('api', 'timeout'))
    if configuration.api_request_timeout <= configuration.api_polling_period:
        raise Exception('Invalid configuration: timeout have to be bigger than polling_period')
    configuration.echo_command = cfg.get('debug', 'echo_command')
    configuration.log_level = cfg.get('logging', 'level')
    configuration.log_stream = cfg.get('logging', 'stream')
    if configuration.log_stream not in {'stdout', 'stderr'}:
        raise Exception('Logging stream %s is not valid', configuration.log_stream)
    configuration.allowed_usernames = comma_separated_config_line(cfg.get('security', 'allowed_usernames'))
    configuration.allowed_ids = comma_separated_config_line(cfg.get('security', 'allowed_ids'), int)
    configuration.port = int(cfg.get('http', 'port'))  # TODO: can be None?
    configuration.script = cfg.get('slave', 'process')
    env = os.environ
    pass_vars = comma_separated_config_line(cfg.get('slave', 'pass_environ'))
    configuration.env = {k: v for k, v in env.items() if k in pass_vars}
    if configuration.port is not None:
        configuration.env['API_PORT'] = str(configuration.port)


def main():
    configure()
    setup_logging()
    if configuration.port:
        logger.info('Run HTTP server on port %d', configuration.port)
        reactor.listenTCP(configuration.port, server.Site(HTTPServer()))
    make_polling_request()
    reactor.run()


if __name__ == '__main__':
    main()
