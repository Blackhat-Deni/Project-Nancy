import subprocess
import json

res = subprocess.run(['/home/deni/.nvm/versions/node/v24.14.1/bin/tv', 'ohlcv', '--count', '500'], capture_output=True, text=True)
print('Length of output:', len(res.stdout))
print('Parsed success:', 'success' in json.loads(res.stdout))
