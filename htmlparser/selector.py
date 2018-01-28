import re
from enum import Enum, auto

class TokenType(Enum):
    IDENTIFIER = auto()
    DOT = auto()
    LEFT_BRACKET = auto()
    RIGHT_BRACKET = auto()
    EQUAL = auto()
    STRING = auto()
    COLON = auto()
    COMMA = auto()
    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    SPACE = auto()
    END = auto()


class Token:
    def __init__(self, token_type, value, position):
        self.type = token_type
        self.value = value
        self.position = position

    def __str__(self):
        return "Token({}, '{}')".format(self.type, self.value)


class ScannerError(Exception):
    def __init__(self, symbol, position):
        super().__init__("unknown symbol '{}' on position {}".format(symbol, position))


class ParserError(Exception):
    def __init__(self, token, weight):
        super().__init__("invalid syntax '{}' on position {}".format(token.value, token.position + 1))
        self.weight = weight

    def __lt__(self, other):
        return self.weight < other.weight

    def __gt__(self, other):
        return self.weight > other.weight


class Scanner:
    LEXEM_PATTERNS = [
        (re.compile(r"[a-zA-Z_][\w-]*"), TokenType.IDENTIFIER),
        (" ", TokenType.SPACE),
        (".", TokenType.DOT),
        ("[", TokenType.LEFT_BRACKET),
        ("]", TokenType.RIGHT_BRACKET),
        ("(", TokenType.LEFT_PAREN),
        (")", TokenType.RIGHT_PAREN),
        ("=", TokenType.EQUAL),
        (":", TokenType.COLON),
        (",", TokenType.COMMA),
        (re.compile(r"'[^']*'|\"[^\"]*\""), TokenType.STRING)
    ]

    def __call__(self, string):
        tokens = []
        next_pos = 0
        while next_pos < len(string):
            val = None
            pos = next_pos
            for pattern, token_type in self.LEXEM_PATTERNS:
                if isinstance(pattern, str):
                    if string.startswith(pattern, next_pos):
                        val = pattern
                        next_pos += len(pattern)
                else:
                    match = pattern.match(string, next_pos)
                    if match:
                        val = match.group()
                        next_pos = match.end()
                if val is not None:
                    if token_type is TokenType.STRING:
                        val = val[1:-1]
                    tokens.append(Token(token_type, val, pos))
                    break
            if val is None:
                raise ScannerError(string[next_pos], next_pos + 1)
        tokens.append(Token(TokenType.END, "EOF", next_pos))
        return tokens


class Parser:
    scanner = Scanner()

    def eat(self, token_type):
        if self.buf[self.pos].type is token_type:
            self.pos += 1
        else:
            self.raise_error(ParserError(self.buf[self.pos], self.pos))

    def raise_error(self, error):
        if self.error is None:
            self.error = error
        else:
            if error > self.error:
                self.error = error
        raise self.error

    @property
    def eaten_token(self):
        return self.buf[self.pos - 1]

    def proc_class_selector(self):
        pos = self.pos
        try:
            self.eat(TokenType.DOT)
            self.eat(TokenType.IDENTIFIER)
            return ClassSelector(self.eaten_token.value)
        except ParserError:
            self.pos = pos
            raise

    def proc_attr_selector(self):
        pos = self.pos
        try:
            self.eat(TokenType.LEFT_BRACKET)
            self.skip_spaces()
            self.eat(TokenType.IDENTIFIER)
            name = self.eaten_token.value
            self.skip_spaces()
            prev_pos = self.pos
            try:
                self.eat(TokenType.EQUAL)
                self.skip_spaces()
                self.eat(TokenType.STRING)
                value = self.eaten_token.value
                self.skip_spaces()
            except ParserError:
                self.pos = prev_pos
                value = None
            self.eat(TokenType.RIGHT_BRACKET)
            return AttrSelector(name, value)
        except ParserError:
            self.pos = pos
            raise

    def proc_not_pseudo_class_arg(self):
        for i, rule in enumerate([self.proc_class_selector, self.proc_attr_selector]):
            try:
                return rule()
            except ParserError:
                if i == 1:
                    raise

    def proc_not_pseudo_class(self):
        pos = self.pos
        try:
            self.eat(TokenType.COLON)
            self.eat(TokenType.IDENTIFIER)
            self.eat(TokenType.LEFT_PAREN)
            self.skip_spaces()
            selectors = []
            selectors.append(self.proc_not_pseudo_class_arg())
            while True:
                prev_pos = self.pos
                self.skip_spaces()
                try:
                    self.eat(TokenType.COMMA)
                except ParserError:
                    self.pos = prev_pos
                    break
                self.skip_spaces()
                selectors.append(self.proc_not_pseudo_class_arg())
            self.skip_spaces()
            self.eat(TokenType.RIGHT_PAREN)
            return NotPseudoClass(selectors)
        except ParserError:
            self.pos = pos
            raise

    def skip_spaces(self):
        while True:
            try:
                self.eat(TokenType.SPACE)
            except ParserError:
                break

    def proc_selector_chain(self):
        rules = [
            self.proc_class_selector,
            self.proc_attr_selector,
            self.proc_not_pseudo_class
        ]
        selectors = []
        self.eat(TokenType.IDENTIFIER)
        selectors.append(TagSelector(self.eaten_token.value))
        while True:
            found = False
            for rule in rules:
                try:
                    selectors.append(rule())
                    found = True
                    break
                except ParserError:
                    pass
            if not found:
                break
        return SelectorChain(selectors)

    def proc_selector_list(self):
        selectors = []
        selectors.append(self.proc_selector_chain())
        pos = self.pos
        while True:
            try:
                self.eat(TokenType.SPACE)
                self.skip_spaces()
            except ParserError:
                break
            try:
                selectors.append(self.proc_selector_chain())
            except ParserError:
                self.pos = pos
                raise
        return SelectorList(selectors)

    def proc_selector_group(self):
        selectors = []
        try:
            selectors.append(self.proc_selector_list())
        except ParserError:
            pass
        else:
            while True:
                pos = self.pos
                self.skip_spaces()
                try:
                    self.eat(TokenType.COMMA)
                except ParserError:
                    self.pos = pos
                    break
                self.skip_spaces()
                selectors.append(self.proc_selector_list())
        self.eat(TokenType.END)
        return SelectorGroup(selectors)

    def __call__(self, string):
        self.error = None
        self.buf = self.scanner(string)
        self.pos = 0
        self.skip_spaces()
        return self.proc_selector_group()


class TagSelector:
    def __init__(self, name):
        self.name = name

    def __call__(self, element):
        return element.name == self.name


class ClassSelector:
    def __init__(self, name):
        self.name = name

    def __call__(self, element):
        return element.has_class(self.name)


class AttrSelector:
    def __init__(self, name, value=None):
        self.name = name
        self.value = value

    def __call__(self, element):
        return element.has_attr(self.name, self.value)


class NotPseudoClass:
    def __init__(self, selectors):
        self.selectors = selectors

    def __call__(self, element):
        return all(not selector(element) for selector in self.selectors)


class SelectorChain:
    def __init__(self, selectors):
        self.selectors = selectors

    def __call__(self, element):
        return all(selector(element) for selector in self.selectors)


class SelectorList:
    def __init__(self, selectors):
        self.selectors = selectors

    def __call__(self, elements):
        i = len(self.selectors) - 1
        first = True
        for element in reversed(elements):
            selector = self.selectors[i]
            if selector(element):
                i -= 1
                if i < 0:
                    return True
            elif first:
                break
            first = False
        return False


class SelectorGroup:
    def __init__(self, selectors):
        self.selectors = selectors

    def __call__(self, elements):
        for i, selector in enumerate(self.selectors):
            if selector(elements):
                return i
        return -1

    def __len__(self):
        return len(self.selectors)


class Selector:
    parser = Parser()

    def __init__(self, string):
        self.selector_group = self.parser(string)

    def __call__(self, elements):
        return self.selector_group(elements)

    def __len__(self):
        return len(self.selector_group)
