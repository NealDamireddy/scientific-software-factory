from pathlib import Path
import json
import tempfile
import unittest

from factory.assays.b12 import b12_build, optics
from factory.assays.b12.followup import replay_acquisition, run_followup
from factory.assays.b12.lab import save
from factory.software.sandbox import execute


# An offline fixture with an independently written estimator for the trusted runner.
CANDIDATE = """import json, sys
s = json.load(sys.stdin)
a = s['absorbances']
c = s['calibration']
p = s['preparation']
result = {'sample_id': s['sample_id'], 'calibration_id': c['id'],
          'status': 'review', 'concentration_mg_l': None}
if min(a) >= c['low'] and max(a) <= c['high']:
    diluted = sum((reading - c['intercept']) / c['slope'] for reading in a) / len(a)
    factor = p['final_ml'] / p['sample_ml'] if p else 1
    result.update(status='ok', concentration_mg_l=diluted * factor)
    if p:
        result.update(diluted_mg_l=diluted, factor=factor, parent_id=p['parent_id'], preparation_id=p['id'])
print(json.dumps(result))
"""


class FollowupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.parent = Path(temp.name) / 'parent'
        self.child = Path(temp.name) / 'child'
        self.parent.mkdir()
        self.child.mkdir()
        for folder in (self.parent, self.child):
            (folder / 'analysis.py').write_text(CANDIDATE + '# ' + folder.name)
            save(folder / 'views.json', {'title': 'Example'})
            save(folder / 'recipe.json', optics.RECIPE)
        cal = optics.fit_calibration(optics.RECIPE, 1224)
        raw = optics.acquire(optics.RECIPE, 36, 83, sample_id='B')
        finding = optics.assess(raw, cal)
        payload = {'sample_id': 'B', 'preparation': None, 'absorbances': finding['absorbances'],
                   'calibration': {key: cal[key] for key in ('id', 'slope', 'intercept', 'low', 'high')}}
        self.acquisition = {'calibration': cal, 'raw': raw, 'input': payload, 'finding': finding}
        save(self.parent / 'acquisition.json', self.acquisition)
        save(self.parent / 'private.json', {'prepared_mg_l': 36})
        self.parent_task = {'id': 'parent', 'status': 'verified', 'revision': b12_build.revision(self.parent),
                            'result': {'status': 'review', 'concentration_mg_l': None,
                                       'sample_id': 'B', 'calibration_id': cal['id']}}
        self.child_task = {
            'id': 'child', 'status': 'verified', 'revision': b12_build.revision(self.child),
            'parent_revision': self.parent_task['revision'], 'parent_id': 'parent',
            'approval': {'origin': 'parent', 'approved_at': '2026-01-01T00:00:00Z',
                         'factor': 2, 'protocol': optics.PROFILE['protocol']},
            'preparation': {'sample_id': 'B-2', 'id': 'P1', 'parent_id': 'B',
                            'sample_ml': 1.25, 'final_ml': 2.5, 'unit': 'mL'}
        }
        save(self.parent / 'task.json', self.parent_task)
        save(self.child / 'task.json', self.child_task)

    def run_child(self):
        return run_followup(self.parent, self.child, self.parent_task, self.child_task)

    def test_triplicate_followup_and_replay(self):
        record = self.run_child()
        result = record['result']
        self.assertAlmostEqual(result['concentration_mg_l'], 36, delta=0.2)
        self.assertAlmostEqual(result['diluted_mg_l'], 18, delta=0.1)
        self.assertEqual((result['parent_id'], result['sample_id'], result['preparation_id']), ('B', 'B-2', 'P1'))
        self.assertFalse({'seed', 'prepared_mg_l'} & record.keys())
        self.assertEqual(len(record['raw']), 3)
        self.assertEqual(record['calibration_id'], self.acquisition['calibration']['id'])
        self.assertEqual(replay_acquisition(self.parent, self.acquisition, self.acquisition['calibration']),
                         self.parent_task['result'])
        # Replay must ignore cached candidate output and absorbances in favour of the counts.
        record['result'] = None
        record['input']['absorbances'] = [100] * 3
        self.assertEqual(replay_acquisition(self.child, record, self.acquisition['calibration']), result)

    def test_rerun_outside_scale(self):
        # A stronger simulated preparation still lies above the scale at factor 2.
        save(self.parent / 'private.json', {'prepared_mg_l': 75})
        raw = optics.acquire(optics.RECIPE, 75, 83, sample_id='B')
        self.acquisition['raw'] = raw
        self.acquisition['finding'] = optics.assess(raw, self.acquisition['calibration'])
        self.acquisition['input']['absorbances'] = self.acquisition['finding']['absorbances']
        save(self.parent / 'acquisition.json', self.acquisition)
        record = self.run_child()
        self.assertTrue(record['finding']['above_range'])
        self.assertEqual(record['result']['status'], 'review')
        self.assertIsNone(record['result']['concentration_mg_l'])

    def test_digests_and_approval_rechecked(self):
        for field, value in [('parent_id', 'other'), ('parent_revision', 'changed'), ('status', 'generating')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                run_followup(self.parent, self.child, self.parent_task, {**self.child_task, field: value})
        self.child_task['approval']['factor'] = 4
        with self.assertRaisesRegex(ValueError, 'approved dilution'):
            self.run_child()
        self.child_task['approval']['factor'] = 2
        original_cal = self.acquisition['calibration'].copy()
        self.acquisition['calibration']['slope'] = 0.5
        save(self.parent / 'acquisition.json', self.acquisition)
        with self.assertRaisesRegex(ValueError, 'calibration digest'):
            self.run_child()
        self.acquisition['calibration'] = original_cal
        save(self.parent / 'acquisition.json', self.acquisition)
        (self.child / 'analysis.py').write_text('print("{}")')
        with self.assertRaisesRegex(ValueError, 'source digest'):
            self.run_child()

    def test_candidate_cannot_read_label_or_mutate_trusted_files(self):
        validator = Path(optics.__file__).resolve()
        calibration = self.parent / 'acquisition.json'
        for path, mode in [(self.parent / 'private.json', 'r'), (validator, 'r+'), (calibration, 'r+')]:
            before = path.read_bytes()
            with self.subTest(path=path, mode=mode):
                # Open for updating without performing a write if the boundary unexpectedly fails.
                source = self.child / 'probe.py'
                source.write_text(f"open({str(path)!r},{mode!r}).close()\nprint('{{}}')")
                # Seatbelt denies access; bubblewrap hides the host path entirely.
                with self.assertRaisesRegex(RuntimeError, 'PermissionError|FileNotFoundError'):
                    execute(source, json.dumps({}).encode())
                self.assertEqual(path.read_bytes(), before)
