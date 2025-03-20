from os import path, listdir
from shlex import shlex
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion #, AutoSuggestFromHistory
from prompt_toolkit.completion import Completer
from prompt_toolkit.completion import CompleteEvent, Completer, Completion

class MythicCompleter(Completer):
    def __init__(self, cmds):
        self.cmds = cmds
    def get_completions(self, document, complete_event):

        if len(document.text_before_cursor)<1:
            #empty line
            for a in self.cmds.keys():
                display = self.cmds[a]['cmd']
                display_meta = self.cmds[a]['description']
                yield Completion(
                    text=a,
                    start_position=0,
                    display=display,
                    display_meta=display_meta,
                )

        lex = list(map(lambda i: i[1], partial_cmd_split(document.text_before_cursor)))
        if document.text_before_cursor.endswith(' '):
            lex.append('')
        #text = document.get_word_before_cursor()
        if len(lex) < 2:
            #first word is command
            t = lex[0] if len(lex)==1 else ''
            for a in self.cmds.keys():
                if a.startswith(t):
                    display = self.cmds[a]['cmd']
                    display_meta = self.cmds[a]['description']
                    yield Completion(
                        text=a,
                        start_position=-len(t),
                        display=display,
                        display_meta=display_meta,
                    )
        elif lex[0] in self.cmds:
            params = self.cmds[lex[0]]['commandparameters']
            if lex[-1].startswith('-'):
                #parameter name
                for pi in params:
                    if pi["cli_name"].startswith(lex[-1][1:]):
                        display = pi['display_name']
                        display_meta = pi['description']
                        yield Completion(
                            text=pi["cli_name"]+' ',
                            start_position=-len(lex[-1][1:]),
                            display=display,
                            display_meta=display_meta,
                        )
            else:
                n = figure_out_the_current_param(params, lex)
                if n:
                    for c in complete_param(lex[-1], n):
                        yield c

def figure_out_the_current_param(params: list, lex: list):
    pos = len(lex)
    params = sorted(params, key=lambda d: d['ui_position'])
    n = None
    if pos > 2 and lex[-2].startswith('-'):
        #we are in a named parameter
        for pi in params:
            if pi["cli_name"] == lex[-1][1:]:
                n = pi
                break
        else:
            return
    else:
        #args count is off if named params are present
        for p in lex:
            if p.startswith('-'):
                pos-=1
        #we are in param index
        if len(params) <= pos-2:
            return
        n = params[pos-2]
    return n

def complete_file(text: str):
    # Start of current file.
    if text.startswith('~'):
        text = path.expanduser(text)
    else:
        text = './'+text
    search_dir,prefix = path.split(text)
    #prefix = path.basename(text)

    # Get all filenames.
    filenames = []
    if path.isdir(search_dir):
        for filename in listdir(search_dir):
            if filename.startswith(prefix):
                filenames.append((search_dir, filename))

    # Sort
    filenames = sorted(filenames, key=lambda k: k[1])

    # Yield them.
    for directory, filename in filenames:
        completion = filename[len(prefix) :]
        full_name = path.join(directory, filename)

        if path.isdir(full_name):
            filename += "/"
            completion += "/"

        yield Completion(
            text=completion,
            start_position=0,
            display=filename,
        )

def complete_param(text, param_info):
    if param_info['type'] == 'ChooseOne':
        for c in param_info['choices']:
            if c.startswith(text):
                yield Completion(
                    text=c,
                    start_position=-len(text)
                )
    elif param_info['type'] == 'File':
        #path
        for c in complete_file(text):
            yield c
    #else:
    #    yield Completion(
    #        text='-'+param_info['display_name']+' ',
    #        start_position=0,
    #    )

class MythicParamCompleter(Completer):
    def __init__(self, param_info):
        self.param_info = param_info
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        for c in complete_param(text, self.param_info):
            yield c

class MythicParamSuggest(AutoSuggest):
    def __init__(self, param_info):
        self.param_info = param_info
    def get_suggestion(self, buff, document):
        text = document.text_before_cursor
        for c in complete_param(text, self.param_info):
            return Suggestion(c.text)

class MythicSuggest(AutoSuggest):
    def __init__(self, cmds):
        self.cmds = cmds
    def get_suggestion(self, buff, document):# → Suggestion | None
        history = buff.history
        # Consider only the last line for the suggestion.
        text = document.text.rsplit("\n", 1)[-1]
        # Only create a suggestion when this is not an empty line.
        if text.strip():
            i = iter(partial_cmd_split(text))
            (_, cmd, _) = next(i)
            if len(cmd) < len(text):
                #cmd is fully typed
                # Find first matching line in history.
                for string in reversed(list(history.get_strings())):
                    for line in reversed(string.splitlines()):
                        if line.startswith(text):
                            return Suggestion(line[len(text) :])
                lex = [cmd]
                lex.extend(map(lambda x: x[1],i))
                if text.endswith(' '):
                    lex.append('')
                if not cmd in self.cmds:
                    return None
                params = self.cmds[cmd]['commandparameters']
                n = figure_out_the_current_param(params, lex)
                if n:
                    for c in complete_param(lex[-1], n):
                        return Suggestion(c.text)
            else:
                for line in self.cmds:
                    if line.startswith(text):
                        return Suggestion(line[len(text) :])
        return None


def partial_cmd_split(cmdline):
    lex = shlex(cmdline, posix=True)
    lex.whitespace_split = True
    lex.commenters = ''
    io = lex.instream
    while True:
        try:
            c = lex.get_token()
            if c==lex.eof:
                break
            yield (True, c, io.tell())
        except ValueError:
            c = lex.token
            yield (False, c, io.tell())
            break

class MythicLexer(Lexer):
    def __init__(self, cmds):
        self.cmds = cmds
    def lex_document(self, document):
        lines = document.lines

        def get_line(lineno: int):
            if lineno==0 and len(lines[0])>0:
                lex = iter(partial_cmd_split(lines[0]))
                (_, c, p) = next(lex)
                ret = []
                lexarr = [c]
                s = None
                if c in self.cmds:
                    s = '#00ff00'
                else:
                    s = '#ff0000'
                ret.append((s, lines[0][:p]))

                for (ok, c, np) in lex:
                    lexarr.append(c)
                    w = lines[0][p:np] # keep the line as it was - quotes etc
                    p = np
                    if ok:
                        if c.startswith('-'):
                            s = '#ff00ff'
                        elif w.startswith('"'):
                            s = '#0000ff'
                        else:
                            s = '#000000'
                            if lexarr[0] in self.cmds:
                             params = self.cmds[lexarr[0]]['commandparameters']
                             param_info = figure_out_the_current_param(params, lexarr)
                             if param_info:
                                if param_info['type'] == 'ChooseOne':
                                    if c in param_info['choices']:
                                        s = '#00ff00'
                                    else:
                                        s = '#ff0000'
                                elif param_info['type'] == 'File':
                                    c = path.expanduser(c)
                                    if path.isfile(c):
                                        s = '#00ff00'
                                    else:
                                        s = '#ff0000'
                                elif param_info['type'] == 'Number':
                                    try:
                                        int(c)
                                        s = '#00ff00'
                                    except ValueError:
                                        s = '#ff0000'
                    else:
                        s = '#ff0000'
                    ret.append((s, w))
                return ret
            try:
                return [('', lines[lineno])]
            except IndexError:
                return []

        return get_line
