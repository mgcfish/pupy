# -*- coding: utf-8 -*-
# Copyright (c) 2015, Nicolas VERDIER (contact@n1nj4.eu)
# Pupy is under the BSD 3-Clause license. see the LICENSE file at the root of the project for the detailed licence terms

from buffer import Buffer
from network.lib import getLogger

logger = getLogger('chain')


class ReleaseChainedTransport(Exception):
    __slots__ = ()


class TransportSetupFailed(Exception):
    __slots__ = ()


class BasePupyTransport(object):
    __slots__ = (
        'downstream', 'upstream', 'stream', 'closed'
    )

    name = '?'
    credentials = []

    def __init__(self, stream, **kwargs):
        if stream is None:
            self.downstream = Buffer()
            self.upstream = Buffer()
            self.stream = None
        else:
            self.downstream = stream.downstream
            self.upstream = stream.upstream
            self.stream = stream

        self.closed = False

    @classmethod
    def customize(cls, **kwargs):
        """ return a class with some existing attributes customized """
        for name, value in kwargs.iteritems():
            if name in ["cookie", "upstream", "downstream", "stream"]:
                raise TransportError("you cannot customize the protected attribute %s"%name)
            if not hasattr(cls, name):
                raise TransportError("Transport has no attribute %s"%name)
        NewSubClass = type('Customized_{}'.format(cls.__name__), (cls,), kwargs)
        return NewSubClass

    @classmethod
    def custom(cls, **kwargs):
        return cls.customize(**kwargs)

    @classmethod
    def set(cls, **kwargs):
        return cls.customize(**kwargs)

    def close(self):
        self.closed = True
        try:
            self.on_close()
        except:
            pass

        try:
            if self.stream:
                self.stream.close()
            else:
                raise EOFError()
        except:
            raise EOFError()

    def on_connect(self):
        """
            We just established a connection. Handshake time ! :-)
        """
        pass

    def on_close(self):
        """
            called when the connection has been closed
        """
        pass

    def downstream_recv(self, data):
        """
            receiving obfuscated data from the remote client and writing deobfuscated data to downstream
        """
        raise NotImplementedError()

    def upstream_recv(self, data):
        """
            receiving clear-text data from local rpyc Stream and writing obfuscated data to upstream
        """
        raise NotImplementedError()


class TransportError(Exception):
    __slots__ = ()


class PluggableTransportError(Exception):
    __slots__ = ()


class TransportWrapper(BasePupyTransport):

    __slots__ = ('chain',)

    cls_chain = ()

    def __init__(self, stream, **kwargs):
        super(TransportWrapper, self).__init__(stream, **kwargs)

        self.chain = [
            klass(None, **kwargs) for klass in self.__class__._linearize()
        ]

        self._setup_callbacks()

    def _setup_callbacks(self):
        for idx, klass in enumerate(self.chain):
            klass.upstream.on_write_f = self._generate_write_callback(
                klass.upstream, idx, up=True)

            klass.downstream.on_write_f = self._generate_write_callback(
                klass.downstream, idx, up=False)

    @classmethod
    def _linearize(cls):
        for klass in cls.cls_chain:
            if issubclass(klass, TransportWrapper):
                for subklass in klass.cls_chain:
                    yield subklass
            else:
                yield klass

    def _generate_write_callback(self, buffer, idx, up=False):
        if up:
            return lambda: self.downstream_recv(buffer, idx+1)
        else:
            return lambda: self.upstream_recv(buffer, idx-1)

    def on_connect(self):
        for klass in self.chain:
            klass.on_connect()

    def on_close(self):
        for klass in self.chain:
            klass.on_close()

    def close(self):
        for klass in self.chain:
            try:
                klass.close()
            except:
                pass

        super(TransportWrapper, self).close()

    def downstream_recv(self, data, idx=0):
        if __debug__:
            logger.debug('downstream: recv=%s/%s',
                len(data) if data else None, idx)

        if not len(data):
            return

        if idx > len(self.chain) - 1:
            data.write_to(self.upstream)
        else:
            try:
                self.chain[idx].downstream_recv(data)
            except ReleaseChainedTransport:
                del self.chain[idx]
                self._setup_callbacks()

    def upstream_recv(self, data, idx=None):
        if __debug__:
            logger.debug('upstream: recv=%s/%s',
                len(data) if data else None, idx)

        if not len(data):
            return

        if idx is None:
            idx = len(self.chain) - 1

        if idx < 0:
            data.write_to(self.downstream)
        else:
            self.chain[idx].upstream_recv(data)


def chain_transports(*args):
    """ chain 2 or more transports in such a way that the first argument is the transport seen at network level like t1(t2(t3(...(raw_data)...)))"""
    if not args:
        raise ValueError('Nothing to chain')

    elif len(args) == 1:
        return args[0]

    class WrappedTransport(TransportWrapper):
        __slots__ = ()

        cls_chain = list(args)

    return WrappedTransport
