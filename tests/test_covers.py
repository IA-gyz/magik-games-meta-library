import os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cover_retry import cover_retry_delay

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    from PySide6.QtGui import QPixmap, QColor
    from PySide6.QtNetwork import QNetworkReply
    from covers import Covers
except ImportError:
    Covers = None


class RetryPolicyTests(unittest.TestCase):
    def test_backoff_is_bounded_and_missing_images_wait_longer(self):
        self.assertEqual(
            [cover_retry_delay(n) for n in [1, 2, 3, 99]], [30, 60, 120, 900]
        )
        self.assertEqual(cover_retry_delay(1, 404), 21600)
        self.assertEqual(cover_retry_delay(1, invalid_image=True), 21600)

    def test_server_wait_is_honored(self):
        self.assertEqual(cover_retry_delay(1, 429, "120"), 120)
        self.assertEqual(
            cover_retry_delay(1, 429, "Thu, 01 Jan 1970 00:02:00 GMT", now=0), 120
        )
        for header in ["bad", "inf", "-1"]:
            self.assertEqual(cover_retry_delay(1, 429, header), 30)


@unittest.skipIf(Covers is None, "PySide6 required")
class CoverRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.covers = Covers(self.tmp.name)
        self.clock = 1000.0
        self.clock_patch = patch(
            "covers.time.monotonic", side_effect=lambda: self.clock
        )
        self.clock_patch.start()
        self.reply = Mock()
        self.reply.error.return_value = QNetworkReply.TimeoutError
        self.reply.property.return_value = None
        self.reply.attribute.return_value = None
        self.reply.rawHeader.return_value = QByteArray()
        self.get_patch = patch.object(self.covers, "get", return_value=self.reply)
        self.get = self.get_patch.start()
        self.url = "https://example.invalid/cover.png"

    def tearDown(self):
        self.covers.retry_timer.stop()
        self.get_patch.stop()
        self.clock_patch.stop()
        self.covers.deleteLater()
        self.q.processEvents()
        self.tmp.cleanup()

    def fail(self):
        self.covers.get_cover(self.url)
        self.covers.finish(self.reply, self.url)

    def png(self):
        pix = QPixmap(10, 10)
        pix.fill(QColor("blue"))
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        pix.save(buffer, "PNG")
        buffer.close()
        return data

    def test_failure_does_not_retry_before_deadline(self):
        self.fail()
        for _ in range(10):
            self.covers.get_cover(self.url)
        self.assertEqual(self.get.call_count, 1)
        self.assertEqual(self.covers.running, 0)
        self.clock += 30
        self.covers.get_cover(self.url)
        self.assertEqual(self.get.call_count, 2)

    def test_notification_is_once_and_never_downloads_by_itself(self):
        notices = []
        self.covers.ready.connect(notices.append)
        self.fail()
        notices.clear()
        self.clock += 30
        self.covers.retry_due()
        self.covers.retry_due()
        self.assertEqual(notices, [self.url])
        self.assertEqual(self.get.call_count, 1)
        self.assertFalse(self.covers.retry_timer.isActive())

    def test_visible_cover_can_retry_from_notification(self):
        self.fail()
        self.clock += 30
        self.covers.ready.connect(lambda url: self.covers.get_cover(url))
        self.covers.retry_due()
        self.assertEqual(self.get.call_count, 2)
        self.covers.get_cover(self.url)
        self.assertEqual(self.get.call_count, 2)

    def test_repeated_failure_increases_wait(self):
        self.fail()
        self.clock += 30
        self.fail()
        self.assertEqual(self.covers.failures[self.url]["retry_at"], self.clock + 60)

    def test_success_clears_failures_and_caches_image(self):
        self.fail()
        self.clock += 30
        self.covers.get_cover(self.url)
        self.reply.error.return_value = QNetworkReply.NoError
        self.reply.readAll.return_value = self.png()
        self.covers.finish(self.reply, self.url)
        self.assertNotIn(self.url, self.covers.failures)
        self.assertIsNotNone(self.covers.get_cover(self.url))
        self.assertEqual(self.get.call_count, 2)
        self.assertTrue(self.covers.path(self.url).exists())

    def test_server_retry_after_applies_to_failed_reply(self):
        self.reply.attribute.return_value = 429
        self.reply.rawHeader.return_value = QByteArray(b"120")
        self.fail()
        self.assertEqual(self.covers.failures[self.url]["retry_at"], 1120)

    def test_invalid_image_waits_and_releases_queue_slot(self):
        self.reply.error.return_value = QNetworkReply.NoError
        self.reply.readAll.return_value = QByteArray(b"not an image")
        self.fail()
        self.assertEqual(self.covers.failures[self.url]["retry_at"], 22600)
        self.assertEqual(self.covers.running, 0)
        self.assertNotIn(self.url, self.covers.queued)
        self.reply.deleteLater.assert_called_once()

    def test_four_download_limit_and_queue_continues_after_failure(self):
        for i in range(6):
            self.covers.get_cover(self.url + str(i))
        self.assertEqual(self.get.call_count, 4)
        self.assertEqual(len(self.covers.queue), 2)
        self.covers.finish(self.reply, self.url + "0")
        self.assertEqual(self.get.call_count, 5)
        self.assertEqual(self.covers.running, 4)

    def test_oversized_download_is_aborted_and_waits_longer(self):
        from covers import MAX_COVER_BYTES

        self.covers.get_cover(self.url)
        callback = self.reply.downloadProgress.connect.call_args.args[0]
        callback(MAX_COVER_BYTES + 1, -1)
        self.reply.abort.assert_called_once()
        self.reply.setProperty.assert_called_once_with("cover_size_exceeded", True)
        self.reply.property.return_value = True
        self.covers.finish(self.reply, self.url)
        self.assertEqual(self.covers.failures[self.url]["retry_at"], 22600)

    def test_very_long_server_delay_does_not_overflow_qt_timer(self):
        self.reply.rawHeader.return_value = QByteArray(b"1e300")
        self.fail()
        self.assertEqual(self.covers.retry_timer.interval(), 2_147_483_647)
        self.assertGreater(self.covers.failures[self.url]["retry_at"], self.clock)

    def test_disk_failure_keeps_usable_memory_image_and_cleans_temporary(self):
        self.covers.get_cover(self.url)
        self.reply.error.return_value = QNetworkReply.NoError
        self.reply.readAll.return_value = self.png()
        with patch("covers.Path.replace", side_effect=OSError("disk problem")):
            self.covers.finish(self.reply, self.url)
        self.assertIsNotNone(self.covers.get_cover(self.url))
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
