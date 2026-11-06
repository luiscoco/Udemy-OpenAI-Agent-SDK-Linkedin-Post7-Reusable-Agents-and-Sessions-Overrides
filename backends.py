"""Two implementations of the same lesson workflow: local simulation and real API."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4


def replace_fields(saved, overrides):
    """Teaching model for these fields; not a general API configuration resolver."""
    result = deepcopy(saved)
    for field, value in overrides.items():
        result[field] = deepcopy(value)
    return result


class OfflineBackend:
    """Deterministic fixture answers. No network, language model, or API credentials."""
    mode = 'OFFLINE SIMULATION'

    def __init__(self, directory, timeout=180):
        self.directory = Path(directory)
        self.agents = {}
        self.sessions = {}

    def save_agent(self, config):
        agent_id = 'demo_agent_' + uuid4().hex[:8]
        self.agents[agent_id] = deepcopy(config)
        return agent_id

    def get_agent(self, agent_id):
        return deepcopy(self.agents[agent_id])

    def update_agent(self, agent_id, fields):
        self.agents[agent_id] = replace_fields(self.agents[agent_id], fields)

    def start(self, agent_id, overrides, text, label):
        session_id = 'demo_session_' + uuid4().hex[:8]
        self.sessions[session_id] = {
            'id': session_id, 'agent_id': agent_id,
            'agent': replace_fields(self.agents[agent_id], overrides),
            'environment': {'type': 'none'}, 'history': [], 'label': label,
        }
        self.send(session_id, text)
        return self.get_session(session_id)

    def send(self, session_id, text):
        session = self.sessions[session_id]
        history = session['history']
        if 'reference did I give' in text:
            references = re.findall(r'\b(?:ALPHA|BRAVO)-\d+\b', ' '.join(m['text'] for m in history if m['role']=='user'))
            answer = references[0] if references else 'No reference was supplied in this session.'
        elif 'timeouts' in text.lower():
            answer = 'A request timeout means a response did not arrive within the allowed time. Set a deadline and retry suitable transient failures with backoff.'
        else:
            answer = 'Pagination divides a large collection into smaller pages. For example, request the first page, then use the returned cursor to request the next page.'
        instructions = session['agent']['instructions']
        if 'three bullet points' in instructions and 'reference did I give' not in text:
            answer = '- Request a page of results.\n- Read the next-page cursor.\n- Continue until no further page is available.'
        history.extend([{'role':'user', 'text':text}, {'role':'assistant', 'text':answer}])
        self._checkpoint()
        return self.get_session(session_id)

    def get_session(self, session_id):
        return deepcopy(self.sessions[session_id])

    def _checkpoint(self):
        (self.directory/'offline_state.json').write_text(json.dumps({'agents':self.agents, 'sessions':self.sessions}, indent=2), encoding='utf-8')


class LiveBackend:
    """Small standard-library REST client for the documented Agents API beta."""
    mode = 'LIVE OPENAI API'
    base = 'https://api.openai.com/v1'

    def __init__(self, directory, timeout=180):
        self.key = os.environ.get('OPENAI_API_KEY', '').strip()
        if not self.key:
            raise ValueError('Set OPENAI_API_KEY before using --live. Offline mode needs no key.')
        self.directory = Path(directory)
        self.timeout = timeout
        self.resources = {'agents': [], 'sessions': []}

    def request(self, method, path, body=None):
        headers = {'Authorization': 'Bearer '+self.key, 'OpenAI-Beta':'agents=v1', 'Content-Type':'application/json'}
        # One distinct key per mutation; there are no automatic mutation retries.
        if method == 'POST':
            headers['Idempotency-Key'] = str(uuid4())
        request = Request(self.base+path, data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            detail = error.read().decode(errors='replace').replace(self.key, '[REDACTED]')
            raise RuntimeError(f'OpenAI HTTP {error.code}: {detail[:1500]}') from None
        except (URLError, TimeoutError) as error:
            raise RuntimeError('Network request failed. Inspect resources.json and remote state before retrying a mutation; its outcome may be unknown.') from error

    def pages(self, path):
        after = None
        while True:
            query = {'order':'asc', 'limit':100}
            if after:
                query['after'] = after
            page = self.request('GET', path+'?'+urlencode(query))
            yield from page.get('data', [])
            if not page.get('has_more'):
                break
            after = page.get('last_id')
            if not after:
                raise RuntimeError('Paginated response omitted its continuation cursor.')

    def remember(self, kind, resource_id):
        self.resources[kind].append(resource_id)
        (self.directory/'resources.json').write_text(json.dumps(self.resources, indent=2), encoding='utf-8')

    def save_agent(self, config):
        result = self.request('POST', '/agents', config)
        self.remember('agents', result['id'])
        return result['id']

    def get_agent(self, agent_id):
        return self.request('GET', '/agents/'+quote(agent_id, safe=''))

    def update_agent(self, agent_id, fields):
        self.request('POST', '/agents/'+quote(agent_id, safe=''), fields)

    def start(self, agent_id, overrides, text, label):
        body = {'agent_id':agent_id, 'environment':{'type':'none'}, 'input':text,
                'metadata':{'lesson':'7', 'config_label':label}}
        if overrides:
            body['agent'] = overrides
        result = self.request('POST', '/agents/sessions', body)
        session_id = result['id']
        self.remember('sessions', session_id)  # Save the ID before waiting on inference.
        self.wait(session_id, set())
        return self.get_session(session_id)

    def send(self, session_id, text):
        path = '/agents/sessions/'+quote(session_id, safe='')
        previous = {turn['id'] for turn in self.pages(path+'/turns')}
        self.request('POST', path+'/events', {'events':[{
            'type':'agent.session.input.message',
            'input':[{'role':'user', 'content':[{'type':'input_text', 'text':text}]}],
        }]})
        self.wait(session_id, previous)
        return self.get_session(session_id)

    def wait(self, session_id, previous):
        path = '/agents/sessions/'+quote(session_id, safe='')
        deadline = time.monotonic()+self.timeout
        while time.monotonic() < deadline:
            state = self.request('GET', path)
            if state.get('status') in ('requires_action', 'failed') or state.get('required_actions'):
                raise RuntimeError(f'Session {session_id} needs attention: {json.dumps(state.get("required_actions") or state.get("error"))}')
            turns = [t for t in self.pages(path+'/turns') if t['id'] not in previous and not t.get('subagent_id')]
            for turn in turns:
                if turn['status'] in ('failed', 'cancelled'):
                    raise RuntimeError(f'Turn {turn["id"]} {turn["status"]}: {turn.get("error")}')
            if turns and all(t['status']=='completed' for t in turns):
                return
            time.sleep(1)
        raise RuntimeError(f'Timed out waiting for {session_id}. The remote turn may still be running; inspect it before starting new work.')

    def get_session(self, session_id):
        path = '/agents/sessions/'+quote(session_id, safe='')
        state = self.request('GET', path)
        history = []
        for item in self.pages(path+'/items'):
            if item.get('type') != 'message':
                continue
            text = '\n'.join(part.get('text','') for part in item.get('content',[]) if part.get('type') in ('input_text','output_text','text'))
            if text:
                history.append({'role':item.get('role'), 'text':text})
        state['history'] = history
        return state
