import threading
import unittest
from unittest.mock import Mock

from beatrice.lostark_registration import LostArkRegistration
from beatrice.lostark.news import NewsApi
from beatrice.lostark.errors import (LostArkAuthError, LostArkNetworkError,
                                    LostArkRateLimitError, LostArkMaintenanceError)


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock()
        self.store.view.return_value = dict(configured=False, message='')
        self.store.save.return_value = True
        self.client = Mock()
        self.client.news.events.return_value = []
        self.factory = Mock(return_value=self.client)
        self.registration = LostArkRegistration(self.store, self.factory)

    def finish(self):
        self.registration.pending[2].join(timeout=2)
        return self.registration.poll()

    def test_news_endpoint(self):
        client = Mock()
        NewsApi(client).events()
        client.request.assert_called_once_with('GET', '/news/events')

    def test_valid_candidate_saved_only_on_owner_poll(self):
        owner = threading.get_ident()
        self.store.save.side_effect = lambda key: threading.get_ident() == owner
        self.assertTrue(self.registration.begin('candidate'))
        self.registration.pending[2].join(timeout=2)
        self.store.save.assert_not_called()
        result = self.registration.poll()
        self.assertTrue(result['success'])
        self.store.save.assert_called_once_with('candidate')
        self.factory.assert_called_once_with(key='candidate')
        self.client.news.events.assert_called_once()
        self.assertNotIn('candidate', str(result))

    def test_errors_keep_old_key_and_hide_candidate(self):
        self.store.view.return_value = dict(configured=True, message='')
        for error in [LostArkAuthError('candidate'), LostArkNetworkError('candidate'),
                      LostArkRateLimitError(), RuntimeError('candidate')]:
            self.client.news.events.side_effect = error
            self.assertTrue(self.registration.begin('candidate'))
            result = self.finish()
            self.assertFalse(result['success'])
            self.assertTrue(result['configured'])
            self.assertNotIn('candidate', str(result))
        self.store.save.assert_not_called()

    def test_invalid_news_payload_is_not_saved(self):
        self.client.news.events.return_value = {'error': 'candidate'}
        self.registration.begin('candidate')
        self.assertFalse(self.finish()['success'])
        self.store.save.assert_not_called()

    def test_maintenance_reports_service_state_and_keeps_old_key(self):
        self.store.view.return_value = dict(configured=True, message='')
        self.client.news.events.side_effect = LostArkMaintenanceError()
        self.registration.begin('candidate')
        result = self.finish()
        self.assertFalse(result['success'])
        self.assertTrue(result['configured'])
        self.assertIn('서버 점검', result['message'])
        self.assertNotIn('유효하지', result['message'])
        self.assertNotIn('candidate', str(result))
        self.store.save.assert_not_called()

    def test_duplicate_request_is_rejected(self):
        ready = threading.Event()
        self.client.news.events.side_effect = lambda: ready.wait(2) and []
        self.assertTrue(self.registration.begin('candidate'))
        self.assertFalse(self.registration.begin('other'))
        ready.set()
        self.finish()
        self.factory.assert_called_once()

    def test_shutdown_discards_ready_result(self):
        self.registration.begin('candidate')
        self.registration.pending[2].join(timeout=2)
        self.registration.stop()
        self.assertIsNone(self.registration.poll())
        self.store.save.assert_not_called()
        self.assertTrue(self.registration.settled)

    def test_invalid_candidate_never_calls_network(self):
        for value in [None, '', ' ', 'key\nother', 'x'*16385]:
            self.assertFalse(self.registration.begin(value))
        self.factory.assert_not_called()

    def test_storage_failure_does_not_report_success(self):
        self.store.save.return_value = False
        self.store.message = '저장하지 못했습니다.'
        self.registration.begin('candidate')
        result = self.finish()
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], self.store.message)
