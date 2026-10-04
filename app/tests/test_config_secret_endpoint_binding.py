import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from config_settings import AppConfig, GenerationConfig, LLMConfig, TTSConfig
from routers import system


class ConfigSecretEndpointBindingTests(unittest.TestCase):
    def profile(self, url, key):
        return LLMConfig(base_url=url, api_key=key, model_name='fixture')

    def test_changed_endpoint_cannot_restore_or_resolve_saved_key(self):
        existing = {'llm': {'base_url': 'http://127.0.0.1:1234/v1', 'api_key': 'fixture-secret'},
                    'llm_local': {'base_url': 'http://127.0.0.1:1234/v1', 'api_key': 'fixture-secret'}}
        config = AppConfig(llm=self.profile('http://127.0.0.1:1235/v1', '[REDACTED]'), tts=TTSConfig())
        original = copy.deepcopy(existing)
        with self.assertRaises(HTTPException) as error:
            system._restore_redacted_secrets(config, existing)
        self.assertEqual(400, error.exception.status_code)
        with self.assertRaises(HTTPException) as error:
            system._resolve_redacted_api_key('[REDACTED]', 'http://127.0.0.1:1235/v1', existing)
        self.assertEqual(400, error.exception.status_code)
        self.assertEqual(original, existing)
        self.assertEqual('[REDACTED]', config.llm.api_key)

    def test_save_rejects_url_change_without_overwriting_config_and_allows_explicit_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'config.json')
            old = self.profile('http://127.0.0.1:1234/v1', 'fixture-secret')
            config = AppConfig(llm=old, llm_local=old, tts=TTSConfig())
            path.write_text(json.dumps(config.model_dump()))
            original = path.read_bytes()
            application = FastAPI(); application.include_router(system.router)
            incoming = config.model_dump()
            incoming['llm_local'].update(base_url='http://127.0.0.1:1235/v1', api_key='[REDACTED]')
            with patch.object(system, 'CONFIG_PATH', str(path)), patch.object(system, 'project_manager', Mock()), TestClient(application) as client:
                result = client.post('/api/config', json=incoming)
                self.assertEqual(400, result.status_code)
                self.assertEqual(original, path.read_bytes())
                incoming['llm_local']['api_key'] = 'explicit-new-key'
                result = client.post('/api/config', json=incoming)
                self.assertEqual(200, result.status_code)
            saved = json.loads(path.read_text())
            self.assertEqual('explicit-new-key', saved['llm_local']['api_key'])
            self.assertEqual(saved['llm_local'], saved['llm'])

    def test_mode_switch_preserves_each_profile_key_and_mirrors_new_active_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'config.json')
            local = self.profile('http://127.0.0.1:1234/v1', 'local-fixture')
            remote = self.profile('http://127.0.0.1:1236/v1', 'remote-fixture')
            config = AppConfig(llm=local, llm_local=local, llm_remote=remote, tts=TTSConfig())
            path.write_text(json.dumps(config.model_dump()))
            incoming = system._redact_config_secrets(config.model_dump())
            incoming['llm_mode'] = 'remote'
            application = FastAPI(); application.include_router(system.router)
            with patch.object(system, 'CONFIG_PATH', str(path)), patch.object(system, 'project_manager', Mock()), TestClient(application) as client:
                response = client.post('/api/config', json=incoming)
            self.assertEqual(200, response.status_code, response.text)
            saved = json.loads(path.read_text())
            self.assertEqual('remote-fixture', saved['llm']['api_key'])
            self.assertEqual('remote-fixture', saved['llm_remote']['api_key'])
            self.assertEqual('local-fixture', saved['llm_local']['api_key'])

    def test_test_and_models_routes_reject_unmatched_key_before_client_or_claim(self):
        existing = {'llm_local': {'base_url': 'http://127.0.0.1:1234/v1', 'api_key': 'fixture-secret'}}
        application = FastAPI(); application.include_router(system.router)
        request = self.profile('http://127.0.0.1:1235/v1', '[REDACTED]').model_dump()
        with patch.object(system, 'load_app_config', return_value=existing), \
             patch.object(system, 'claim_gpu_task') as claim, \
             patch('llm_provider.make_llm_client') as client_factory, TestClient(application) as client:
            result = client.post('/api/llm/test', json=request)
            self.assertEqual(400, result.status_code)
            models = client.post('/api/llm/models', json=request)
            self.assertEqual(200, models.status_code)
            self.assertEqual([], models.json()['models'])
            self.assertIn('changed endpoint', models.json()['error'])
            self.assertNotIn('fixture-secret', result.text + models.text)
            claim.assert_not_called()
            client_factory.assert_not_called()

    def test_get_then_save_initial_and_legacy_config_preserves_credentials(self):
        for saved in ({}, {'llm': self.profile('http://127.0.0.1:1234/v1', 'legacy-secret').model_dump()},
                      {'llm': self.profile('http://127.0.0.1:1234/v1', 'legacy-secret').model_dump(), 'llm_local': None}):
            with self.subTest(saved=bool(saved)), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp, 'config.json')
                if saved:
                    path.write_text(json.dumps(saved))
                before = path.read_bytes() if path.exists() else None
                application = FastAPI()
                application.include_router(system.router)
                with patch.object(system, 'CONFIG_PATH', str(path)), patch.object(system, 'project_manager', Mock()), TestClient(application) as client:
                    response = client.get('/api/config')
                    self.assertEqual(200, response.status_code)
                    self.assertEqual(before, path.read_bytes() if path.exists() else None)
                    incoming = response.json()
                    self.assertNotIn('legacy-secret', response.text)
                    incoming['tts']['pause_same_speaker_ms'] = 321
                    result = client.post('/api/config', json=incoming)
                    self.assertEqual(200, result.status_code, result.text)
                persisted = json.loads(path.read_text())
                self.assertEqual(321, persisted['tts']['pause_same_speaker_ms'])
                self.assertEqual('legacy-secret' if saved else 'local', persisted['llm']['api_key'])
                self.assertEqual(persisted['llm']['api_key'], persisted['llm_local']['api_key'])

    def test_endpoint_without_url_is_not_treated_as_changed(self):
        # A profile holding a placeholder key and NO base_url (the common
        # "not using a remote LLM" shape) must survive a plain GET-then-save.
        # The GET hands the browser the key sentinel; posting it back untouched
        # used to be read as "the endpoint changed" and demand a key for an
        # endpoint the user never edited.
        self.assertFalse(system.llm_endpoint_changed('', ''))
        self.assertFalse(system.llm_endpoint_changed(None, None))
        self.assertFalse(system.llm_endpoint_changed('  ', ''))
        self.assertTrue(system.llm_endpoint_changed('http://127.0.0.1:1236/v1', ''))
        self.assertTrue(system.llm_endpoint_changed('', 'http://127.0.0.1:1234/v1'))

    def test_get_then_save_placeholder_key_with_empty_url_succeeds(self):
        saved = {'llm': self.profile('http://127.0.0.1:1234/v1', 'local').model_dump(),
                 'llm_local': self.profile('http://127.0.0.1:1234/v1', 'local').model_dump(),
                 'llm_remote': self.profile('', 'local').model_dump(),
                 'generation': GenerationConfig().model_dump(),
                 'tts': TTSConfig().model_dump()}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'config.json')
            path.write_text(json.dumps(saved))
            application = FastAPI()
            application.include_router(system.router)
            with patch.object(system, 'CONFIG_PATH', str(path)), patch.object(system, 'project_manager', Mock()), TestClient(application) as client:
                incoming = client.get('/api/config').json()
                self.assertEqual('[REDACTED]', incoming['llm_remote']['api_key'])
                self.assertEqual('', incoming['llm_remote']['base_url'])
                untouched = client.post('/api/config', json=incoming)
                self.assertEqual(200, untouched.status_code, untouched.text)
                # Editing an unrelated value must not raise it either.
                incoming['generation']['three_pass_instruct_batch_size'] = 40
                edited = client.post('/api/config', json=incoming)
                self.assertEqual(200, edited.status_code, edited.text)
            persisted = json.loads(path.read_text())
            self.assertEqual('local', persisted['llm_remote']['api_key'])
            self.assertEqual('local', persisted['llm_local']['api_key'])
            self.assertEqual(40, persisted['generation']['three_pass_instruct_batch_size'])

    def test_clearing_a_real_endpoint_still_demands_an_explicit_key(self):
        # The relaxation is only for "no endpoint" == "no endpoint": removing a
        # URL that was set is a genuine change.
        existing = {'llm_remote': {'base_url': 'http://127.0.0.1:1236/v1', 'api_key': 'remote-secret'}}
        config = AppConfig(llm=self.profile('http://127.0.0.1:1234/v1', 'local'),
                           llm_remote=self.profile('', '[REDACTED]'), tts=TTSConfig())
        with self.assertRaises(HTTPException) as error:
            system._restore_redacted_secrets(config, existing)
        self.assertEqual(400, error.exception.status_code)
        self.assertIn('changed llm_remote endpoint', error.exception.detail)
