import 'dart:convert';

import 'package:timezone/timezone.dart' as tz;

enum ReminderKind { training, breakfast, lunch, dinner, water, measurement }

extension ReminderKindInfo on ReminderKind {
  String get label => switch (this) {
    ReminderKind.training => '训练',
    ReminderKind.breakfast => '早餐记录',
    ReminderKind.lunch => '午餐记录',
    ReminderKind.dinner => '晚餐记录',
    ReminderKind.water => '饮水',
    ReminderKind.measurement => '身体数据',
  };
  String get destination => switch (this) {
    ReminderKind.training => 'training',
    ReminderKind.water => 'water',
    ReminderKind.measurement => 'progress',
    _ => 'nutrition',
  };
  String get body => switch (this) {
    ReminderKind.training => '到你设置的训练时间了，打开查看安排，按状态决定是否训练。',
    ReminderKind.water => '到你设置的饮水提醒时间了，按需要补充水分，也可以记录饮水。',
    ReminderKind.measurement => '到你设置的身体数据记录时间了，可按相近条件测量并记录。',
    _ => '到你设置的$label时间了，可按实际情况补记。',
  };
}

class ReminderRule {
  ReminderRule({
    required this.kind,
    this.enabled = false,
    required List<int> times,
    required List<int> weekdays,
  }) : times = List.unmodifiable(times),
       weekdays = List.unmodifiable(weekdays) {
    if (times.isEmpty ||
        times.length > 6 ||
        times.toSet().length != times.length ||
        times.any((v) => v < 0 || v >= 1440) ||
        weekdays.isEmpty ||
        weekdays.length > 7 ||
        weekdays.toSet().length != weekdays.length ||
        weekdays.any((v) => v < 1 || v > 7)) {
      throw const FormatException('提醒时间或星期无效');
    }
  }
  final ReminderKind kind;
  final bool enabled;
  final List<int> times;
  final List<int> weekdays;
  ReminderRule copyWith({
    bool? enabled,
    List<int>? times,
    List<int>? weekdays,
  }) => ReminderRule(
    kind: kind,
    enabled: enabled ?? this.enabled,
    times: times ?? this.times,
    weekdays: weekdays ?? this.weekdays,
  );
  Map<String, dynamic> toJson() => {
    'kind': kind.name,
    'enabled': enabled,
    'times': times,
    'weekdays': weekdays,
  };
  factory ReminderRule.fromJson(Map<String, dynamic> json) => ReminderRule(
    kind: ReminderKind.values.byName(json['kind'] as String),
    enabled: json['enabled'] as bool,
    times: List<int>.from(json['times'] as List),
    weekdays: List<int>.from(json['weekdays'] as List),
  );
}

class LocalReminderSettings {
  LocalReminderSettings({
    this.enabled = false,
    this.hidePreview = true,
    this.quietEnabled = true,
    this.quietStart = 1320,
    this.quietEnd = 480,
    required List<ReminderRule> rules,
  }) : rules = List.unmodifiable(rules) {
    if (quietStart < 0 ||
        quietStart >= 1440 ||
        quietEnd < 0 ||
        quietEnd >= 1440 ||
        (quietEnabled && quietStart == quietEnd) ||
        rules.length != ReminderKind.values.length ||
        rules.map((v) => v.kind).toSet().length != rules.length) {
      throw const FormatException('提醒设置无效');
    }
  }
  factory LocalReminderSettings.defaults() => LocalReminderSettings(
    rules: [
      ReminderRule(
        kind: ReminderKind.training,
        times: [1080],
        weekdays: [1, 3, 5],
      ),
      for (final (kind, minute) in [
        (ReminderKind.breakfast, 480),
        (ReminderKind.lunch, 720),
        (ReminderKind.dinner, 1080),
      ])
        ReminderRule(
          kind: kind,
          times: [minute],
          weekdays: [1, 2, 3, 4, 5, 6, 7],
        ),
      ReminderRule(
        kind: ReminderKind.water,
        times: [540, 660, 840, 960, 1080],
        weekdays: [1, 2, 3, 4, 5, 6, 7],
      ),
      ReminderRule(kind: ReminderKind.measurement, times: [510], weekdays: [1]),
    ],
  );
  factory LocalReminderSettings.fromJson(Map<String, dynamic> json) {
    if (json['version'] != 1) throw const FormatException('提醒设置版本无效');
    return LocalReminderSettings(
      enabled: json['enabled'] as bool,
      hidePreview: json['hide_preview'] as bool,
      quietEnabled: json['quiet_enabled'] as bool,
      quietStart: json['quiet_start'] as int,
      quietEnd: json['quiet_end'] as int,
      rules: (json['rules'] as List)
          .map(
            (v) => ReminderRule.fromJson(Map<String, dynamic>.from(v as Map)),
          )
          .toList(),
    );
  }
  final bool enabled, hidePreview, quietEnabled;
  final int quietStart, quietEnd;
  final List<ReminderRule> rules;
  bool isQuiet(int minute) =>
      quietEnabled &&
      (quietStart < quietEnd
          ? minute >= quietStart && minute < quietEnd
          : minute >= quietStart || minute < quietEnd);
  LocalReminderSettings copyWith({
    bool? enabled,
    bool? hidePreview,
    bool? quietEnabled,
    int? quietStart,
    int? quietEnd,
    List<ReminderRule>? rules,
  }) => LocalReminderSettings(
    enabled: enabled ?? this.enabled,
    hidePreview: hidePreview ?? this.hidePreview,
    quietEnabled: quietEnabled ?? this.quietEnabled,
    quietStart: quietStart ?? this.quietStart,
    quietEnd: quietEnd ?? this.quietEnd,
    rules: rules ?? this.rules,
  );
  Map<String, dynamic> toJson() => {
    'version': 1,
    'enabled': enabled,
    'hide_preview': hidePreview,
    'quiet_enabled': quietEnabled,
    'quiet_start': quietStart,
    'quiet_end': quietEnd,
    'rules': rules.map((v) => v.toJson()).toList(),
  };
}

class ScheduledReminder {
  const ScheduledReminder({
    required this.id,
    required this.kind,
    required this.at,
    required this.payload,
    required this.hidePreview,
    this.repeat = true,
    this.weekly = false,
  });
  final int id;
  final ReminderKind kind;
  final tz.TZDateTime at;
  final String payload;
  final bool hidePreview, repeat, weekly;
}

class ReminderPlanner {
  static const testId = 39990;
  static bool ownsId(int id) => id >= 30000 && id < 31000 || id == testId;
  static String ownerFor(String server, String userId) =>
      base64Url.encode(utf8.encode('$server|$userId'));
  static String payload(String owner, ReminderKind kind) => jsonEncode({
    'feature': 'local_reminder',
    'version': 1,
    'owner': owner,
    'kind': kind.name,
  });
  static List<ScheduledReminder> build(
    LocalReminderSettings settings,
    String owner,
    tz.Location location,
    DateTime now,
  ) {
    if (!settings.enabled) return const [];
    final localNow = tz.TZDateTime.from(now, location);
    final result = <ScheduledReminder>[];
    for (final rule in settings.rules.where((v) => v.enabled)) {
      final days = rule.weekdays.length == 7
          ? [0]
          : (rule.weekdays.toList()..sort());
      for (var slot = 0; slot < rule.times.length; slot++) {
        final minute = rule.times[slot];
        if (settings.isQuiet(minute)) continue;
        for (final day in days) {
          final offset = day == 0 ? 0 : (day - localNow.weekday + 7) % 7;
          var at = tz.TZDateTime(
            location,
            localNow.year,
            localNow.month,
            localNow.day + offset,
            minute ~/ 60,
            minute % 60,
          );
          if (!at.isAfter(localNow)) {
            at = tz.TZDateTime(
              location,
              localNow.year,
              localNow.month,
              localNow.day + offset + (day == 0 ? 1 : 7),
              minute ~/ 60,
              minute % 60,
            );
          }
          result.add(
            ScheduledReminder(
              id: 30000 + rule.kind.index * 100 + slot * 10 + day,
              kind: rule.kind,
              at: at,
              payload: payload(owner, rule.kind),
              hidePreview: settings.hidePreview,
              weekly: day != 0,
            ),
          );
        }
      }
    }
    if (result.length > 63) throw const FormatException('提醒安排较多，请减少提醒时间或星期后重试');
    result.sort((a, b) => a.at.compareTo(b.at));
    return result;
  }
}

String reminderTime(int minute) =>
    '${(minute ~/ 60).toString().padLeft(2, '0')}:${(minute % 60).toString().padLeft(2, '0')}';
