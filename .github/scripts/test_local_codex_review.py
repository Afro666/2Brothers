import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import local_codex_review as local


class LocalReviewTests(unittest.TestCase):
    def test_api_login_is_refused_before_any_model_call(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(local.shutil, 'which', return_value='codex'), patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='Logged in using an API key', stderr='')) as run:
            with self.assertRaisesRegex(ValueError, 'API-key authentication is refused'):
                local.review(1, 'team/repo', 'gpt-test', Path(tmp) / 'review.md')
            self.assertEqual(run.call_count, 1)

    def test_chatgpt_review_excludes_secrets_and_never_posts(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OPENAI_API_KEY': 'private-api', 'GH_TOKEN': 'private-gh', 'VERDA_API_KEY': 'private-verda', 'PATH': 'bin'}, clear=True):
            out = Path(tmp) / 'review.md'
            def run(cmd, **kwargs):
                self.assertFalse(set(kwargs['env']) & {'OPENAI_API_KEY', 'GH_TOKEN', 'VERDA_API_KEY'})
                if 'login' in cmd:
                    return subprocess.CompletedProcess(cmd, 0, stdout='Logged in using ChatGPT', stderr='')
                self.assertIn('--ignore-user-config', cmd)
                self.assertIn('shell_tool', cmd)
                self.assertEqual(kwargs['input'].count('UNTRUSTED DIFF:'), 1)
                Path(cmd[cmd.index('-o') + 1]).write_text('No concrete findings.', encoding='utf-8')
                return subprocess.CompletedProcess(cmd, 0)
            with patch.object(local.shutil, 'which', return_value='codex'), patch.object(local, 'gh', side_effect=['a'*40, 'diff', 'a'*40]) as gh, patch.object(subprocess, 'run', side_effect=run), contextlib.redirect_stdout(io.StringIO()):
                local.review(1, 'team/repo', 'gpt-test', out)
            self.assertTrue(out.exists())
            self.assertNotIn('comment', str(gh.call_args_list))
            self.assertIn('Existing ChatGPT login', out.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
