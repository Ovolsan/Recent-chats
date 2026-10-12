"""Verify metadata, hook signatures and composer target against exteraLess source."""
import ast
import importlib.util
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "Chat tags/.reference/exteraless"
JAVA = REPO / "TMessagesProj/src/main/java"
PYTHON = REPO / "TMessagesProj/src/main/python"


def main():
    spec = importlib.util.spec_from_file_location("metadata_parser", PYTHON / "extera_utils/metadata_parser.py")
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    metadata = parser.read_metadata(str(ROOT / "recent_chats.plugin"))
    assert metadata["id"] == "recent_chats", metadata
    assert set(metadata["permissions"]) == {"ui", "messages.read", "hooks"}, metadata
    tree = ast.parse((ROOT / "recent_chats.plugin").read_text(encoding="utf-8"))
    security = ast.parse((PYTHON / "extera_utils/plugin_loader.py").read_text(encoding="utf-8"))
    denied = next(ast.literal_eval(node.value.args[0]) for node in security.body
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name)
                  and t.id == "_JAVA_CLASS_DENIED" for t in node.targets))
    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                and isinstance(node.value, str)}
    assert not literals.intersection(denied), literals.intersection(denied)
    chat = (JAVA / "org/telegram/ui/ChatActivity.java").read_text(encoding="utf-8")
    hooks = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_hook":
            name, count = ast.literal_eval(node.args[0]), ast.literal_eval(node.args[1])
            signatures = re.findall(r"^    (?:public|private|protected)\s+\w+\s+" + re.escape(name)
                                    + r"\s*\(([^)]*)\)", chat, re.MULTILINE)
            counts = [len(sig.split(",")) if sig.strip() else 0 for sig in signatures]
            assert counts.count(count) == 1, (name, count, counts)
            hooks.append(name)
    assert len(hooks) == 4, hooks
    enter = (JAVA / "org/telegram/ui/Components/ChatActivityEnterView.java").read_text(encoding="utf-8")
    assert "private ImageView attachButton;" in enter
    assert "private FrameLayout audioVideoButtonContainer;" in enter
    assert "private boolean isAudioVideoSendButtonInMenuState()" in enter
    assert "return getAudioVideoSendButtonState() == ChatActivityEnterViewAnimatedIconView.State.MENU;" in enter
    assert "attachButton.setTag(1);" in enter and "targetRes = R.drawable.ic_ab_other;" in enter
    assert "attachButton.setTag(2);" in enter and "targetRes = R.drawable.input_attach;" in enter
    assert "attachButton.setOnTouchListener" not in enter, "Recheck existing touch listener compatibility"
    assert re.search(r"(?:private|protected) ChatActivityEnterView chatActivityEnterView;", chat)
    assert "private int chatMode" in chat
    sdk = (PYTHON / "android_utils.py").read_text(encoding="utf-8")
    assert "def OnTouchListener(fn):" in sdk
    controller = (JAVA / "org/telegram/messenger/MessagesController.java").read_text(encoding="utf-8")
    assert "boolean checkCanOpenChat(Bundle bundle, BaseFragment fragment)" in controller
    assert "public TLRPC.Dialog getDialog(long did)" in controller
    assert "public TopicsController getTopicsController()" in controller
    topics = (JAVA / "org/telegram/messenger/TopicsController.java").read_text(encoding="utf-8")
    assert "public int[] getForumUnreadCount(long chatId)" in topics
    assert "countsTmp[2] += topic.unread_reactions_count > 0 ? 1 : 0;" in topics
    chat_object = (JAVA / "org/telegram/messenger/ChatObject.java").read_text(encoding="utf-8")
    assert "public static boolean canManageMonoForum(int currentAccount, TLRPC.Chat chat)" in chat_object
    assert "public static boolean isMonoForum(TLRPC.Chat chat)" in chat_object
    cell = (JAVA / "org/telegram/ui/Cells/DialogCell.java").read_text(encoding="utf-8")
    for field in ("unread_count", "unread_mentions_count", "unread_reactions_count", "unread_mark"):
        assert "dialog." + field in cell, field
    theme = (JAVA / "org/telegram/ui/ActionBar/Theme.java").read_text(encoding="utf-8")
    for resource in ("filled_chatlist_mention", "filled_chatlist_reaction"):
        assert "R.drawable." + resource in theme, resource
    assert "key_dialogReactionMentionBackground" in theme
    bubble = (JAVA / "org/telegram/ui/Components/BubbleCounterPath.java").read_text(encoding="utf-8")
    assert "public static void addBubbleRect(Path path, RectF bounds, float radius)" in bubble
    assert "BubbleCounterPath.addBubbleRect" in cell
    notifications = (JAVA / "org/telegram/messenger/NotificationCenter.java").read_text(encoding="utf-8")
    for name in ("updateInterfaces", "dialogsNeedReload", "dialogsUnreadCounterChanged", "dialogsUnreadReactionsCounterChanged", "topicsDidLoaded"):
        assert "int " + name + " =" in notifications, name
    storage = (JAVA / "org/telegram/messenger/MessagesStorage.java").read_text(encoding="utf-8")
    for name in ("getUserSync", "getChatSync"):
        assert re.search(r"public TLRPC\.\w+ " + name + r"\(long \w+\)", storage), name
    print(json.dumps({"metadata": metadata, "hooks": hooks, "composer": "attachButton and audioVideoButtonContainer in MENU state", "result": "OK"},
                     indent=2))


if __name__ == "__main__":
    main()
