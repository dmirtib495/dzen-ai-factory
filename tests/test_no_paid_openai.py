import os
import subprocess
import sys


def test_paid_openai_key_is_ignored_project_wide():
    env = dict(os.environ)
    env['OPENAI_API_KEY'] = 'must-not-be-used'
    env['OPENAI_MODEL'] = 'gpt-5-mini'
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'import config; assert config.OPENAI_API_KEY == ""; assert config.OPENAI_MODEL == ""; print("PAID_OPENAI_DISABLED")',
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert 'PAID_OPENAI_DISABLED' in proc.stdout
