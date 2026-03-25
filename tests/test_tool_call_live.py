"""Live tool call test with full Claude Code tool set."""
import asyncio
import sys
import os

sys.path.insert(0, '/teamspace/studios/this_studio/wiwi')
os.environ['CURSOR_COOKIE'] = 'WorkosCursorSessionToken=user_01K0E9JZM7YR938EKTHFV35TAJ%3A%3AeyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJnb29nbGUtb2F1dGgyfHVzZXJfMDFLMEU5SlpNN1lSOTM4RUtUSEZWMzVUQUoiLCJ0aW1lIjoiMTc3MzI5ODQyMSIsInJhbmRvbW5lc3MiOiI5NDI2NTM3Yy1mMzRmLTQ0MjEiLCJleHAiOjE3Nzg0ODI0MjEsImlzcyI6Imh0dHBzOi8vYXV0aGVudGljYXRpb24uY3Vyc29yLnNoIiwic2NvcGUiOiJvcGVuaWQgcHJvZmlsZSBlbWFpbCBvZmZsaW5lX2FjY2VzcyIsImF1ZCI6Imh0dHBzOi8vY3Vyc29yLmNvbSIsInR5cGUiOiJ3ZWIiLCJ3b3Jrb3NTZXNzaW9uSWQiOiJzZXNzaW9uXzAxS0tHRDUyU0JaMUFOSDJGWkJSMEVFQTEzIn0.1_4AWNXXCuKzVu_ipvbLXA98kSOCmsC860F_aQ35Sqo'

import httpx
import msgspec.json as mj
from converters.to_cursor import openai_to_cursor
from cursor.client import CursorClient, _build_payload

# Full Claude Code tool set
TOOLS = [
    {'type':'function','function':{'name':'Agent','description':'Launch a new agent to handle complex, multi-step tasks autonomously. Launches specialized agents (subprocesses) with specific capabilities.','parameters':{'type':'object','properties':{'description':{'type':'string'},'prompt':{'type':'string'},'subagent_type':{'type':'string'},'run_in_background':{'type':'boolean'},'resume':{'type':'string'}},'required':['description','prompt']}}},
    {'type':'function','function':{'name':'Bash','description':'Executes a bash command and returns its output. Working directory persists between commands.','parameters':{'type':'object','properties':{'command':{'type':'string'},'timeout':{'type':'number'},'run_in_background':{'type':'boolean'},'description':{'type':'string'}},'required':['command']}}},
    {'type':'function','function':{'name':'Read','description':'Reads a file from the local filesystem. Returns contents with line numbers. Can read images, PDFs, Jupyter notebooks.','parameters':{'type':'object','properties':{'file_path':{'type':'string'},'offset':{'type':'number'},'limit':{'type':'number'},'pages':{'type':'string'}},'required':['file_path']}}},
    {'type':'function','function':{'name':'Write','description':'Writes a file to the local filesystem. Overwrites existing file.','parameters':{'type':'object','properties':{'file_path':{'type':'string'},'content':{'type':'string'}},'required':['file_path','content']}}},
    {'type':'function','function':{'name':'Edit','description':'Performs exact string replacements in files. old_string must be unique in file.','parameters':{'type':'object','properties':{'file_path':{'type':'string'},'old_string':{'type':'string'},'new_string':{'type':'string'},'replace_all':{'type':'boolean','default':False}},'required':['file_path','old_string','new_string']}}},
    {'type':'function','function':{'name':'Glob','description':'Fast file pattern matching. Supports glob patterns like **/*.js. Returns paths sorted by modification time.','parameters':{'type':'object','properties':{'pattern':{'type':'string'},'path':{'type':'string'}},'required':['pattern']}}},
    {'type':'function','function':{'name':'Grep','description':'Search file contents using ripgrep. Supports full regex. Filter with glob or type. Output modes: content, files_with_matches, count.','parameters':{'type':'object','properties':{'pattern':{'type':'string'},'path':{'type':'string'},'glob':{'type':'string'},'type':{'type':'string'},'output_mode':{'type':'string','enum':['content','files_with_matches','count']},'context':{'type':'number'},'-i':{'type':'boolean'}},'required':['pattern']}}},
    {'type':'function','function':{'name':'WebSearch','description':'Search the web for current information. Returns results with links.','parameters':{'type':'object','properties':{'query':{'type':'string'},'allowed_domains':{'type':'array','items':{'type':'string'}}},'required':['query']}}},
    {'type':'function','function':{'name':'WebFetch','description':'Fetches content from a URL and processes it with a prompt.','parameters':{'type':'object','properties':{'url':{'type':'string'},'prompt':{'type':'string'}},'required':['url','prompt']}}},
    {'type':'function','function':{'name':'TaskCreate','description':'Create a task in the task list to track progress.','parameters':{'type':'object','properties':{'subject':{'type':'string'},'description':{'type':'string'}},'required':['subject','description']}}},
    {'type':'function','function':{'name':'TaskUpdate','description':'Update a task status or details.','parameters':{'type':'object','properties':{'taskId':{'type':'string'},'status':{'type':'string'},'subject':{'type':'string'}},'required':['taskId']}}},
    {'type':'function','function':{'name':'TaskList','description':'List all tasks with their status.','parameters':{'type':'object','properties':{}}}},
    {'type':'function','function':{'name':'TaskGet','description':'Get a specific task by ID.','parameters':{'type':'object','properties':{'taskId':{'type':'string'}},'required':['taskId']}}},
    {'type':'function','function':{'name':'mcp__ide__getDiagnostics','description':'Get language diagnostics (errors/warnings) from the IDE for a file.','parameters':{'type':'object','properties':{'uri':{'type':'string'}}}}},
    {'type':'function','function':{'name':'mcp__ide__executeCode','description':'Execute Python code in the Jupyter kernel.','parameters':{'type':'object','properties':{'code':{'type':'string'}},'required':['code']}}},
    {'type':'function','function':{'name':'mcp__browser__screenshot','description':'Take a screenshot of the current browser page.','parameters':{'type':'object','properties':{}}}},
    {'type':'function','function':{'name':'mcp__browser__navigate','description':'Navigate the browser to a URL.','parameters':{'type':'object','properties':{'url':{'type':'string'}},'required':['url']}}},
    {'type':'function','function':{'name':'mcp__browser__click','description':'Click on an element in the browser.','parameters':{'type':'object','properties':{'ref':{'type':'string'}},'required':['ref']}}},
    {'type':'function','function':{'name':'mcp__browser__type','description':'Type text into a browser input element.','parameters':{'type':'object','properties':{'ref':{'type':'string'},'text':{'type':'string'}},'required':['ref','text']}}},
    {'type':'function','function':{'name':'mcp__browser__snapshot','description':'Get accessibility snapshot of the current browser page.','parameters':{'type':'object','properties':{'filename':{'type':'string'}}}}},
]

MESSAGES = [
    {'role': 'user', 'content': (
        'Do these 5 tasks in parallel simultaneously:\n'
        '1. Use WebSearch to find Python 3.13 release notes\n'
        '2. Use Read to read /etc/os-release\n'
        '3. Use Glob to find all *.py files in /tmp\n'
        '4. Use Bash to run: ps aux | head -5\n'
        '5. Use TaskCreate to create a task called "Live test" with description "Testing parallel tool calls"'
    )}
]


async def main():
    cursor_messages = openai_to_cursor(MESSAGES, tools=TOOLS, model='anthropic/claude-sonnet-4.6')
    payload = _build_payload(cursor_messages, 'anthropic/claude-sonnet-4.6', TOOLS)
    payload_bytes = mj.encode(payload)
    print(f'Payload: {len(payload_bytes):,} bytes (~{len(payload_bytes)//4:,} tokens)')
    print(f'Messages: {len(cursor_messages)}  Tools: {len(TOOLS)}')
    print()

    async with httpx.AsyncClient(timeout=httpx.Timeout(90)) as http:
        client = CursorClient(http)
        full = ''
        async for delta in client.stream(cursor_messages, 'anthropic/claude-sonnet-4.6', TOOLS):
            full += delta
            print(delta, end='', flush=True)
    print()
    print(f'--- DONE | {len(full)} chars ---')


if __name__ == '__main__':
    asyncio.run(main())
