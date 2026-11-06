"""Lesson 7: one technical-support agent, independent tailored sessions."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4
from backends import LiveBackend, OfflineBackend, replace_fields

ROOT = Path(__file__).resolve().parent


def replacement_lab():
    # These names are labels for a local exercise, not executable tool definitions.
    saved = {'reasoning':{'effort':'low', 'summary':'auto'}, 'tools':['lookup_docs','create_ticket']}
    override = {'reasoning':{'effort':'high'}, 'tools':['lookup_docs']}
    return {'saved':saved, 'override':override, 'effective':replace_fields(saved, override)}


def run_demo(backend, config, directory):
    directory = Path(directory)
    report = {'mode':backend.mode, 'model':config['model'], 'sessions':{}, 'checks':{}}

    def checkpoint():
        (directory/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    def check(name, condition):
        report['checks'][name] = bool(condition)
        checkpoint()
        print(f'  {"PASS" if condition else "FAIL"}: {name}', flush=True)
        if not condition:
            raise RuntimeError(f'Lesson verification failed: {name}. Inspect report.json.')

    def capture(name, session, version, overrides, task):
        report['sessions'][name] = {
            'agent_id':agent_id, 'session_id':session['id'], 'config_label':version,
            'purpose':task, 'overrides':deepcopy(overrides),
            'expected_config':replace_fields(config if version=='support-v1' else config_v2, overrides),
            'observed_config':session['agent'], 'environment':session['environment'],
            'history':session['history'],
        }
        checkpoint()
        answers = [m['text'] for m in session['history'] if m['role']=='assistant']
        print(f'\n{name}: {session["id"]}\n'+(answers[-1] if answers else '[No assistant text returned]'), flush=True)
        check(name+' returned assistant text', bool(answers))

    print(f'\n{backend.mode}\n1. Save reusable support agent', flush=True)
    agent_id = backend.save_agent(config)
    report['agent_id'] = agent_id
    checkpoint()
    print('2. Start A with defaults and B with session overrides', flush=True)
    task_a = 'Our support ticket is ALPHA-17. Explain API pagination.'
    a = backend.start(agent_id, {}, task_a, 'support-v1')
    capture('A - default explanation', a, 'support-v1', {}, task_a)
    overrides = {'instructions':config['instructions']+' Use one concise paragraph of at most 45 words.',
                 'reasoning':{'effort':'low'}}
    task_b = 'Our support ticket is BRAVO-28. Explain API request timeouts.'
    b = backend.start(agent_id, overrides, task_b, 'support-v1')
    capture('B - concise support', b, 'support-v1', overrides, task_b)
    saved_after_b = backend.get_agent(agent_id)
    check('B override did not edit saved instructions', saved_after_b['instructions']==config['instructions'])
    check('A and B have different session IDs', a['id']!=b['id'])
    check('B received replacement instructions', b['agent']['instructions']==overrides['instructions'])

    print('\n3. Continue A using its own conversation history', flush=True)
    a = backend.send(a['id'], 'Which support ticket reference did I give you? Answer only with the reference.')
    b_unchanged = backend.get_session(b['id'])
    capture('A - continued', a, 'support-v1', {}, task_a)
    check('Continuing A did not change B history', b_unchanged['history']==b['history'])
    user_a = ' '.join(m['text'] for m in a['history'] if m['role']=='user')
    user_b = ' '.join(m['text'] for m in b['history'] if m['role']=='user')
    check('Each session has only its own ticket input', 'ALPHA-17' in user_a and 'BRAVO-28' not in user_a and 'BRAVO-28' in user_b and 'ALPHA-17' not in user_b)

    print('\n4. Update saved instructions, then create C', flush=True)
    config_v2 = deepcopy(config)
    config_v2['instructions'] = config['instructions']+' Present explanations as exactly three bullet points.'
    backend.update_agent(agent_id, {'instructions':config_v2['instructions']})
    task_c = 'Explain API pagination.'
    c = backend.start(agent_id, {}, task_c, 'support-v2')
    capture('C - new saved configuration', c, 'support-v2', {}, task_c)
    old_a = backend.get_session(a['id'])
    old_b = backend.get_session(b['id'])
    check('Existing A retains v1 instructions', old_a['agent']['instructions']==config['instructions'])
    check('Existing B retains its own override', old_b['agent']['instructions']==overrides['instructions'])
    check('New C receives v2 instructions', c['agent']['instructions']==config_v2['instructions'])

    print('\n5. Inspect object and list replacement', flush=True)
    report['replacement_lab'] = replacement_lab()
    print(json.dumps(report['replacement_lab'], indent=2), flush=True)
    check('Replacement object drops omitted summary', 'summary' not in report['replacement_lab']['effective']['reasoning'])
    check('Replacement list drops omitted tool', report['replacement_lab']['effective']['tools']==['lookup_docs'])
    report['saved_agent_final'] = backend.get_agent(agent_id)
    checkpoint()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Use real OpenAI Agents API calls; creates billed inference work.')
    parser.add_argument('--model', help='Override OPENAI_MODEL/config.json model.')
    parser.add_argument('--config', type=Path, default=ROOT/'config.json')
    parser.add_argument('--timeout', type=int, default=180, help='Maximum polling time per turn, in seconds.')
    args = parser.parse_args()
    if args.timeout<=0:
        parser.error('--timeout must be positive')
    config = json.loads(args.config.read_text(encoding='utf-8'))
    config['model'] = args.model or os.environ.get('OPENAI_MODEL') or config['model']
    # This lab deliberately implements no external function execution.
    if config.get('tools') != []:
        parser.error('This text-only lab requires tools: []; use replacement_lab for the list exercise.')
    if not isinstance(config.get('instructions'), str) or not config['instructions'].strip():
        parser.error('config instructions must be a nonempty string')
    if args.live and not os.environ.get('OPENAI_API_KEY','').strip():
        parser.error('Set OPENAI_API_KEY for --live, or omit --live for offline simulation.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = ROOT/'runs'/f'{stamp}-{uuid4().hex[:6]}'
    directory.mkdir(parents=True)
    print(f'Run folder: {directory}', flush=True)
    try:
        backend = (LiveBackend if args.live else OfflineBackend)(directory, timeout=args.timeout)
        run_demo(backend, config, directory)
    except (RuntimeError, ValueError, KeyError) as error:
        (directory/'error.txt').write_text(str(error), encoding='utf-8')
        parser.exit(1, f'\nStopped: {error}\nPartial results: {directory}\n')
    print(f'\nCompleted. Read {directory / "report.json"}', flush=True)
    if not args.live:
        print('Offline answers are fixtures, not model-generated responses.')
    else:
        print('Remote IDs are in resources.json. Sessions and the saved agent remain in your project.')


if __name__=='__main__':
    main()
