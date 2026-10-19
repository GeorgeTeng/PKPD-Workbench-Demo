"""Local transport contract test; not a scientific/model acceptance test."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CompatibleHTTPTests(unittest.TestCase):
    def test_streaming_provider_uses_configured_endpoint_model_and_source_prompt(self):
        observed = {}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                observed['path'] = self.path
                observed['authorization_present'] = self.headers.get('Authorization') == 'Bearer test-only-placeholder'
                observed['body'] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                for content in ('{"value":', '7,"unit":"mg/L"}'):
                    chunk = {'choices':[{'delta':{'content':content}}]}
                    self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                output = Path(folder)/'response.json'
                env = dict(os.environ, CTXCOMP_OPENAI_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1',
                           CTXCOMP_OPENAI_MODEL='replacement-model', CTXCOMP_OPENAI_API_KEY='test-only-placeholder',
                           CTXCOMP_OPENAI_RESPONSE_FORMAT='json_object', CTXCOMP_OPENAI_EXTRA='',
                           CTXCOMP_OPENAI_CONTEXT_TOKENS='')
                prompt = json.dumps({'payload': {'source': '7 mg/L', 'schema': {'type': 'object'}}})
                result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8',
                    str(ROOT/'backend/context_compression/ctxcomp/openai_stream.py'), str(output)],
                    input=prompt, text=True, encoding='utf-8', capture_output=True, env=env, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(output.read_text()), {'value':7,'unit':'mg/L'})
                self.assertEqual(observed['path'], '/v1/chat/completions')
                self.assertTrue(observed['authorization_present'])
                self.assertEqual(observed['body']['model'], 'replacement-model')
                self.assertEqual(observed['body']['messages'][1]['content'], prompt)
                self.assertEqual(observed['body']['response_format'], {'type':'json_object'})
                self.assertNotIn('test-only-placeholder', result.stdout+result.stderr)
        finally:
            server.shutdown();server.server_close();worker.join()
