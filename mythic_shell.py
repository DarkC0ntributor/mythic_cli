#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Rum commands via a Mythic callback
"""

from mythic import mythic, mythic_utilities
from sys import exit, stdin
from asyncio import get_event_loop, all_tasks, gather, create_task, CancelledError, run, sleep
from argparse import ArgumentParser
from os import path, listdir
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from datetime import datetime
import signal
from traceback import print_exception
from shlex import shlex, split as shell_parse
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion #, AutoSuggestFromHistory
from prompt_toolkit.completion import Completer
from prompt_toolkit.history import FileHistory
from prompt_toolkit.shortcuts import print_formatted_text, set_title
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.validation import Validator
from uuid import UUID

def sizeof_fmt(num, suffix="B"):
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"

#async def ainput(prompt: str = "") -> str:
#    with ThreadPoolExecutor(1, "AsyncInput") as executor:
#        return await get_event_loop().run_in_executor(executor, input, prompt)

parser = ArgumentParser(description=__doc__)
parser.add_argument('--user', type=str, help='Mythic user name (def: mythic_admin)', default='mythic_admin')
parser.add_argument('--host', type=str, help='Mythic IP (def: localhost)', default='127.0.0.1')
parser.add_argument('--port', type=int, help='Mythic Port (def: 7443)', default=7443)
parser.add_argument('callback', type=int, help='Callback ID', nargs='?')
parser.add_argument('--history', type=str, help='historyfile (def: ./.mythic_history)', default='./.mythic_history')
args = parser.parse_args()

histfile = FileHistory(path.expanduser(args.history))

async def select_callback(mythic_instance, columns):
    ait = await mythic.get_all_active_callbacks(mythic_instance, "id host user os architecture description payload { payloadtype { name } } last_checkin")
    agentlist = []
    colwidth = [0,7,4,4,9,4,2,4]
    for item in ait:
        d = datetime.now() - datetime.fromisoformat(item['last_checkin'][:19])
        if d.total_seconds() < 300:
            d = f"{d.total_seconds()}s"
        else:
            hours, remainder = divmod(d.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            d = '{}h {}m {}s'.format(int(hours), int(minutes), int(seconds))

        agentlist.append({
            'id': str(item['id']),
            'agent': item['payload']['payloadtype']['name'],
            'user': item['user'],
            'host': item['host'],
            'date': d,
            'arch': item['architecture'],
            'os': item['os'],
            'desc': item['description'],
        })
        for i,c in enumerate(agentlist[-1].values()):
            if len(c) > colwidth[i]:
                colwidth[i] = len(c)
    w = sum(colwidth)+6*3
    if w > columns:
        #make stuff smaller
        if colwidth[6] > 13:
            w -= colwidth[6] - 13
            colwidth[6] = 13
        if w > columns:
            colwidth[7] -= 1+w-columns

    form = []
    i = 0
    for c in ('#','payload','user@host','Last Seen','arch','os','desc'):
        if i > 0:
            form.append(('',' | '))
        if i==2:
            c = 'user'.rjust(colwidth[2])+'@'+'host'.ljust(colwidth[3])
            i+=1
        else:
            c = c.ljust(colwidth[i])
        form.append(('underline', c))
        i+=1
    print_formatted_text(FormattedText(form))

    for item in agentlist:
        print_formatted_text(FormattedText([
            ('#00ff00 bold',item['id'].ljust(colwidth[0])),
            ('',' | '),
            ('',item['agent'].ljust(colwidth[1])),
            ('',' | '),
            ('#00cccc',item['user'].rjust(colwidth[2])),
            ('','@'),
            ('#ffcc00 bold',item['host'].ljust(colwidth[3])),
            ('',' | '),
            ('#0000ff',item['date'].ljust(colwidth[4])),
            ('',' | '),
            ('#cccccc',item['arch'].ljust(colwidth[5])),
            ('',' | '),
            ('',item['os'][:colwidth[6]].ljust(colwidth[6])),
            ('',' | '),
            ('',item['desc'][:colwidth[7]].ljust(colwidth[7])),
        ]))

async def gather_help_info(mythic_instance, cb_id):
    cmd_fields = 'cmd commandparameters { cli_name choices display_name description required default_value ui_position type } description help_cmd supported_ui_features'
    query = 'query CurrentCommands($callback_id: Int!){callback(where: {id: {_eq: $callback_id} }){' \
        +' payload { payloadtype { name } payloadcommands { command { '+cmd_fields+' } } }' \
        +' loadedcommands { command { cmd } }' \
        +' host user os last_checkin' \
        +'} } '
    item = (await mythic_utilities.graphql_post(
        mythic=mythic_instance, query=query, variables={"callback_id": cb_id}
    ))['callback'][0]

    item['payload']['payloadcommands'] = dict(map(lambda x: (x['command']['cmd'], x['command']), item['payload']['payloadcommands']))
    
    #add help and cb
    item['payload']['payloadcommands']['help'] = {
        'cmd':'help',
        'description':'(Local) Show a help',
        'help_cmd':'help [cmd]',
        'supported_ui_features':[],
        'commandparameters':[{
            'display_name':'cmd',
            'cli_name':'cmd',
            'default_value':'',
            'required':False,
            'choices':list(item['payload']['payloadcommands'].keys()),
            'description':'cmd',
            'ui_position':0,
            'type':'ChooseOne'
        }]
    }
    item['payload']['payloadcommands']['cb'] = {
        'cmd':'cb',
        'description':'(Local) switch to callback number',
        'help_cmd':'cb [#]',
        'supported_ui_features':[],
        'commandparameters':[{
            'display_name':'nr',
            'cli_name':'nr',
            'default_value':'',
            'required':False,
            'choices':[],
            'description':'callback number',
            'ui_position':0,
            'type':'Number'
        }]
    }
    return item

async def print_help(cb_info, cmd):
    #help
    print(f"User: {cb_info['user']}\r\nHost: {cb_info['host']}\r\nOS: {cb_info['os']}\r\nLast Checkin: {cb_info['last_checkin']}\r\n")
    print(f"Payload: {cb_info['payload']['payloadtype']['name']}")

    loaded = list(map(lambda c: c['command']['cmd'], cb_info['loadedcommands']))

    ait = cb_info['payload']['payloadcommands']
    if len(cmd)>1:
        detailed = cmd[1]
        cmd = ait[detailed]
        print(cmd['cmd'])
        if cmd['cmd'] not in loaded:
            print("not loaded")
        print(cmd['description'])
        print(cmd['help_cmd'])
        cmd['commandparameters'] = sorted(cmd['commandparameters'], key=lambda d: d['ui_position'])
        for arg in cmd['commandparameters']:
            print(f"- {arg['display_name']}")
            print(f"\t{arg['cli_name']}", end='')
            d = arg['default_value']
            if d:
                print(f" = {d}", end='')
            c = arg['choices']
            if c:
                c='|'.join(c)
                print(f" ({c})", end='')
            print()
            print(f"\t{arg['description']}")
        else:
            print("command not found")
        return
    #cmd list
    for cmd in ait.values():
        c = cmd['cmd']
        if c not in loaded:
            c += '*'
        desc = cmd['description']
        de = desc.find('. ')
        if de>0:
            desc=desc[:de+2]
        cmd['commandparameters'] = sorted(cmd['commandparameters'], key=lambda d: d['ui_position'])
        for arg in cmd['commandparameters']:
            n = arg['cli_name']
            if arg['choices']:
                ch='|'.join(arg['choices'])
                n = f"({ch})"
            if (not arg['required']) or arg['default_value']:
                n = f"[{n}]"
            c+=" "+n
        print(f"{c}\n\t{desc}")
    
    print("\nUse \"help <cmd>\" for a full help")

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

async def scripting():
    mythic_instance = None
    try:
        pw = await PromptSession().prompt_async(args.user+"'s PW: ", is_password=True)

        mythic_instance = await mythic.login(
            username=args.user,
            password=pw,
            server_ip=args.host,
            server_port=args.port,
            #logging_level=41
        )
    except Exception as e:
        print_formatted_text(FormattedText([('#ff0000',str(e))]))
        #print(f"\033[0;31m{str(e)}\033[0m")
        return

    if args.callback is None:
        s = PromptSession()
        await select_callback(mythic_instance, s.output.get_size().columns)
        args.callback = int(await s.prompt_async('cb# ',
                    is_password=False,
                    enable_history_search=False))
    
    cb_info = await gather_help_info(mythic_instance, args.callback)

    set_title(f"{cb_info['user']}@{cb_info['host']} - {cb_info['payload']['payloadtype']['name']}/{cb_info['os']}")

    session = PromptSession(history=histfile)
    while True:
     with patch_stdout():
        cmd = ""
        try:
            cmd = await session.prompt_async(f"{cb_info['user']}@{cb_info['host']}> ",
                    is_password=False,
                    rprompt=f"{cb_info['payload']['payloadtype']['name']}/{cb_info['os']}",
                    lexer=MythicLexer(cb_info['payload']['payloadcommands']),
                    completer=MythicCompleter(cb_info['payload']['payloadcommands']),
                    auto_suggest=MythicSuggest(cb_info['payload']['payloadcommands']),
                    enable_history_search=True,
                    complete_while_typing=True,
                    #search_ignore_case
                    )
        except KeyboardInterrupt:
            continue
        except (CancelledError, EOFError):
            print("exit")
            cmd = 'exit'
        if cmd == 'exit':
            break

        cmd = shell_parse(cmd)
        
        if len(cmd)==0:
            continue

        if cmd[0] == "help":
            await print_help(cb_info, cmd)
            continue

        if cmd[0] == "cb":
            if len(cmd)==2:
                args.callback = int(cmd[1])
                cb_info = await gather_help_info(mythic_instance, args.callback)
                set_title(f"{cb_info['user']}@{cb_info['host']} - {cb_info['payload']['payloadtype']['name']}/{cb_info['os']}")
            else:
                await select_callback(mythic_instance, session.output.get_size().columns)
            continue

        try:
            cmdargs = {}
            cmd_info = None
            try:
                cmd_info = cb_info['payload']['payloadcommands'][cmd[0]]
            except KeyError:
                raise ValueError(f"{cmd[0]} is not a known command")
            param_info = sorted(cmd_info['commandparameters'], key=lambda d: d['ui_position'])
            pos = 0
            while pos < len(cmd)-1:
                v = cmd[1+pos]
                n = param_info[pos]
                if v[0]=='-':
                    pos += 1
                    n = v.lstrip('-')
                    for pi in param_info:
                        if pi["cli_name"] == n:
                            n = pi
                            break
                    else:
                        raise ValueError(f"unknown parameter {n}\r\n{cmd_info['help_cmd']}")
                    v = cmd[1+pos]
                
                if n["type"] == "Array" and len(param_info) == pos+1:
                    #last param is array
                    cmdargs[n['cli_name']] = cmd[1+pos:]
                    break

                cmdargs[n['cli_name']] = v
                pos += 1

            for pi in param_info:
                if pi["required"]:
                    n = pi['cli_name']
                    if n not in cmdargs:
                        try:
                            cmdargs[n] = await PromptSession().prompt_async(n+': ',
                                completer=MythicParamCompleter(pi),
                                auto_suggest=MythicParamSuggest(pi),
                                complete_while_typing=True,
                                validator=Validator.from_callable(lambda t: False if not t else True, error_message='Invalid input')
                                )
                        except KeyboardInterrupt:
                            raise StopIteration
                
                t = pi['type']
                if t == 'File':
                    try:
                        UUID(cmdargs[n])
                    except ValueError:
                        cmdargs[n] = path.expanduser(cmdargs[n])
                        with open(cmdargs[n], 'rb') as f:
                            cmdargs[n] = await mythic.register_file(
                                mythic=mythic_instance,
                                filename = path.basename(cmdargs[n]),
                                contents = f.read())                        
                        print(f"uploaded file to mythic. File UUID: {cmdargs[n]}")
                elif t == 'Number':
                    cmdargs[n] = int(cmdargs[n])
                elif t == 'ChooseOne':
                    c = n['choices']
                    if len(c)>0:
                        if cmdargs[n] in c:
                            pass
                        else:
                            raise ValueError(f"{n['cli_name']} must be one of {c}\r\n{cmd_info['help_cmd']}")

            #print(f"running: {cmd[0]} {cmdargs}")
            print_formatted_text(FormattedText([('#cccccc',f"running: {cmd[0]} {cmdargs}")]))

            task = await mythic.issue_task(
                mythic=mythic_instance,
                command_name=cmd[0],
                parameters=cmdargs,
                callback_display_id=args.callback,
                timeout=60,
                #wait_for_complete=True,
            )
            if task is not None:
                print(f"Issued a task: {task}")
                try:
                    for f in cmd_info['supported_ui_features']:
                        if f == "file_browser:list":
                            list_fut = create_task(print_res_files(mythic_instance, task))
                            await mythic.waitfor_task_complete(
                                    mythic=mythic_instance,
                                    task_display_id=task["display_id"],
                                )
                            await sleep(0.5)
                            list_fut.cancel()
                            break
                        elif f == "process_browser:list":
                            list_fut = create_task(print_res_procs(mythic_instance, task))
                            await mythic.waitfor_task_complete(
                                    mythic=mythic_instance,
                                    task_display_id=task["display_id"],
                                )
                            list_fut.cancel()
                            break
                        elif f == "file_browser:download":
                            await print_res_download(mythic_instance, task)
                            break
                        #"file_browser:remove"
                        #"file_browser:upload"
                    else:
                        #no feature
                        await print_res(mythic_instance, task)
                except KeyboardInterrupt:
                    pass
        except StopIteration:
            pass
        except Exception as e:
            print_exception(e)
            print_formatted_text(FormattedText([('#ff0000',str(e))]))
            #print(f"\033[0;31m{str(e)}\033[0m")

async def print_res(mythic_instance, task):
    output = await mythic.waitfor_for_task_output(
        mythic=mythic_instance, task_display_id=task["display_id"], timeout=60
    )
    if output == b"":
        print_formatted_text(FormattedText([('#00ff00','∅')]))
    else:
        # just a (bin) string
        print(output.decode())

async def print_res_files(mythic_instance, task):
    print_path = 0
    async for item in mythic.subscribe_new_filebrowser(mythic=mythic_instance):
     for f in item:
      try:
        #print_formatted_text(FormattedText([('#cccccc',str(f))]))
        if f['task_id'] != task["display_id"]:
            continue
        if print_path < len(f['parent_path_text']):
            print_path = len(f['parent_path_text'])
            print_formatted_text(FormattedText([
                ('italic',f['parent_path_text']),
                ('',"\n    "),
                ('underline',"Size"),
                ('',' '),
                ('underline',"Date Modified"),
                ('',' '),
                ('underline',"Name"),
            ]))
        elif len(f['parent_path_text']) < print_path:
            print_formatted_text(FormattedText([('#cccccc',f['full_path_text'])]))
            continue
        nc = '#000000'
        n = f['name_text']
        if f['can_have_children']:
            n+='/'
            nc = '#0000ff bold'
        #full_path_text
        m = f['metadata']
        #'metadata': {'size': 7166, 'access_time': 0, 'modify_time': 1741179164000, 'permissions': []

        mod = m.get('modify_time', None)
        if mod:
            mod = datetime.fromtimestamp(mod/1000)
            if (datetime.now()-mod).days < 200:
                mod = f"{mod:%d %b %H:%M}"
            else:
                mod = f"{mod:%d %b %Y}"
        else:
            mod = "            "

        print_formatted_text(FormattedText([
            ('#00ff00 bold',f"{sizeof_fmt(m.get('size',0)):>8} "),
            ('#0000ff',f"{mod}  "),
            (nc,n),
            ('#000000',f"\t{m.get('permissions','')}")
            ]))
      except Exception as e:
          print_formatted_text(FormattedText([('#ff0000',repr(e))]))

async def print_res_download(mythic_instance, task):
    file_uuid = None
    file_name = None
    async for item in mythic.subscribe_new_downloaded_files(mythic=mythic_instance):
     for f in item:
        if f['task']['id'] != task["display_id"]:
            continue
        #print(f)
        if not f['complete']:
            continue
        #'chunks_received' 0
        #'total_chunks' 1
        print_formatted_text(FormattedText([('#00ff00',"fetched file: "+f['full_remote_path_utf8'])]))
        file_uuid = f['agent_file_id']
        file_name = f['filename_utf8']
        break
     else:
        #not fitting file - keep subscription
        continue
     #fitting file - end subscription
     break
    try:
        local_name = await PromptSession().prompt_async('store at: ',
                default=file_name,
                validator=Validator.from_callable(lambda t: False if not t else True, error_message='Invalid input'))
        #ask file name and store
        bytes = await mythic.download_file(mythic=mythic_instance, file_uuid = file_uuid)
        local_name = path.expanduser(local_name)
        with open(local_name, 'wb') as lf:
            lf.write(bytes)
    except KeyboardInterrupt:
        pass

        
async def print_res_procs(mythic_instance):
    async for item in mythic.subscribe_new_processes(mythic=mythic_instance):
        print(item)

def ask_exit(task):
    stdin.close()
    if task._fut_waiter is not None:
        task._fut_waiter.cancel()
    else:
        task.cancel()

# everything below here is expected as a staple at the end of your program
# this launches the functions asynchronously and keeps the program running while long-running tasks are going
async def main():
    task = create_task(scripting())

    for signame in {'SIGINT', 'SIGTERM'}:
        get_event_loop().add_signal_handler(
            getattr(signal, signame),
            partial(ask_exit, task))

    #Strg+Z SIGTSTP

    await task

    try:
        while True:
            pending = all_tasks()
            plist = []
            for p in pending:
                if p._coro.__name__ != "main" and p._state == "PENDING":
                    plist.append(p)
            if len(plist) == 0:
                exit(0)
            else:
                await gather(*plist)
    except KeyboardInterrupt:
        pending = all_tasks()
        for t in pending:
            t.cancel()

run(main())
