import 'dart:async';
import 'dart:convert';

import 'package:timezone/timezone.dart' as tz;

import '../offline/local_records.dart';
import '../state/lifecycle_notifier.dart';
import 'reminder_models.dart';
import 'reminder_platform.dart';

class LocalReminderController extends LifecycleNotifier {
  LocalReminderController(
    this._store,
    this.platform, {
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;
  final LocalDataStore _store;
  final ReminderPlatform platform;
  final DateTime Function() _now;
  Future<void> _tail = Future.value();
  Future<void>? _initialized;
  String? _owner, _lastApplied, _waitingPayload;
  String? _server, _userId;
  ReminderKind? _navigation;
  bool loaded = false, busy = false;
  String? errorMessage, message;
  ReminderPermission permission = ReminderPermission.denied;
  tz.Location? deviceLocation;
  LocalReminderSettings settings = LocalReminderSettings.defaults();
  List<ScheduledReminder> planned = const [];
  Set<int> scheduledIds = {};
  String? get owner => _owner;
  bool get hasNavigation => _navigation != null;
  int get scheduledCount =>
      scheduledIds.where((id) => id != ReminderPlanner.testId).length;
  int get skippedTimes => settings.rules
      .where((r) => r.enabled)
      .fold(0, (sum, r) => sum + r.times.where(settings.isQuiet).length);

  Future<void> initialize() {
    final existing = _initialized;
    if (existing != null) return existing;
    final task = () async {
      final launch = await platform.initialize(_captureTap);
      if (launch != null) _waitingPayload = launch;
    }();
    _initialized = task;
    return task.catchError((Object error, StackTrace stack) {
      if (identical(_initialized, task)) _initialized = null;
      Error.throwWithStackTrace(error, stack);
    });
  }

  Future<T> _serial<T>(Future<T> Function() action) async {
    final before = _tail;
    final release = Completer<void>();
    _tail = release.future;
    await before;
    try {
      return await action();
    } finally {
      release.complete();
    }
  }

  Future<void> activate(String server, String userId) {
    _server = server;
    _userId = userId;
    return _serial(() async {
      busy = true;
      notifyListeners();
      try {
        await initialize();
        final next = ReminderPlanner.ownerFor(server, userId);
        if (_owner != next || !loaded) {
          await platform.cancelManaged();
          _owner = next;
          loaded = false;
          _lastApplied = null;
          settings = LocalReminderSettings.defaults();
          planned = const [];
          scheduledIds = {};
          final raw = await _store.read('reminders.$next');
          if (raw != null) {
            settings = LocalReminderSettings.fromJson(
              Map<String, dynamic>.from(jsonDecode(raw) as Map),
            );
          }
          loaded = true;
        }
        await _reconcile();
        _deliverWaitingTap();
      } on Object {
        errorMessage = '本机提醒设置暂时无法读取或安排，已保留原设置，请重试';
      } finally {
        busy = false;
        _deliverWaitingTap();
        notifyListeners();
      }
    });
  }

  Future<void> deactivate() {
    // Stop an in-flight permission/save operation before it can schedule again.
    _server = null;
    _userId = null;
    _owner = null;
    loaded = false;
    _waitingPayload = null;
    _navigation = null;
    settings = LocalReminderSettings.defaults();
    planned = const [];
    _lastApplied = null;
    return _serial(() async {
      try {
        await initialize();
        await platform.cancelManaged();
        scheduledIds = {};
        await _store.delete('reminders.active');
      } on Object {
        errorMessage = '提醒清理未完成，请重新打开 App 后核对系统通知设置';
      }
      notifyListeners();
    });
  }

  Future<void> refresh({bool force = false}) async {
    if (busy) return;
    if (!loaded && _server != null && _userId != null) {
      await activate(_server!, _userId!);
      return;
    }
    await _serial(() async {
      busy = true;
      notifyListeners();
      try {
        await initialize();
        if (_owner == null) {
          await platform.cancelManaged();
          scheduledIds = {};
          return;
        }
        if (!loaded) return;
        if (force) _lastApplied = null;
        await _reconcile();
      } on Object {
        errorMessage = '暂时无法更新系统提醒状态，请重试';
      } finally {
        busy = false;
        _deliverWaitingTap();
        notifyListeners();
      }
    });
  }

  Future<bool> setEnabled(bool value) =>
      _change((s) => s.copyWith(enabled: value), request: value);
  Future<bool> setRule(ReminderRule rule) => _change(
    (s) => s.copyWith(
      rules: [
        for (final current in s.rules)
          current.kind == rule.kind ? rule : current,
      ],
    ),
  );
  Future<bool> setPrivacy(bool value) =>
      _change((s) => s.copyWith(hidePreview: value));
  Future<bool> setQuiet({bool? enabled, int? start, int? end}) => _change(
    (s) => s.copyWith(quietEnabled: enabled, quietStart: start, quietEnd: end),
  );

  Future<bool> _change(
    LocalReminderSettings Function(LocalReminderSettings) transform, {
    bool request = false,
  }) async {
    if (busy || !loaded || _owner == null) return false;
    final expectedOwner = _owner;
    return _serial(() async {
      if (_owner != expectedOwner || !loaded) return false;
      busy = true;
      errorMessage = null;
      message = null;
      notifyListeners();
      var saved = false;
      try {
        if (request) {
          permission = await platform.requestPermission();
          if (_owner != expectedOwner) return false;
          if (permission != ReminderPermission.allowed) {
            errorMessage = permission == ReminderPermission.channelBlocked
                ? '日常记录提醒已被系统关闭，请到系统设置中开启'
                : '尚未获准发送系统通知，提醒总开关保持关闭';
            return false;
          }
        }
        final next = transform(settings);
        ReminderPlanner.build(next, expectedOwner!, deviceLocation!, _now());
        await _store.write(
          'reminders.$expectedOwner',
          jsonEncode(next.toJson()),
        );
        if (_owner != expectedOwner) return false;
        saved = true;
        settings = next;
        _lastApplied = null;
        await _reconcile();
        message = next.enabled ? '提醒设置已保存' : '本机系统提醒已关闭，已取消待提醒任务';
        return true;
      } on FormatException catch (e) {
        errorMessage = e.message;
        return false;
      } on Object {
        _lastApplied = null;
        if (saved) {
          try {
            await platform.cancelManaged();
            scheduledIds = {};
          } on Object {
            /* Retry on resume. */
          }
        }
        errorMessage = saved ? '设置已保存，但提醒尚未完全安排，请重试' : '本机保存失败，原提醒设置继续生效，请重试';
        return false;
      } finally {
        busy = false;
        _deliverWaitingTap();
        notifyListeners();
      }
    });
  }

  Future<void> _reconcile() async {
    final expectedOwner = _owner;
    if (expectedOwner == null) return;
    permission = await platform.permission();
    deviceLocation = await platform.location();
    if (_owner != expectedOwner) return;
    final desired = ReminderPlanner.build(
      settings,
      expectedOwner,
      deviceLocation!,
      _now(),
    );
    planned = desired;
    scheduledIds = await platform.pendingIds();
    final signature =
        '$expectedOwner|${deviceLocation!.name}|${jsonEncode(settings.toJson())}|${permission.name}';
    final desiredIds = desired.map((v) => v.id).toSet();
    final actualIds = scheduledIds
        .where((id) => id != ReminderPlanner.testId)
        .toSet();
    final same =
        desiredIds.length == actualIds.length &&
        desiredIds.containsAll(actualIds);
    if (_lastApplied == signature && same) return;
    await platform.cancelManaged();
    scheduledIds = {};
    if (_owner != expectedOwner) return;
    if (permission == ReminderPermission.allowed && settings.enabled) {
      for (final entry in desired) {
        if (_owner != expectedOwner) return;
        await platform.schedule(entry);
      }
      await _store.write('reminders.active', expectedOwner);
    } else {
      _lastApplied = null;
      await _store.delete('reminders.active');
    }
    if (_owner != expectedOwner) return;
    scheduledIds = await platform.pendingIds();
    if (settings.enabled &&
        permission == ReminderPermission.allowed &&
        !scheduledIds.containsAll(desiredIds)) {
      throw StateError('Incomplete schedule');
    }
    _lastApplied = signature;
    errorMessage = null;
  }

  Future<bool> test(
    ReminderKind kind, {
    Duration delay = const Duration(seconds: 10),
  }) async {
    if (busy || !loaded || _owner == null) return false;
    return _serial(() async {
      busy = true;
      errorMessage = null;
      message = null;
      notifyListeners();
      final expectedOwner = _owner;
      try {
        permission = await platform.permission();
        if (!settings.enabled || permission != ReminderPermission.allowed) {
          errorMessage = '请先开启提醒总开关，并允许系统通知';
          return false;
        }
        if (!settings.rules.any((r) => r.kind == kind && r.enabled)) {
          errorMessage = '请先开启这类提醒，再发送测试';
          return false;
        }
        final location = await platform.location();
        final at = tz.TZDateTime.from(_now().add(delay), location);
        if (settings.isQuiet(at.hour * 60 + at.minute)) {
          errorMessage = '测试时间处于免打扰时段，请调整时间后再测试';
          return false;
        }
        if (_owner != expectedOwner) return false;
        await platform.schedule(
          ScheduledReminder(
            id: ReminderPlanner.testId,
            kind: kind,
            at: at,
            payload: ReminderPlanner.payload(expectedOwner!, kind),
            hidePreview: settings.hidePreview,
            repeat: false,
          ),
        );
        scheduledIds = await platform.pendingIds();
        if (!scheduledIds.contains(ReminderPlanner.testId)) {
          throw StateError('Test not scheduled');
        }
        message = '测试提醒已安排，约 10 秒后查看通知栏，系统可能延后；点击可进入${kind.label}页面';
        return true;
      } on Object {
        errorMessage = '测试提醒安排失败，请核对系统通知权限后重试';
        return false;
      } finally {
        busy = false;
        _deliverWaitingTap();
        notifyListeners();
      }
    });
  }

  Future<void> openSystemSettings() async {
    try {
      await platform.openSettings();
    } on Object {
      errorMessage = '无法直接打开系统设置，请在手机设置中找到 NxtRep 的通知权限';
      notifyListeners();
    }
  }

  void _captureTap(String payload) {
    _waitingPayload = payload;
    if (!busy) _deliverWaitingTap();
  }

  void _deliverWaitingTap() {
    final raw = _waitingPayload;
    if (raw == null || _owner == null || !loaded) return;
    _waitingPayload = null;
    try {
      final data = jsonDecode(raw) as Map;
      if (data['feature'] != 'local_reminder' ||
          data['version'] != 1 ||
          data['owner'] != _owner ||
          !settings.enabled) {
        return;
      }
      final kind = ReminderKind.values.byName(data['kind'] as String);
      if (!settings.rules.any((r) => r.kind == kind && r.enabled)) return;
      _navigation = kind;
      notifyListeners();
    } on Object {
      /* Ignore malformed or stale launch data. */
    }
  }

  ReminderKind? takeNavigation() {
    final result = _navigation;
    _navigation = null;
    return result;
  }
}
