"""Meaningful checks for snapshots, isolation, replacement, and remote failures."""
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from uuid import uuid4
import unittest
from unittest.mock import patch

from app import ROOT, replacement_lab, run_demo
from backends import LiveBackend, OfflineBackend, replace_fields


class LessonTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / ('test-' + uuid4().hex)
        self.path.mkdir()
        assert self.path.resolve().parent == ROOT.resolve()
        self.addCleanup(self.cleanup_files)
        self.config = json.loads((ROOT/'config.json').read_text())

    def cleanup_files(self):
        for file in self.path.iterdir():
            file.unlink()
        self.path.rmdir()

    def test_complete_offline_workflow_and_persisted_report(self):
        backend = OfflineBackend(self.path)
        with redirect_stdout(StringIO()):
            report = run_demo(backend, self.config, self.path)
        self.assertTrue(all(report['checks'].values()))
        self.assertEqual(3, len(backend.sessions))
        self.assertEqual('ALPHA-17', report['sessions']['A - continued']['history'][-1]['text'])
        self.assertEqual(report, json.loads((self.path/'report.json').read_text()))

    def test_session_configuration_is_deeply_copied(self):
        backend = OfflineBackend(self.path)
        agent_id = backend.save_agent(self.config)
        original = backend.start(agent_id, {}, 'Explain pagination', 'v1')
        self.config['reasoning']['effort'] = 'high'
        backend.update_agent(agent_id, {'instructions':'New instructions'})
        current = backend.get_session(original['id'])
        self.assertEqual('low', current['agent']['reasoning']['effort'])
        self.assertNotEqual('New instructions', current['agent']['instructions'])
        # Mutating a retrieved copy also must not alter stored history.
        current['history'].clear()
        self.assertEqual(2, len(backend.get_session(original['id'])['history']))

    def test_nested_objects_and_arrays_replace_and_inputs_remain_unchanged(self):
        lab = replacement_lab()
        self.assertEqual({'effort':'high'}, lab['effective']['reasoning'])
        self.assertEqual(['lookup_docs'], lab['effective']['tools'])
        self.assertIn('summary', lab['saved']['reasoning'])
        inherited = replace_fields(lab['saved'], {})
        inherited['tools'].clear()
        self.assertEqual(2, len(lab['saved']['tools']))

    def live_double(self, turns, state=None):
        # No constructor, credentials, or network in this test double.
        backend = object.__new__(LiveBackend)
        backend.timeout = .1
        backend.request = lambda *args: state or {'status':'idle', 'required_actions':[]}
        backend.pages = lambda *args: iter(deepcopy(turns))
        return backend

    def test_failed_turn_is_not_treated_as_successful_idle_session(self):
        backend = self.live_double([{'id':'turn_bad','status':'failed','error':{'message':'quota'},'subagent_id':None}])
        with self.assertRaisesRegex(RuntimeError, 'failed'):
            backend.wait('session_test', set())

    def test_old_completed_turn_does_not_complete_a_new_submission(self):
        backend = self.live_double([{'id':'turn_old','status':'completed'}])
        with patch('backends.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Timed out'):
                backend.wait('session_test', {'turn_old'})

    def test_required_action_stops_with_an_explanation(self):
        backend = self.live_double([], {'status':'requires_action','required_actions':[{'type':'function_call'}]})
        with self.assertRaisesRegex(RuntimeError, 'needs attention'):
            backend.wait('session_test', set())

    def test_paginated_history_preserves_both_pages(self):
        backend = object.__new__(LiveBackend)
        replies = iter([
            {'data':[{'id':'one'}], 'has_more':True, 'last_id':'one'},
            {'data':[{'id':'two'}], 'has_more':False},
        ])
        paths = []
        def request(method, path):
            paths.append(path)
            return next(replies)
        backend.request = request
        self.assertEqual(['one','two'], [v['id'] for v in backend.pages('/items')])
        self.assertIn('after=one', paths[1])


if __name__=='__main__':
    unittest.main()
