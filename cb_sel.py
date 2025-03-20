from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.scroll import scroll_one_line_down, scroll_one_line_up, scroll_page_down, scroll_page_up
from prompt_toolkit.layout import Layout, HSplit
from prompt_toolkit.widgets import RadioList, Label
from prompt_toolkit.formatted_text import FormattedText
from datetime import datetime

async def full_sel_cb(ait, columns, require_input):
    agentlist = []
    colwidth = [0,7,4,4,9,4,2,4]
    default = 0
    for item in ait:
        d = datetime.now() - datetime.fromisoformat(item['last_checkin'][:19])
        if d.total_seconds() < 300:
            d = f"{d.total_seconds()}s"
        else:
            hours, remainder = divmod(d.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            d = '{}h {}m {}s'.format(int(hours), int(minutes), int(seconds))

        if item['id'] > default:
            default = item['id']
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
    w = sum(colwidth)+6*3+4
    if w > columns:
        #make stuff smaller
        if colwidth[6] > 13:
            w -= colwidth[6] - 13
            colwidth[6] = 13
        if w > columns:
            colwidth[7] -= 1+w-columns

    form = [('','    ')]
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
    #print_formatted_text(FormattedText(form))

    s= await radiofy(FormattedText(form), [(item['id'],FormattedText([
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
        ])) for item in agentlist], str(default))
    if s:
        return int(s)
    elif require_input:
        raise KeyboardInterrupt

async def radiofy(header, items, default):
    root_container = RadioList(items, default)
    layout = Layout(container=HSplit([Label(header), root_container]))
    layout.container.children[1].content.key_bindings.remove("enter")
    kb = KeyBindings()
    @kb.add("c-c")
    @kb.add("escape")
    def exit(event) -> None:
        get_app().exit()
    kb.add("pagedown")(scroll_page_down)
    kb.add("pageup")(scroll_page_up)
    kb.add("down")(scroll_one_line_down)
    kb.add("up")(scroll_one_line_up)
    @kb.add("enter")
    def enter(event) -> None:
        root_container._handle_enter()
        get_app().exit(result=root_container.current_value)
    application = Application(layout=layout, key_bindings=kb, full_screen=True)
    #application.layout.container.content.key_bindings.remove("enter")
    return await application.run_async()


async def inline_sel_cb(ait, columns, required):
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
    if required:
        return int(await PromptSession().prompt_async('cb# ',
                        is_password=False,
                        enable_history_search=False,
                        validator=Validator.from_callable(lambda t: False if not t else True, error_message='Invalid input')))
