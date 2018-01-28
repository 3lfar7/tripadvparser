from html import parser
from collections import deque
from htmlparser.selector import Selector
import collections.abc

__all__ = ["DataHandler", "AttrHandler", "IntHandler", "ValueHandlerError", "Collector", "CollectorError", "HTMLParser"]

class HTMLElement:
    def __init__(self, name, attrs):
        self.name = name
        self.attrs = dict(attrs)
        self.classes = set(self.attrs.get("class", "").split())
        self.data_nodes = []

    def has_class(self, name):
        return name in self.classes

    def has_attr(self, name, value=None):
        if name in self.attrs:
            if value is None:
                return True
            return self.attrs[name] == value
        return False

    def __str__(self):
        return "<{}>".format(self.name)


class HTMLTreeParser(parser.HTMLParser):
    VOID_TAGS = set(["area", "base", "br", "col", "embed", "hr", "img", "input", "keygen", "link", "meta", "param", "source", "track", "wbr"])

    def __init__(self, handler):
        super().__init__()
        self.handler = handler

    def handle_starttag(self, tag, attrs):
        if self.elements and self.elements[-1] in self.VOID_TAGS:
            self.handle_endtag(self.elements[-1].name)
        self.elements.append(HTMLElement(tag, attrs))

    def handle_endtag(self, tag):
        while self.elements:
            self.handler(self.elements)
            element = self.elements.pop()
            if element.name == tag:
                break

    def handle_data(self, data):
        if self.elements:
            self.elements[-1].data_nodes.append(data)

    def feed(self, data):
        super().feed(data)
        self.handle_endtag("")

    def reset(self):
        super().reset()
        self.elements = deque()


class ValueHandlerError(Exception):
    def __init__(self, name, message):
        super().__init__("collector '{}': {}".format(name, message))


class DataHandler:
    def __init__(self, index=0, allow_empty=False):
        self.index = index
        self.allow_empty = allow_empty

    def __call__(self, name, element):
        if element.data_nodes:
            try:
                val = element.data_nodes[self.index].strip()
            except IndexError:
                raise ValueHandlerError(name, "element does not contain data node with index {}".format(self.index))
            if not val and not self.allow_empty:
                raise ValueHandlerError(name, "data cannot be empty")
            return val
        raise ValueHandlerError(name, "element does not contain data nodes")


class AttrHandler:
    def __init__(self, name, allow_empty=False):
        self.name = name
        self.allow_empty = allow_empty

    def __call__(self, name, element):
        val = element.attrs.get(self.name)
        if val is None:
            raise ValueHandlerError(name, "element does not contain attr '{}'".format(self.name))
        if not val and not self.allow_empty:
            raise ValueHandlerError(name, "attr '{}' cannot be empty".format(self.name))
        return val


class IntHandler:
    def __init__(self, handler):
        self.handler = handler

    def __call__(self, name, element):
        try:
            return int(self.handler(name, element))
        except ValueError:
            raise ValueHandlerError(name, "value from enclosed handler is not integer")


class CollectorError(Exception):
    pass


class Collector:
    def __init__(self, selector, value_handler=None, min_pass_count=0, limit=None, default_value=None):
        self.selector = Selector(selector)
        self.value_handler = value_handler
        if isinstance(self.value_handler, collections.abc.Sequence) and len(self.selector) != len(self.value_handler):
            raise ValueError("len(selector) != len(value_handler)")
        self.min_pass_count = min_pass_count
        self.limit = limit
        self.default_value = default_value

    def __call__(self, name, elements):
        i = self.selector(elements)
        if i > -1:
            if self.value_handler:
                if isinstance(self.value_handler, collections.abc.Sequence):
                    return self.value_handler[i](name, elements[-1])
                return self.value_handler(name, elements[-1])
            return True

    def clean(self, name, result):
        if self.min_pass_count > len(result):
            raise CollectorError("the number of collector ('{}') passes ({}) is less than the minimum number of passes ({})".format(
                name, len(result), self.min_pass_count)
            )
        if result:
            if self.limit:
                if self.limit == 1:
                    return result[0]
                elif self.limit > 1:
                    return result[:self.limit]
            return result
        else:
            if self.limit == 1:
                return self.default_value
            return result if self.default_value is None else self.default_value


class HTMLParser:
    def __init__(self):
        self.disabled_collectors = set()
        self.data_init = True

    def enable(self, *names):
        self.disabled_collectors.update(names)

    def disable(self, *names):
        self.disabled_collectors.difference_update(names)

    def is_enabled(self, name):
        return not (name in self.disabled_collectors)

    def collectors(self):
        for name, val in self.__class__.__dict__.items():
            if isinstance(val, Collector):
                yield name, val

    def __call__(self, html, clean=True):
        if self.data_init:
            self.data = {}
            for name, collector in self.collectors():
                if collector.value_handler:
                    self.data[name] = []
                else:
                    self.data[name] = 0
            self.data_init = False
        self.html = html
        parser = HTMLTreeParser(self.proc_collectors)
        parser.feed(html)
        if clean:
            for name, collector in self.collectors():
                if self.is_enabled(name) and collector.value_handler:
                    self.data[name] = collector.clean(name, self.data[name])
            if hasattr(self, "clean"):
                self.clean()
            self.data_init = True

    def proc_collectors(self, elements):
        for name, collector in self.collectors():
            if self.is_enabled(name):
                val = collector(name, elements)
                if val is not None:
                    if collector.value_handler:
                        self.data[name].append(val)
                    else:
                        self.data[name] += 1
