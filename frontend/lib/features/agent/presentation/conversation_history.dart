import '../domain/agent_models.dart';

class ConversationDayGroup {
  const ConversationDayGroup(this.label, this.items);
  final String label;
  final List<AgentConversation> items;
}

List<ConversationDayGroup> groupConversationsByDay(
  List<AgentConversation> items, {
  DateTime? now,
}) {
  final localNow = (now ?? DateTime.now()).toLocal();
  final today = DateTime(localNow.year, localNow.month, localNow.day);
  final yesterday = DateTime(today.year, today.month, today.day - 1);
  final sorted = [...items]
    ..sort((a, b) {
      final first = a.activityAt;
      final second = b.activityAt;
      if (first == null) return second == null ? a.id.compareTo(b.id) : 1;
      if (second == null) return -1;
      final order = second.compareTo(first);
      return order == 0 ? a.id.compareTo(b.id) : order;
    });
  final groups = <String, List<AgentConversation>>{};
  for (final item in sorted) {
    final at = item.activityAt?.toLocal();
    String label = '更早的对话';
    if (at != null) {
      final day = DateTime(at.year, at.month, at.day);
      label = day == today
          ? '今天'
          : day == yesterday
          ? '昨天'
          : '${day.year}年${day.month}月${day.day}日';
    }
    groups.putIfAbsent(label, () => []).add(item);
  }
  return [
    for (final entry in groups.entries)
      ConversationDayGroup(entry.key, entry.value),
  ];
}

String conversationTimeLabel(AgentConversation item) {
  final at = item.activityAt?.toLocal();
  if (at == null) return '';
  return '${at.hour.toString().padLeft(2, '0')}:${at.minute.toString().padLeft(2, '0')}';
}
