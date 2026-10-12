import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
base = types.ModuleType("base_plugin")
base.BasePlugin = object
with patch.dict(sys.modules, {"base_plugin": base}):
    loader = importlib.machinery.SourceFileLoader("recent_chats", str(ROOT / "recent_chats.plugin"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    plugin = importlib.util.module_from_spec(spec)
    loader.exec_module(plugin)


class HistoryTests(unittest.TestCase):
    def test_revisit_moves_to_bottom_and_excludes_current(self):
        history = plugin.RecentHistory()
        for did in (11, -22, 33, 11):
            history.visit(100, did, str(did))
        self.assertEqual([r["did"] for r in history.rows(100)], [-22, 33, 11])
        self.assertEqual([r["did"] for r in history.rows(100, 11)], [-22, 33])
        self.assertFalse(history.visit(100, 11, "11"))

    def test_persistence_and_account_slot_reuse(self):
        history = plugin.RecentHistory()
        history.visit(100, 11, "First")
        history.visit(200, 22, "Second")
        restored = plugin.RecentHistory(history.dump())
        self.assertEqual(restored.rows(100), [{"did": 11, "title": "First"}])
        self.assertEqual(restored.rows(200), [{"did": 22, "title": "Second"}])
        self.assertEqual(restored.rows(300), [])

    def test_capacity_retains_newest_and_snapshots_are_independent(self):
        history = plugin.RecentHistory()
        for did in range(1, 75):
            history.visit(100, did, "Chat")
        rows = history.rows(100)
        self.assertEqual(len(rows), 50)
        self.assertEqual((rows[0]["did"], rows[-1]["did"]), (25, 74))
        rows[0]["title"] = "Modified"
        payload = history.dump()
        payload["accounts"]["100"].clear()
        self.assertEqual(history.rows(100)[0]["title"], "Chat")
        self.assertEqual(len(history.rows(100)), 50)

    def test_partial_corruption_does_not_drop_valid_history(self):
        history = plugin.RecentHistory({"version": 1, "accounts": {
            "bad": [{"did": 1}], "0": [{"did": 1}],
            "100": [None, {}, {"did": "no"}, {"did": 1 << 90},
                    {"did": -22, "title": "Group"}, {"did": 11},
                    {"did": -22, "title": "Renamed"}],
        }})
        self.assertEqual(history.rows(100), [{"did": 11, "title": "Чат"},
                                             {"did": -22, "title": "Renamed"}])

    def test_invalid_root_and_zero_ids(self):
        for payload in (None, [], "bad", {"version": 2}, {"version": 1, "accounts": []}):
            self.assertEqual(plugin.RecentHistory(payload).dump()["accounts"], {})
        history = plugin.RecentHistory()
        self.assertFalse(history.visit(0, 11, "Chat"))
        self.assertFalse(history.visit(100, 0, "Chat"))


class GestureTests(unittest.TestCase):
    def test_upward_swipe_with_small_horizontal_motion(self):
        swipe = plugin.UpwardSwipe(24, 8)
        swipe.begin(100, 800)
        self.assertFalse(swipe.move(102, 795))
        self.assertFalse(swipe.move(102, 780))
        self.assertTrue(swipe.move(105, 770))
        self.assertTrue(swipe.move(150, 800))

    def test_tap_downward_horizontal_and_cancel(self):
        for x, y in ((100, 800), (120, 800), (100, 820), (140, 770)):
            swipe = plugin.UpwardSwipe(24, 8)
            swipe.begin(100, 800)
            self.assertFalse(swipe.move(x, y))
        swipe.reset()
        self.assertFalse(swipe.move(100, 700))

    def test_horizontal_gesture_cannot_turn_into_upward_swipe(self):
        swipe = plugin.UpwardSwipe(24, 8)
        swipe.begin(100, 800)
        swipe.move(120, 800)
        self.assertFalse(swipe.move(100, 700))

    def test_touch_preserves_native_tap_and_cancels_swipe_click(self):
        instance = plugin.RecentChatsPlugin()
        instance._active = True
        instance._show_popup = Mock()
        instance._report = Mock()
        cancel = Mock()
        instance.Motion = Mock()
        instance.Motion.obtain.return_value = cancel
        view = Mock()
        view.getTag.return_value = "1"
        state = {"swipe": plugin.UpwardSwipe(24, 8), "original": None}

        def event(action, x=100, y=800):
            return types.SimpleNamespace(getActionMasked=lambda: action,
                                         getRawX=lambda: x, getRawY=lambda: y)

        self.assertFalse(instance._touch(state, view, event(0)))
        self.assertFalse(instance._touch(state, view, event(1)))
        instance._show_popup.assert_not_called()
        view.onTouchEvent.assert_not_called()
        instance._touch(state, view, event(0))
        self.assertTrue(instance._touch(state, view, event(2, y=770)))
        self.assertTrue(instance._touch(state, view, event(1, y=750)))
        instance._show_popup.assert_called_once_with(state)
        view.onTouchEvent.assert_called_once_with(cancel)
        cancel.setAction.assert_called_once_with(3)
        cancel.recycle.assert_called_once()
        view.performClick.assert_not_called()
        view.getParent().requestDisallowInterceptTouchEvent.assert_called_with(False)

    def test_empty_composer_swipe_opens_list_and_cancel_does_not(self):
        instance = plugin.RecentChatsPlugin()
        instance._active = True
        instance._show_popup = Mock()
        instance._report = Mock()
        instance.Motion = Mock()
        view = Mock()
        state = {"swipe": plugin.UpwardSwipe(24, 8), "original": None}
        def event(action, y):
            return types.SimpleNamespace(getActionMasked=lambda: action,
                                         getRawX=lambda: 100, getRawY=lambda: y)
        view.getTag.return_value = "2"
        self.assertFalse(instance._touch(state, view, event(0, 800)))
        self.assertTrue(instance._touch(state, view, event(2, 770)))
        self.assertTrue(instance._touch(state, view, event(1, 750)))
        instance._show_popup.assert_called_once_with(state)
        instance._show_popup.reset_mock()
        view.getTag.return_value = "1"
        instance._touch(state, view, event(0, 800))
        instance._touch(state, view, event(2, 770))
        self.assertTrue(instance._touch(state, view, event(3, 750)))
        instance._show_popup.assert_not_called()

    def test_separate_dots_button_swipe_and_voice_state_passthrough(self):
        instance = plugin.RecentChatsPlugin()
        instance._active = True
        instance._show_popup = Mock()
        instance._report = Mock()
        instance.Motion = Mock()
        instance._is_menu_state = Mock(return_value=True)
        view = Mock()
        original = Mock()
        original.onTouch.return_value = False
        state = {"swipe": plugin.UpwardSwipe(24, 8), "original": original,
                 "enter": Mock(), "menu_only": True}
        def event(action, y):
            return types.SimpleNamespace(getActionMasked=lambda: action,
                                         getRawX=lambda: 100, getRawY=lambda: y)
        self.assertFalse(instance._touch(state, view, event(0, 800)))
        self.assertTrue(instance._touch(state, view, event(2, 770)))
        self.assertTrue(instance._touch(state, view, event(1, 750)))
        instance._show_popup.assert_called_once_with(state)
        instance._show_popup.reset_mock()
        view.reset_mock()
        original.reset_mock()
        instance._is_menu_state.return_value = False
        for action, y in ((0, 800), (2, 770), (1, 750)):
            self.assertFalse(instance._touch(state, view, event(action, y)))
        self.assertEqual(original.onTouch.call_count, 3)
        instance._show_popup.assert_not_called()
        view.onTouchEvent.assert_not_called()
        view.getParent.assert_not_called()

    def test_both_button_listeners_are_restored_on_detach(self):
        instance = plugin.RecentChatsPlugin()
        instance._states = {}
        instance._key = id
        instance._dp = int
        instance.ViewConfig = Mock()
        instance.ViewConfig.get().getScaledTouchSlop.return_value = 8
        first, second = Mock(), Mock()
        first_info, second_info = Mock(), Mock()
        first_original, second_original = Mock(), Mock()
        first_info.listener, second_info.listener = first_original, second_original
        first.setOnTouchListener.side_effect = lambda listener: setattr(first_info, "listener", listener)
        second.setOnTouchListener.side_effect = lambda listener: setattr(second_info, "listener", listener)
        enter, fragment = Mock(), Mock()
        def get(obj, field):
            if obj is fragment:
                return enter
            if obj is enter:
                return first if field == "attachButton" else second
            if obj is first or obj is second:
                return first_info if obj is first else second_info
            return obj.listener
        instance._get = get
        android = types.ModuleType("android_utils")
        android.OnTouchListener = lambda fn: fn
        with patch.dict(sys.modules, {"android_utils": android}):
            instance._attach(fragment)
            states = instance._states[id(fragment)]
            self.assertEqual(len(states), 2)
            self.assertFalse(states[0]["menu_only"])
            self.assertTrue(states[1]["menu_only"])
            instance._detach(id(fragment))
            first.setOnTouchListener.assert_called_with(first_original)
            second.setOnTouchListener.assert_called_with(second_original)
            self.assertEqual(instance._states, {})


class CounterAndLayoutTests(unittest.TestCase):
    def test_messages_mentions_and_reactions_are_separate(self):
        dialog = types.SimpleNamespace(unread_count=12, unread_mentions_count=2,
                                       unread_reactions_count=3, unread_mark=False)
        values = plugin.dialog_counters(dialog, True)
        self.assertEqual(values, (12, 2, 3, False, True))
        self.assertEqual(plugin.counter_events(values), [
            ("reaction", 3, False, "Непрочитанные реакции"),
            ("mention", 2, False, "Непрочитанные упоминания"),
            ("message", 12, True, "Непрочитанные сообщения")])

    def test_mentions_and_reactions_do_not_require_unread_messages(self):
        self.assertEqual([(r[0], r[1]) for r in plugin.counter_events((0, 1, 2, False, False))],
                         [("reaction", 2), ("mention", 1)])
        self.assertEqual(plugin.counter_events((0, 0, 0, False, False)), [])
        self.assertEqual(plugin.counter_events((0, 0, 0, True, True))[0],
                         ("message", 0, True, "Непрочитанные сообщения"))

    def test_missing_dialog_and_negative_counts(self):
        self.assertEqual(plugin.dialog_counters(None), (0, 0, 0, False, False))
        dialog = types.SimpleNamespace(unread_count=-1, unread_mentions_count=-2,
                                       unread_reactions_count=-3, unread_mark=False)
        self.assertEqual(plugin.dialog_counters(dialog), (0, 0, 0, False, False))

    def test_forum_reaction_is_visible_when_base_dialog_has_zero(self):
        instance = plugin.RecentChatsPlugin()
        instance._jlong = int
        instance.ChatObject = Mock()
        instance.ChatObject.isMonoForum.return_value = False
        controller = Mock()
        controller.getChat.return_value = types.SimpleNamespace(id=11, forum=True, monoforum=False)
        controller.getTopicsController().getForumUnreadCount.return_value = [1, 0, 1, 1, 0]
        dialog = types.SimpleNamespace(unread_count=1, unread_mentions_count=0,
                                       unread_reactions_count=0, unread_mark=False)
        counters = instance._native_counters(controller, 2, -11, dialog, False)
        self.assertEqual(counters, (1, 0, 1, False, False))
        self.assertEqual([row[0] for row in plugin.counter_events(counters)], ["reaction", "message"])
        controller.getChat.assert_called_once_with(11)
        controller.getTopicsController().getForumUnreadCount.assert_called_once_with(11)

    def test_read_topics_clear_stale_dialog_counters(self):
        dialog = types.SimpleNamespace(unread_count=99, unread_mentions_count=4,
                                       unread_reactions_count=3, unread_mark=False)
        counters = plugin.dialog_counters(dialog, True, [0, 0, 0, 0, 0])
        self.assertEqual(counters, (0, 0, 0, False, True))
        self.assertEqual(plugin.counter_events(counters), [])
        dialog.unread_mark = True
        self.assertTrue(plugin.dialog_counters(dialog, True, [0, 0, 0, 0, 0])[3])

    def test_forum_counter_color_uses_unmuted_unread_topics(self):
        instance = plugin.RecentChatsPlugin()
        instance._jlong = int
        instance.ChatObject = Mock()
        instance.ChatObject.isMonoForum.return_value = False
        controller = Mock()
        controller.getChat.return_value = types.SimpleNamespace(id=11, forum=True, monoforum=False)
        topic_method = controller.getTopicsController().getForumUnreadCount
        topic_method.return_value = [2, 1, 3, 0, 0]
        self.assertEqual(instance._native_counters(controller, 2, -11, None, False),
                         (2, 1, 3, False, True))
        topic_method.return_value = [2, 1, 3, 10, 0]
        self.assertEqual(instance._native_counters(controller, 2, -11, None, True),
                         (2, 1, 3, False, False))

    def test_ordinary_chat_keeps_its_own_counters(self):
        instance = plugin.RecentChatsPlugin()
        instance._jlong = int
        instance.ChatObject = Mock()
        instance.ChatObject.isMonoForum.return_value = False
        controller = Mock()
        dialog = types.SimpleNamespace(unread_count=12, unread_mentions_count=2,
                                       unread_reactions_count=3, unread_mark=False)
        controller.getChat.return_value = types.SimpleNamespace(id=11, forum=False, monoforum=False)
        self.assertEqual(instance._native_counters(controller, 2, -11, dialog, True),
                         (12, 2, 3, False, True))
        controller.getTopicsController.assert_not_called()
        controller.reset_mock()
        self.assertEqual(instance._native_counters(controller, 2, 11, dialog, False),
                         (12, 2, 3, False, False))
        controller.getChat.assert_not_called()
        controller.getTopicsController.assert_not_called()

    def test_monoforum_uses_topic_aggregates_only_with_management_rights(self):
        instance = plugin.RecentChatsPlugin()
        instance._jlong = int
        instance.ChatObject = Mock()
        instance.ChatObject.isMonoForum.return_value = True
        controller = Mock()
        chat = types.SimpleNamespace(id=11, forum=False, monoforum=True)
        controller.getChat.return_value = chat
        dialog = types.SimpleNamespace(unread_count=12, unread_mentions_count=2,
                                       unread_reactions_count=3, unread_mark=False)
        instance.ChatObject.canManageMonoForum.return_value = False
        self.assertEqual(instance._native_counters(controller, 2, -11, dialog, True),
                         (12, 0, 3, False, True))
        controller.getTopicsController.assert_not_called()
        instance.ChatObject.canManageMonoForum.return_value = True
        controller.getTopicsController().getForumUnreadCount.return_value = [4, 5, 6, 100, 0]
        self.assertEqual(instance._native_counters(controller, 2, -11, dialog, True),
                         (4, 0, 6, False, True))
        instance.ChatObject.canManageMonoForum.assert_called_with(2, chat)

    def test_full_width_and_exact_composer_anchor(self):
        self.assertEqual(plugin.popup_geometry(0, 96, 1080, 2053, 2, 127, 889), (0, 1799, 1080, 254))
        self.assertEqual(plugin.popup_geometry(0, 96, 1080, 1422, 2, 127, 889), (0, 1168, 1080, 254))
        self.assertEqual(plugin.popup_geometry(40, 96, 820, 700, 50, 127, 889), (40, 96, 780, 604))
        self.assertEqual(plugin.popup_geometry(0, 96, 1080, 2053, 50, 127, 1957), (0, 96, 1080, 1957))

    def _pull_fixture(self, scale=127 / 48):
        instance = plugin.RecentChatsPlugin()
        instance._active = True
        instance._dp = lambda value: round(value * scale)
        instance._report = Mock()
        instance.Motion = Mock()
        scroll, spacer = Mock(), Mock()
        scroll.getScrollY.return_value = 0
        popup = {"scroll": scroll, "spacer": spacer, "spacer_height": 0, "height": 1957,
                 "touch_start": None, "touch_pull": None, "top": 96}
        instance._popup = popup
        return instance, popup, scroll, spacer

    @staticmethod
    def _pull_event(action, y):
        return types.SimpleNamespace(getActionMasked=lambda: action,
                                     getRawX=lambda: 500, getRawY=lambda: y)

    def test_extra_downward_pull_follows_finger_without_initial_jump(self):
        instance, popup, scroll, spacer = self._pull_fixture()
        event = self._pull_event
        instance._list_touch(popup, event(0, 500))
        instance._list_touch(popup, event(2, 540))
        self.assertEqual(popup["spacer_height"], 0)
        self.assertTrue(instance._list_touch(popup, event(2, 600)))
        self.assertEqual(popup["spacer_height"], 0)
        spacer.setLayoutParams.assert_not_called()
        for y in (625, 650, 700):
            instance._list_touch(popup, event(2, y))
            self.assertEqual(popup["spacer_height"], y - 600)
            self.assertEqual(spacer.getLayoutParams().height, y - 600)
        self.assertEqual(popup["height"], 1957)
        self.assertTrue(instance._list_touch(popup, event(1, 700)))
        self.assertEqual(popup["spacer_height"], 100)
        self.assertIsNone(popup["touch_pull"])
        # Native scrolling is cancelled once; UP is consumed to prevent a fling.
        instance.Motion.obtain.assert_called_once()
        cancel = instance.Motion.obtain.return_value
        cancel.setAction.assert_called_once_with(3)
        scroll.onTouchEvent.assert_called_once_with(cancel)
        cancel.recycle.assert_called_once()
        instance._report.assert_not_called()

    def test_lowering_can_continue_on_next_drag_and_reverse_within_drag(self):
        instance, popup, scroll, spacer = self._pull_fixture()
        event = self._pull_event
        instance._list_touch(popup, event(0, 500))
        instance._list_touch(popup, event(2, 600))
        instance._list_touch(popup, event(2, 1000))
        instance._list_touch(popup, event(1, 1000))
        self.assertEqual(popup["spacer_height"], 400)
        instance._list_touch(popup, event(0, 700))
        instance._list_touch(popup, event(2, 800))
        self.assertEqual(popup["spacer_height"], 400)
        instance._list_touch(popup, event(2, 1000))
        self.assertEqual(popup["spacer_height"], 600)
        instance._list_touch(popup, event(2, 900))
        self.assertEqual(popup["spacer_height"], 500)
        instance._list_touch(popup, event(2, 2200))
        self.assertEqual(popup["spacer_height"], 1068)
        instance._list_touch(popup, event(2, 0))
        self.assertEqual(popup["spacer_height"], 0)
        instance._report.assert_not_called()

    def test_pull_handoff_preserves_visible_gap_after_native_scrolling(self):
        instance, popup, scroll, spacer = self._pull_fixture()
        event = self._pull_event
        popup["spacer_height"] = 400
        scroll.getScrollY.return_value = 300
        instance._list_touch(popup, event(0, 500))
        scroll.getScrollY.return_value = 240
        instance._list_touch(popup, event(2, 600))
        self.assertEqual(popup["spacer_height"], 160)
        scroll.scrollTo.assert_called_with(0, 0)
        scroll.getScrollY.return_value = 0
        instance._list_touch(popup, event(2, 625))
        self.assertEqual(popup["spacer_height"], 185)
        instance._report.assert_not_called()

    def test_ordinary_scroll_to_oldest_does_not_lower_them_in_same_gesture(self):
        instance, popup, scroll, spacer = self._pull_fixture(scale=1)
        instance._lower_oldest = Mock()
        scroll.getScrollY.return_value = 300
        event = self._pull_event
        instance._list_touch(popup, event(0, 500))
        scroll.getScrollY.return_value = 0
        instance._list_touch(popup, event(2, 800))
        instance._list_touch(popup, event(1, 800))
        instance._lower_oldest.assert_not_called()
        instance._list_touch(popup, event(0, 500))
        instance._list_touch(popup, event(2, 600))
        instance._lower_oldest.assert_called_once_with(popup, 0)

    def test_row_cancel_preserves_coordinates_when_scrollview_takes_drag(self):
        instance, popup, scroll, spacer = self._pull_fixture(scale=1)
        instance._lower_oldest = Mock()
        event = self._pull_event
        instance._list_touch(popup, event(0, 500), is_scroll=False)
        instance._list_touch(popup, event(3, 530), is_scroll=False)
        self.assertEqual(popup["touch_start"], (500.0, 500.0, 0))
        instance._list_touch(popup, event(2, 600), is_scroll=True)
        instance._lower_oldest.assert_called_once_with(popup, 0)
        instance._list_touch(popup, event(2, 650), is_scroll=True)
        instance._lower_oldest.assert_called_with(popup, 50)

    def test_refresh_is_coalesced_and_cancelled_after_dismissal(self):
        instance = plugin.RecentChatsPlugin()
        popup = {"refresh_scheduled": False}
        instance._popup = popup
        instance._refresh_badges = Mock()
        android = types.ModuleType("android_utils")
        pending = []
        android.run_on_ui_thread = lambda fn, delay: pending.append(fn)
        with patch.dict(sys.modules, {"android_utils": android}):
            instance._queue_badge_refresh(popup)
            instance._queue_badge_refresh(popup)
            self.assertEqual(len(pending), 1)
            pending.pop()()
            instance._refresh_badges.assert_called_once_with(popup)
            instance._queue_badge_refresh(popup)
            instance._popup = None
            pending.pop()()
            self.assertFalse(popup["refresh_scheduled"])
            instance._refresh_badges.assert_called_once()

    def test_observers_removed_when_popup_closes(self):
        instance = plugin.RecentChatsPlugin()
        observer = Mock()
        center = Mock()
        popup = {"observer": observer, "notification_center": center, "observed": [1, 2, 3, 4, 5],
                 "account": 2, "scroll": Mock(), "list_rows": []}
        instance._popup = popup
        instance._popup_closed(popup)
        self.assertEqual(center.removeObserver.call_count, 5)
        center.removeObserver.assert_called_with(observer, 5)
        self.assertIsNone(instance._popup)
        self.assertEqual(popup["observed"], [])


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.instance = plugin.RecentChatsPlugin()
        self.instance._active = True
        self.instance._generation = 0
        self.instance._dismiss_popup = Mock()
        self.instance._uid = Mock(return_value=100)
        self.instance._jlong = int
        self.fragment = Mock()
        self.controller, self.storage = Mock(), Mock()
        self.controller.getEncryptedChat.return_value = types.SimpleNamespace(user_id=11)
        self.instance.Controller = Mock()
        self.instance.Controller.getInstance.return_value = self.controller
        self.instance.Storage = Mock()
        self.instance.Storage.getInstance.return_value = self.storage
        self.bundle = Mock()
        self.instance.Bundle = Mock(return_value=self.bundle)
        self.instance.Chat = Mock()
        self.background, self.ui = [], []
        client = types.ModuleType("client_utils")
        client.get_last_fragment = lambda: self.fragment
        client.run_on_queue = lambda fn, queue: self.background.append(fn)
        android = types.ModuleType("android_utils")
        android.run_on_ui_thread = lambda fn: self.ui.append(fn)
        self.module_patch = patch.dict(sys.modules, {"client_utils": client, "android_utils": android})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)

    def open(self, did):
        self.instance._open_dialog(self.fragment, 2, 100, did)
        self.background.pop()()

    def test_navigation_uses_correct_account_and_replaces_current_chat(self):
        for did, kind, peer_id in ((11, "user_id", 11), (-22, "chat_id", 22),
                                   (0x4000000000000000 | 33, "enc_id", 33)):
            with self.subTest(did=did):
                self.open(did)
                self.ui.pop()()
                self.instance.Controller.getInstance.assert_called_with(2)
                self.instance.Chat().setCurrentAccount.assert_called_with(2)
                self.fragment.presentFragment.assert_called_with(self.instance.Chat(), True)
                if kind == "enc_id":
                    self.bundle.putInt.assert_called_with(kind, peer_id)
                    self.controller.putUser.assert_called()
                else:
                    self.bundle.putLong.assert_called_with(kind, peer_id)

    def test_missing_cache_loads_from_storage(self):
        self.controller.getChat.return_value = None
        self.open(-22)
        self.storage.getChatSync.assert_called_once_with(22)
        self.ui.pop()()
        self.controller.putChat.assert_called_with(self.storage.getChatSync(), True)

    def test_logout_and_fragment_change_cancel_pending_navigation(self):
        self.open(11)
        self.instance._uid.return_value = 200
        self.ui.pop()()
        self.fragment.presentFragment.assert_not_called()
        self.instance._uid.return_value = 100
        self.open(11)
        self.instance._generation += 1
        self.ui.pop()()
        self.fragment.presentFragment.assert_not_called()

    def test_denied_chat_does_not_navigate(self):
        self.controller.checkCanOpenChat.return_value = False
        self.open(-22)
        self.ui.pop()()
        self.fragment.presentFragment.assert_not_called()

    def test_zero_dialog_rejected(self):
        with self.assertRaises(ValueError):
            plugin.dialog_arguments(0)


if __name__ == "__main__":
    unittest.main()
