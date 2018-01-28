#TODO refactor code
import re
from enum import Enum, auto

class TokenType(Enum):
    NEW_LINE = auto()
    ADD = auto()
    ASSIGN = auto()
    ADD_ASSIGN = auto()
    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    BEGIN_SCOPE = auto()
    END_SCOPE = auto()
    COMMA = auto()
    IDENTIFIER = auto()
    STRING = auto()
    FUNCTION = auto()
    VAR = auto()
    DOCUMENT_WRITE = auto()
    END = auto()


class Token:
    def __init__(self, token_type, value, line_number, position):
        self.type = token_type
        self.value = value
        self.line_number = line_number
        self.position = position

    def __str__(self):
        return "Token({}, '{}')".format(self.type, "\\n" if self.type is TokenType.NEW_LINE else self.value)


class JSInterpreterError(Exception):
    pass


class ScannerError(JSInterpreterError):
    def __init__(self, symbol, line_number, position):
        super().__init__("unknown symbol '{}' (line: {}, pos: {})".format(symbol, line_number + 1, position + 1))


class ParserError(JSInterpreterError):
    def __init__(self, token, weight):
        super().__init__("invalid syntax '{}' (line: {}, pos: {})".format(token.value, token.line_number + 1, token.position + 1))
        self.weight = weight

    def __lt__(self, other):
        return self.weight < other.weight

    def __gt__(self, other):
        return self.weight > other.weight


class NameError(JSInterpreterError):
    def __init__(self, name, line_number, position):
        super().__init__("'{}' is not defined (line: {}, pos: {})".format(name, line_number + 1, position + 1))


class FuncCallError(JSInterpreterError):
    def __init__(self, name, line_number, position):
        super().__init__("'{}' is not a function (line: {}, pos: {})".format(name, line_number + 1, position + 1))


class Scanner:
    LEXEM_PATTERNS = [
        (re.compile(r" "), None),
        (re.compile(r"\n"), TokenType.NEW_LINE),
        (re.compile(r"\+="), TokenType.ADD_ASSIGN),
        (re.compile(r"\+"), TokenType.ADD),
        (re.compile(r"="), TokenType.ASSIGN),
        (re.compile(r"\("), TokenType.LEFT_PAREN),
        (re.compile(r"\)"), TokenType.RIGHT_PAREN),
        (re.compile(r"\{"), TokenType.BEGIN_SCOPE),
        (re.compile(r"\}"), TokenType.END_SCOPE),
        (re.compile(r","), TokenType.COMMA),
        (re.compile(r"//.*|<!--.*"), None),
        (re.compile(r"document\.write"), TokenType.DOCUMENT_WRITE),
        (re.compile(r"[a-zA-Z_]\w*"), TokenType.IDENTIFIER),
        (re.compile(r"'([ 0-9()+-]*)'"), TokenType.STRING)
    ]
    KEYWORD_PATTERNS = [
        (re.compile(r"function"), TokenType.FUNCTION),
        (re.compile(r"var"), TokenType.VAR)
    ]

    def __init__(self, code):
        self.code = code
        self.pos = 0
        self.line_number = 0
        self.rel_pos = 0
        self.prev_token_type = None

    def get_next_token(self):
        while self.pos < len(self.code):
            match = None
            for pattern, token_type in self.LEXEM_PATTERNS:
                group_index = 0
                match = pattern.match(self.code, self.pos)
                if match is not None:
                    rel_pos = self.rel_pos
                    self.rel_pos += match.end() - self.pos
                    self.pos = match.end()
                    if token_type is None:
                        break
                    elif token_type is TokenType.NEW_LINE:
                        self.line_number += 1
                        self.rel_pos = 0
                        if self.prev_token_type in [TokenType.NEW_LINE, None]:
                            break
                    elif token_type is TokenType.IDENTIFIER:
                        for pattern, new_token_type in self.KEYWORD_PATTERNS:
                            new_match = pattern.fullmatch(match.group())
                            if new_match:
                                match = new_match
                                token_type = new_token_type
                                break
                    elif token_type is TokenType.STRING:
                        group_index = 1
                    self.prev_token_type = token_type
                    return Token(token_type, match.group(group_index), self.line_number, rel_pos)
            if match is None:
                raise ScannerError(self.code[self.pos], self.line_number, self.position)
        return Token(TokenType.END, "EOF", self.line_number, self.rel_pos)


# EBNFs rules:
# function_def => FUNCTION IDENTIFIER LEFT_PAREN RIGHT_PAREN BEGIN_SCOPE scope END_SCOPE
# function_call => IDENTIFIER LEFT_PAREN RIGHT_PAREN
# var => VAR IDENTIFIER (COMMA IDENTIFIER) *
# string_expr => STRING | IDENTIFIER (ADD STRING | IDENTIFIER) *
# assign => IDENTIFIER ASSIGN string_expr
# assign_plus => IDENTIFIER ASSIGN_PLUS string_expr
# document_write_call => DOCUMENT_WRITE LPAREN string_expr RPAREN
# scope => (function_def | function_call | var | assign | assign_plus | document_write_call) *
# ADD => '+'


class VarNode:
    def __init__(self, name, line_number, position):
        self.name = name
        self.line_number = line_number
        self.position = position


class VarDefNode:
    def __init__(self, variables):
        self.variables = variables


class StringExprNode:
    def __init__(self, arguments):
        self.arguments = arguments


class CodeBlockNode:
    def __init__(self, statements):
        self.statements = statements


class FuncDefNode:
    def __init__(self, name, body):
        self.name = name
        self.body = body


class FuncCallNode:
    def __init__(self, name, line_number, position):
        self.name = name
        self.line_number = line_number
        self.position = position


class AssignNode:
    def __init__(self, name, expr, line_number, position):
        self.name = name
        self.expr = expr
        self.line_number = line_number
        self.position = position


class AddAssignNode:
    def __init__(self, name, expr, line_number, position):
        self.name = name
        self.expr = expr
        self.line_number = line_number
        self.position = position


class DocumentWriteCallNode:
    def __init__(self, expr):
        self.expr = expr


class Parser:
    def get_next_token(self):
        if self.pos > -1 and self.pos < len(self.buf) - 1:
            self.pos += 1
            return self.buf[self.pos]
        token = self.scanner.get_next_token()
        self.buf.append(token)
        self.pos += 1
        return token

    def reset(self, pos):
        self.token = self.buf[pos]
        self.pos = pos

    def eat(self, token_type):
        if self.token.type is token_type:
            if token_type is TokenType.END:
                self.eaten_end = True
            self.token = self.get_next_token()
        else:
            raise ParserError(self.token, self.pos + 1)

    @property
    def eaten_token(self):
        if self.pos > 0:
            return self.buf[self.pos - 1]

    def proc_script(self):
        statements = self.proc_scope()
        if not self.eaten_end:
            try:
                self.eat(TokenType.END)
            except ParserError as e:
                self.raise_error(e)
        return statements

    def proc_scope(self):
        pos = self.pos
        rules = [
            self.proc_func_def,
            self.proc_var_def,
            self.proc_assign,
            self.proc_add_assign,
            self.proc_document_write_call,
            self.proc_func_call
        ]
        statements = []
        while True:
            found = False
            for rule in rules:
                try:
                    statements.append(rule())
                    self.skip_new_line()
                    found = True
                    break
                except ParserError as e:
                    self.raise_error(e, True)
            if not found:
                self.reset(pos)
                break
            else:
                pos = self.pos
        return CodeBlockNode(statements)

    def raise_error(self, error=None, silent=False):
        if error and (not self.error or self.error < error):
            self.error = error
        if not silent:
            raise self.error

    def proc_func_def(self):
        pos = self.pos
        try:
            self.eat(TokenType.FUNCTION)
            self.skip_new_line()
            self.eat(TokenType.IDENTIFIER)
            name = self.eaten_token.value
            self.skip_new_line()
            self.eat(TokenType.LEFT_PAREN)
            self.skip_new_line()
            self.eat(TokenType.RIGHT_PAREN)
            self.skip_new_line()
            self.eat(TokenType.BEGIN_SCOPE)
            self.skip_new_line()
            body = self.proc_scope()
            self.eat(TokenType.END_SCOPE)
            self.skip_new_line()
            return FuncDefNode(name, body)
        except ParserError as e:
            self.reset(pos)
            self.raise_error(e)

    def proc_statement_end(self):
        error = None
        for token_type in [TokenType.NEW_LINE, TokenType.END]:
            try:
                self.eat(token_type)
                error = None
                break
            except ParserError as e:
                error = e
        if error:
            self.raise_error(error)

    def proc_var_def(self):
        pos = self.pos
        try:
            variables = []
            self.eat(TokenType.VAR)
            self.skip_new_line()
            self.eat(TokenType.IDENTIFIER)
            variables.append(self.eaten_token.value)
            while True:
                prev_pos = self.pos
                self.skip_new_line()
                try:
                    self.eat(TokenType.COMMA)
                except ParserError:
                    self.reset(prev_pos)
                    break
                self.skip_new_line()
                self.eat(TokenType.IDENTIFIER)
                variables.append(self.eaten_token.value)
            self.proc_statement_end()
            return VarDefNode(variables)
        except ParserError as e:
            self.reset(pos)
            self.raise_error(e)

    def proc_string_expr_operand(self):
        error = None
        for token_type in [TokenType.STRING, TokenType.IDENTIFIER]:
            try:
                self.eat(token_type)
                error = None
                break
            except ParserError as e:
                error = e
        if error:
            self.raise_error(error)
        if self.eaten_token.type is TokenType.IDENTIFIER:
            return VarNode(self.eaten_token.value, self.eaten_token.line_number, self.eaten_token.position)
        return self.eaten_token.value

    def proc_string_expr(self):
        pos = self.pos
        try:
            arguments = []
            arguments.append(self.proc_string_expr_operand())
            while True:
                prev_pos = self.pos
                self.skip_new_line()
                try:
                    self.eat(TokenType.ADD)
                except ParserError as e:
                    self.reset(prev_pos)
                    break
                self.skip_new_line()
                arguments.append(self.proc_string_expr_operand())
            return StringExprNode(arguments)
        except ParserError as e:
            self.reset(pos)
            self.raise_error(e)

    def skip_new_line(self):
        while True:
            try:
                self.eat(TokenType.NEW_LINE)
            except ParserError:
                break

    def proc_assign(self):
        pos = self.pos
        try:
            self.eat(TokenType.IDENTIFIER)
            name = self.eaten_token.value
            line_number = self.eaten_token.line_number
            position = self.eaten_token.position
            self.skip_new_line()
            self.eat(TokenType.ASSIGN)
            self.skip_new_line()
            expr = self.proc_string_expr()
            self.proc_statement_end()
            return AssignNode(name, expr, line_number, position)
        except ParserError as e:
            self.reset(pos)
            self.raise_error(e)

    def proc_add_assign(self):
        pos = self.pos
        try:
            self.eat(TokenType.IDENTIFIER)
            name = self.eaten_token.value
            line_number = self.eaten_token.line_number
            position = self.eaten_token.position
            self.skip_new_line()
            self.eat(TokenType.ADD_ASSIGN)
            self.skip_new_line()
            expr = self.proc_string_expr()
            self.proc_statement_end()
            return AddAssignNode(name, expr, line_number, position)
        except ParserError as e:
            self.reset(pos)
            self.raise_error(e)

    def proc_func_call(self):
        pos = self.pos
        try:
            self.eat(TokenType.IDENTIFIER)
            name = self.eaten_token.value
            line_number = self.eaten_token.line_number
            position = self.eaten_token.position
            self.skip_new_line()
            self.eat(TokenType.LEFT_PAREN)
            self.skip_new_line()
            self.eat(TokenType.RIGHT_PAREN)
            self.proc_statement_end()
            return FuncCallNode(name, line_number, position)
        except ParserError as e:
            self.reset(pos)
            self.raise_error(e)

    def proc_document_write_call(self):
        pos = self.pos
        try:
            self.eat(TokenType.DOCUMENT_WRITE)
            self.eat(TokenType.LEFT_PAREN)
            self.skip_new_line()
            expr = self.proc_string_expr()
            self.skip_new_line()
            self.eat(TokenType.RIGHT_PAREN)
            self.proc_statement_end()
            return DocumentWriteCallNode(expr)
        except ParserError as e:
            self.reset(pos)
            self.raise_error(e)

    def __call__(self, code):
        self.scanner = Scanner(code)
        self.buf = []
        self.pos = -1
        self.eaten_end = False
        self.error = None
        self.token = self.get_next_token()
        return self.proc_script()


class JSInterpreter:
    def __init__(self):
        self.parser = Parser()

    def get(self, scopes, name, line_number, position):
        for scope in reversed(scopes):
            try:
                return scope[name]
            except KeyError:
                pass
        raise NameError(name, line_number, position)

    def set(self, scopes, name, value, line_number, position):
        found = False
        for scope in reversed(scopes):
            if name in scope:
                scope[name] = value
                found = True
                break
        if not found:
            raise NameError(name, line_number, position)

    def exec_code_block(self, node, scopes, first=False):
        scopes.append({})
        if first:
            scopes[0]["document.write"] = ""
        for statement in node.statements:
            if isinstance(statement, FuncDefNode):
                self.exec_func_def(statement, scopes)
            elif isinstance(statement, VarDefNode):
                self.exec_var_def(statement, scopes)
        for statement in node.statements:
            if isinstance(statement, AssignNode):
                self.exec_assign(statement, scopes)
            elif isinstance(statement, AddAssignNode):
                self.exec_add_assign(statement, scopes)
            elif isinstance(statement, DocumentWriteCallNode):
                self.exec_document_write_call(statement, scopes)
            elif isinstance(statement, FuncCallNode):
                self.exec_func_call(statement, scopes)
        if not first:
            del scopes[-1]

    def exec_var_def(self, node, scopes):
        scope = scopes[-1]
        for name in node.variables:
            scope[name] = "undefined"

    def exec_string_expr(self, arguments, scopes):
        new_arguments = []
        for arg in arguments:
            if isinstance(arg, VarNode):
                arg = self.get(scopes, arg.name, arg.line_number, arg.position)
            new_arguments.append(arg)
        return "".join(new_arguments)

    def exec_assign(self, node, scopes):
        self.set(scopes, node.name, self.exec_string_expr(node.expr.arguments, scopes), node.line_number, node.position)

    def exec_add_assign(self, node, scopes):
        self.set(scopes, node.name, self.get(scopes, node.name, node.line_number, node.position) + self.exec_string_expr(node.expr.arguments, scopes), node.line_number, node.position)

    def exec_document_write_call(self, node, scopes):
        scopes[0]["document.write"] += self.exec_string_expr(node.expr.arguments, scopes)

    def exec_func_def(self, node, scopes):
        scopes[-1][node.name] = node.body

    def exec_func_call(self, node, scopes):
        body = self.get(scopes, node.name, node.line_number, node.position)
        if isinstance(body, str):
            raise FuncCallError(node.name, node.line_number, node.position)
        self.exec_code_block(body, scopes)

    def __call__(self, code):
        scopes = []
        try:
            self.exec_code_block(self.parser(code), scopes, True)
        except JSInterpreterError:
            # print(code)
            raise
        return scopes[0]["document.write"]
