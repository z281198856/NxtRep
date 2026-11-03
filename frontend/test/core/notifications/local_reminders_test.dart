import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:timezone/data/latest.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;
import 'package:nxtrep/core/notifications/reminder_controller.dart';
import 'package:nxtrep/core/notifications/reminder_models.dart';
import 'package:nxtrep/core/notifications/reminder_platform.dart';
import 'package:nxtrep/core/offline/local_records.dart';
import 'package:nxtrep/features/profile/presentation/local_reminders_page.dart';

class _Store implements LocalDataStore {
  final values = <String, String>{};
  bool failWrite = false;
  @override
  Future<String?> read(String key) async => values[key];
  @override
  Future<void> write(String key, String value) async {
    if (failWrite) throw StateError('disk');
    values[key] = value;
  }

  @override
  Future<void> delete(String key) async => values.remove(key);
}

class _Platform implements ReminderPlatform {
  final scheduled = <int, ScheduledReminder>{};
  final delivered = <int>{};
  ReminderPermission status = ReminderPermission.allowed;
  int permissionRequests = 0,
      cancels = 0,
      initializeCalls = 0,
      openedSettings = 0;
  int? failAfter;
  bool failInit = false;
  String zone = 'Asia/Shanghai';
  String? launch;
  void Function(String)? onTap;
  Completer<void>? permissionGate, statusGate;
  @override
  Future<String?> initialize(void Function(String) tap) async {
    initializeCalls++;
    if (failInit) {
      failInit = false;
      throw StateError('native init');
    }
    onTap = tap;
    return launch;
  }

  @override
  Future<ReminderPermission> permission() async {
    await statusGate?.future;
    return status;
  }

  @override
  Future<ReminderPermission> requestPermission() async {
    permissionRequests++;
    await permissionGate?.future;
    return status;
  }

  @override
  Future<tz.Location> location() async => tz.getLocation(zone);
  @override
  Future<void> cancelManaged() async {
    cancels++;
    scheduled.clear();
    delivered.clear();
  }

  @override
  Future<void> schedule(ScheduledReminder value) async {
    if (failAfter != null && scheduled.length >= failAfter!) {
      throw StateError('native scheduling');
    }
    scheduled[value.id] = value;
  }

  @override
  Future<Set<int>> pendingIds() async => scheduled.keys.toSet();
  @override
  Future<void> openSettings() async {
    openedSettings++;
  }
}

LocalReminderSettings _enabled({
  List<int> times = const [1080],
  List<int> days = const [1, 3, 5],
}) {
  final base = LocalReminderSettings.defaults();
  return base.copyWith(
    enabled: true,
    rules: [
      for (final r in base.rules)
        r.kind == ReminderKind.training
            ? r.copyWith(enabled: true, times: times, weekdays: days)
            : r,
    ],
  );
}

void main() {
  setUpAll(tzdata.initializeTimeZones);
  final now = DateTime.utc(2026, 11, 2, 1); // Monday 09:00 in Shanghai.

  testWidgets(
    'native timezone aliases GMT, UTC and US/Eastern resolve after initialization',
    (tester) async {
      const native = MethodChannel('dexterous.com/flutter/local_notifications');
      const timezone = MethodChannel('flutter_timezone');
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(
        native,
        (call) async => call.method == 'initialize' ? true : null,
      );
      var identifier = 'GMT';
      messenger.setMockMethodCallHandler(
        timezone,
        (call) async => {'identifier': identifier},
      );
      addTearDown(() {
        messenger.setMockMethodCallHandler(native, null);
        messenger.setMockMethodCallHandler(timezone, null);
      });
      AndroidFlutterLocalNotificationsPlugin.registerWith();
      final platform = FlutterReminderPlatform();
      await platform.initialize((_) {});
      for (final name in ['GMT', 'UTC', 'US/Eastern']) {
        identifier = name;
        final location = await platform.location();
        expect(location.name, name);
      }
    },
  );

  test(
    'planner produces stable IDs, next selected days and no past alarms',
    () {
      final zone = tz.getLocation('Asia/Shanghai');
      final first = ReminderPlanner.build(_enabled(), 'owner', zone, now);
      expect(first.map((e) => e.at.weekday), [1, 3, 5]);
      expect(first.first.at.hour, 18);
      expect(first.every((e) => e.at.isAfter(now)), isTrue);
      expect(first.map((e) => e.id).toSet().length, 3);
      expect(
        ReminderPlanner.build(_enabled(), 'owner', zone, now).map((e) => e.id),
        first.map((e) => e.id),
      );
      final after = ReminderPlanner.build(
        _enabled(),
        'owner',
        zone,
        now.add(const Duration(hours: 10)),
      );
      expect(after.first.at.weekday, 3);
    },
  );

  test(
    'daily schedule is one repeating request; DST keeps next local clock time',
    () {
      final zone = tz.getLocation('America/New_York');
      final before = tz.TZDateTime(zone, 2026, 3, 7, 10);
      final result = ReminderPlanner.build(
        _enabled(times: [540], days: [1, 2, 3, 4, 5, 6, 7]),
        'owner',
        zone,
        before,
      );
      expect(result.length, 1);
      expect(result.single.weekly, isFalse);
      expect(result.single.at.hour, 9);
      expect(result.single.at.difference(before).inHours, 22);
    },
  );

  test('quiet hours wrap midnight, end boundary is allowed and blocked times are skipped', () {
    final settings = _enabled(times: [1380, 480, 420]);
    expect(settings.isQuiet(1380), isTrue);
    expect(settings.isQuiet(420), isTrue);
    expect(settings.isQuiet(480), isFalse);
    final result = ReminderPlanner.build(
      settings,
      'owner',
      tz.getLocation('Asia/Shanghai'),
      now,
    );
    expect(result.length, 3);
    expect(result.every((r) => r.at.hour == 8), isTrue);
    expect(
      ReminderPlanner.build(
        settings.copyWith(enabled: false),
        'owner',
        tz.UTC,
        now,
      ),
      isEmpty,
    );
  });

  test('invalid or duplicate times, weekdays and all-day quiet period are rejected', () {
    expect(() => _enabled(times: [1080, 1080]), throwsFormatException);
    expect(() => _enabled(days: []), throwsFormatException);
    expect(() => _enabled(times: [1440]), throwsFormatException);
    expect(
      () => _enabled().copyWith(quietStart: 480, quietEnd: 480),
      throwsFormatException,
    );
  });

  test('too many pending requests are rejected before the iOS limit, not silently dropped', () {
    final base = LocalReminderSettings.defaults();
    final full = base.copyWith(
      enabled: true,
      quietEnabled: false,
      rules: [
        for (final r in base.rules)
          r.copyWith(
            enabled: true,
            times: r.kind == ReminderKind.water
                ? [480, 600, 720, 840, 960, 1080]
                : r.times,
            weekdays: [1, 2, 3, 4, 5, 6],
          ),
      ],
    );
    expect(
      () => ReminderPlanner.build(full, 'owner', tz.UTC, now),
      throwsFormatException,
    );
    final daily = full.copyWith(
      rules: [
        for (final r in full.rules) r.copyWith(weekdays: [1, 2, 3, 4, 5, 6, 7]),
      ],
    );
    expect(
      ReminderPlanner.build(daily, 'owner', tz.UTC, now).length,
      lessThan(64),
    );
  });

  test(
    'activating account does not ask permission; denial never enables master',
    () async {
      final store = _Store();
      final platform = _Platform()..status = ReminderPermission.denied;
      final controller = LocalReminderController(
        store,
        platform,
        now: () => now,
      );
      addTearDown(controller.dispose);
      await controller.activate('server', 'alice');
      expect(platform.permissionRequests, 0);
      expect(await controller.setEnabled(true), isFalse);
      expect(controller.settings.enabled, isFalse);
      expect(platform.scheduled, isEmpty);
      expect(controller.errorMessage, contains('尚未获准'));
    },
  );

  test('channel blocked is distinguished from app permission denial', () async {
    final platform = _Platform()..status = ReminderPermission.channelBlocked;
    final controller = LocalReminderController(
      _Store(),
      platform,
      now: () => now,
    );
    addTearDown(controller.dispose);
    await controller.activate('server', 'alice');
    expect(await controller.setEnabled(true), isFalse);
    expect(controller.errorMessage, contains('系统关闭'));
  });

  test('saving repeatedly does not duplicate IDs; unchanged resume does not re-alert', () async {
    final platform = _Platform();
    final controller = LocalReminderController(
      _Store(),
      platform,
      now: () => now,
    );
    addTearDown(controller.dispose);
    await controller.activate('server', 'alice');
    await controller.setEnabled(true);
    final rule = controller.settings.rules.first.copyWith(enabled: true);
    await controller.setRule(rule);
    await controller.setRule(rule);
    expect(controller.scheduledCount, 3);
    final cancels = platform.cancels;
    await controller.refresh();
    expect(platform.cancels, cancels);
  });

  test('permission revoked cancels alarms and re-grant resumes the saved configuration', () async {
    final platform = _Platform();
    final controller = LocalReminderController(
      _Store(),
      platform,
      now: () => now,
    );
    addTearDown(controller.dispose);
    await controller.activate('server', 'alice');
    await controller.setEnabled(true);
    await controller.setRule(
      controller.settings.rules.first.copyWith(enabled: true),
    );
    platform.status = ReminderPermission.denied;
    await controller.refresh();
    expect(platform.scheduled, isEmpty);
    expect(controller.settings.enabled, isTrue);
    platform.status = ReminderPermission.allowed;
    await controller.refresh();
    expect(controller.scheduledCount, 3);
  });

  test('logout cancels pending and delivered reminders; account and server settings are isolated', () async {
    final store = _Store();
    final platform = _Platform();
    final controller = LocalReminderController(store, platform, now: () => now);
    addTearDown(controller.dispose);
    await controller.activate('server', 'alice');
    await controller.setEnabled(true);
    await controller.setRule(
      controller.settings.rules.first.copyWith(enabled: true),
    );
    platform.delivered.add(30001);
    await controller.deactivate();
    expect(platform.scheduled, isEmpty);
    expect(platform.delivered, isEmpty);
    await controller.activate('server', 'bob');
    expect(controller.settings.enabled, isFalse);
    await controller.activate('other-server', 'alice');
    expect(controller.settings.enabled, isFalse);
    await controller.activate('server', 'alice');
    expect(controller.scheduledCount, 3);
  });

  test(
    'logout while permission prompt is pending prevents late scheduling',
    () async {
      final platform = _Platform()..permissionGate = Completer<void>();
      final controller = LocalReminderController(
        _Store(),
        platform,
        now: () => now,
      );
      addTearDown(controller.dispose);
      await controller.activate('server', 'alice');
      final enabling = controller.setEnabled(true);
      await Future<void>.delayed(Duration.zero);
      final logout = controller.deactivate();
      platform.permissionGate!.complete();
      expect(await enabling, isFalse);
      await logout;
      expect(controller.owner, isNull);
      expect(platform.scheduled, isEmpty);
    },
  );

  test('storage failure retains old settings; partial native schedule is cancelled and reported', () async {
    final store = _Store();
    final platform = _Platform();
    final controller = LocalReminderController(store, platform, now: () => now);
    addTearDown(controller.dispose);
    await controller.activate('server', 'alice');
    store.failWrite = true;
    expect(await controller.setEnabled(true), isFalse);
    expect(controller.settings.enabled, isFalse);
    expect(platform.scheduled, isEmpty);
    store.failWrite = false;
    await controller.setEnabled(true);
    platform.failAfter = 1;
    expect(
      await controller.setRule(
        controller.settings.rules.first.copyWith(enabled: true),
      ),
      isFalse,
    );
    expect(controller.errorMessage, contains('尚未完全安排'));
    expect(platform.scheduled, isEmpty);
    platform.failAfter = null;
    await controller.refresh(force: true);
    expect(controller.scheduledCount, 3);
  });

  test('native initialization can be retried; corrupt preferences are not overwritten', () async {
    final store = _Store();
    final platform = _Platform()..failInit = true;
    final controller = LocalReminderController(store, platform, now: () => now);
    addTearDown(controller.dispose);
    await controller.activate('server', 'alice');
    expect(controller.loaded, isFalse);
    await controller.refresh();
    expect(controller.loaded, isTrue);
    final key = 'reminders.${ReminderPlanner.ownerFor('server', 'bob')}';
    store.values[key] = '{broken';
    await controller.activate('server', 'bob');
    expect(controller.loaded, isFalse);
    expect(store.values[key], '{broken');
  });

  test(
    'cold-start tap waits for the matching account and navigates only once',
    () async {
      final store = _Store();
      final platform = _Platform();
      final owner = ReminderPlanner.ownerFor('server', 'alice');
      store.values['reminders.$owner'] = jsonEncode(_enabled().toJson());
      platform.launch = ReminderPlanner.payload(owner, ReminderKind.training);
      final controller = LocalReminderController(
        store,
        platform,
        now: () => now,
      );
      addTearDown(controller.dispose);
      await controller.activate('server', 'alice');
      expect(controller.takeNavigation(), ReminderKind.training);
      expect(controller.takeNavigation(), isNull);
      platform.onTap!(
        ReminderPlanner.payload(
          ReminderPlanner.ownerFor('server', 'bob'),
          ReminderKind.training,
        ),
      );
      expect(controller.takeNavigation(), isNull);
      await controller.setRule(
        controller.settings.rules.first.copyWith(enabled: false),
      );
      platform.onTap!(ReminderPlanner.payload(owner, ReminderKind.training));
      expect(controller.takeNavigation(), isNull);
    },
  );

  test(
    'warm tap during a resume refresh is delivered once after refresh',
    () async {
      final platform = _Platform();
      final controller = LocalReminderController(
        _Store(),
        platform,
        now: () => now,
      );
      addTearDown(controller.dispose);
      await controller.activate('server', 'alice');
      await controller.setEnabled(true);
      await controller.setRule(
        controller.settings.rules.first.copyWith(enabled: true),
      );
      platform.statusGate = Completer<void>();
      final refresh = controller.refresh();
      await Future<void>.delayed(Duration.zero);
      expect(controller.busy, isTrue);
      platform.onTap!(
        ReminderPlanner.payload(controller.owner!, ReminderKind.training),
      );
      expect(controller.takeNavigation(), isNull);
      platform.statusGate!.complete();
      await refresh;
      expect(controller.takeNavigation(), ReminderKind.training);
      expect(controller.takeNavigation(), isNull);
    },
  );

  test('test notification respects quiet hours, replaces its ID, and disabling cancels it', () async {
    final platform = _Platform();
    var clock = now;
    final controller = LocalReminderController(
      _Store(),
      platform,
      now: () => clock,
    );
    addTearDown(controller.dispose);
    await controller.activate('server', 'alice');
    await controller.setEnabled(true);
    await controller.setRule(
      controller.settings.rules.first.copyWith(enabled: true),
    );
    expect(await controller.test(ReminderKind.training), isTrue);
    expect(await controller.test(ReminderKind.training), isTrue);
    expect(
      platform.scheduled.keys
          .where((id) => id == ReminderPlanner.testId)
          .length,
      1,
    );
    clock = DateTime.utc(2026, 11, 2, 15); // 23:00 Shanghai.
    expect(await controller.test(ReminderKind.training), isFalse);
    await controller.setEnabled(false);
    expect(platform.scheduled, isEmpty);
  });

  testWidgets(
    'notification page shows denial and keeps the master off, then schedules selected type',
    (tester) async {
      final platform = _Platform()..status = ReminderPermission.denied;
      final controller = LocalReminderController(
        _Store(),
        platform,
        now: () => now,
      );
      addTearDown(controller.dispose);
      await controller.activate('server', 'alice');
      await tester.pumpWidget(
        MaterialApp(home: LocalRemindersPage(controller: controller)),
      );
      await tester.tap(find.byKey(const ValueKey('reminder-master')));
      await tester.pumpAndSettle();
      expect(controller.settings.enabled, isFalse);
      expect(find.textContaining('尚未获准'), findsOneWidget);
      platform.status = ReminderPermission.allowed;
      await tester.tap(find.byKey(const ValueKey('reminder-master')));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.byKey(const ValueKey('reminder-training')),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.byKey(const ValueKey('reminder-training')));
      await tester.pumpAndSettle();
      expect(controller.scheduledCount, 3);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
