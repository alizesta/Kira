import unittest

from kira.ui.controllers import ChatAttachmentController


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class FakeRow:
    def __init__(self):
        self.widgets = [object()]  # trailing stretch spacer, matching the real tile strip

    def insertWidget(self, index, widget):
        self.widgets.insert(index, widget)

    def removeWidget(self, widget):
        if widget in self.widgets:
            self.widgets.remove(widget)

    def count(self):
        return len(self.widgets)


class FakeStrip:
    def __init__(self):
        self.row = FakeRow()
        self.visible = False

    def show(self):
        self.visible = True

    def setVisible(self, visible):
        self.visible = visible


class FakeLabel:
    def __init__(self):
        self.value = ""

    def setText(self, value):
        self.value = value

    def text(self):
        return self.value


class FakeWidget:
    def __init__(self):
        self.visible = False

    def setVisible(self, visible):
        self.visible = visible

    def show(self):
        self.visible = True


class FakeButton(FakeWidget):
    def setEnabled(self, enabled):
        self.enabled = enabled


class FakeTile:
    def __init__(self, name):
        self.name = name
        self.att = None
        self.deleted = False
        self.removeRequested = FakeSignal()
        self.progress = None

    def set_progress(self, value):
        self.progress = value

    def set_attachment(self, attachment):
        self.att = attachment

    def setParent(self, parent):
        self.parent = parent

    def deleteLater(self):
        self.deleted = True


class FakeWorker:
    def __init__(self, paths):
        self.paths = list(paths)
        self.progress = FakeSignal()
        self.loaded = FakeSignal()
        self.failed = FakeSignal()
        self.finished = FakeSignal()
        self.running = False
        self.cancelled = []
        self.started = False

    def start(self):
        self.started = True
        self.running = True

    def isRunning(self):
        return self.running

    def cancel(self, index):
        self.cancelled.append(index)

    def finish(self):
        self.running = False
        self.finished.emit()


class FakeAttachmentApi:
    class AttachmentError(ValueError):
        pass


class ChatAttachmentControllerTests(unittest.TestCase):
    def setUp(self):
        self.strip = FakeStrip()
        self.error_label = FakeLabel()
        self.error_widget = FakeWidget()
        self.error_close = FakeWidget()
        self.send_button = FakeButton()
        self.workers = []
        self.controller = ChatAttachmentController(
            attach_strip=self.strip,
            error_label=self.error_label,
            error_widget=self.error_widget,
            error_close_button=self.error_close,
            send_button=self.send_button,
            is_chat_busy=lambda: False,
            tile_factory=FakeTile,
            worker_factory=self.make_worker,
            attachment_api=FakeAttachmentApi,
            max_files=2,
        )

    def make_worker(self, paths):
        worker = FakeWorker(paths)
        self.workers.append(worker)
        return worker

    def test_add_paths_creates_tiles_and_starts_injected_worker(self):
        self.controller.add_paths(["one.txt", "two.txt"])
        self.assertEqual([tile.name for tile in self.controller.tiles], ["one.txt", "two.txt"])
        self.assertEqual(self.workers[0].paths, ["one.txt", "two.txt"])
        self.assertTrue(self.workers[0].started)
        self.assertFalse(self.send_button.enabled)

    def test_loaded_payload_is_exposed_without_window_state(self):
        self.controller.add_paths(["one.txt"])
        payload = {"name": "one.txt", "kind": "text", "text": "hello"}
        self.workers[0].loaded.emit(0, payload)
        self.assertEqual(self.controller.attachments, [payload])
        self.assertEqual(self.controller.tiles[0].progress, 100)

    def test_worker_completion_restores_send_button_and_clears_loading_notice(self):
        self.controller.add_paths(["one.txt"])
        self.workers[0].finish()
        self.assertTrue(self.send_button.enabled)
        self.assertNotIn(self.controller.LOADING_TEXT, self.error_label.value)
        self.assertFalse(self.error_widget.visible)

    def test_file_limit_is_enforced_before_worker_creation(self):
        self.controller.add_paths(["one.txt", "two.txt", "three.txt"])
        self.assertEqual(self.workers[0].paths, ["one.txt", "two.txt"])
        self.assertIn("حداکثر 2", self.error_label.value)

    def test_cancel_stops_reads_and_clears_selected_tiles(self):
        self.controller.add_paths(["one.txt", "two.txt"])
        self.controller.cancel()
        self.assertEqual(self.workers[0].cancelled, [0, 1])
        self.assertEqual(self.controller.tiles, [])
        self.assertEqual(self.strip.row.count(), 1)  # the stretch spacer remains
        self.assertFalse(self.error_widget.visible)


if __name__ == "__main__":
    unittest.main()
