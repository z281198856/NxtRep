import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;
import 'package:url_launcher/url_launcher.dart';

import 'reminder_models.dart';

enum ReminderPermission { allowed, denied, channelBlocked, unsupported }

abstract interface class ReminderPlatform {
  Future<String?> initialize(void Function(String payload) onTap);
  Future<ReminderPermission> permission();
  Future<ReminderPermission> requestPermission();
  Future<tz.Location> location();
  Future<void> cancelManaged();
  Future<void> schedule(ScheduledReminder reminder);
  Future<Set<int>> pendingIds();
  Future<void> openSettings();
}

class FlutterReminderPlatform implements ReminderPlatform {
  FlutterReminderPlatform({FlutterLocalNotificationsPlugin? plugin})
    : _plugin = plugin ?? FlutterLocalNotificationsPlugin();
  final FlutterLocalNotificationsPlugin _plugin;
  static const channelId = 'nxtrep_local_reminders_v1';
  static const _channel = AndroidNotificationChannel(
    channelId,
    '日常记录提醒',
    description: '你设置的训练、饮食、饮水和身体数据定时提醒',
  );
  bool get _android =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
  bool get _ios => !kIsWeb && defaultTargetPlatform == TargetPlatform.iOS;

  @override
  Future<String?> initialize(void Function(String payload) onTap) async {
    if (!_android && !_ios) return null;
    tzdata.initializeTimeZones();
    await _plugin.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('ic_stat_nxtrep'),
        iOS: DarwinInitializationSettings(
          requestAlertPermission: false,
          requestSoundPermission: false,
          requestBadgePermission: false,
        ),
      ),
      onDidReceiveNotificationResponse: (response) {
        if (response.payload case final payload?) onTap(payload);
      },
    );
    if (_android) {
      await _plugin
          .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin
          >()!
          .createNotificationChannel(_channel);
    }
    final launch = await _plugin.getNotificationAppLaunchDetails();
    return launch?.didNotificationLaunchApp == true
        ? launch?.notificationResponse?.payload
        : null;
  }

  @override
  Future<ReminderPermission> permission() async {
    if (_android) {
      final platform = _plugin
          .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin
          >()!;
      if (await platform.areNotificationsEnabled() != true) {
        return ReminderPermission.denied;
      }
      final channels = await platform.getNotificationChannels();
      if (channels?.any(
            (c) => c.id == channelId && c.importance == Importance.none,
          ) ==
          true) {
        return ReminderPermission.channelBlocked;
      }
      return ReminderPermission.allowed;
    }
    if (_ios) {
      final result = await _plugin
          .resolvePlatformSpecificImplementation<
            IOSFlutterLocalNotificationsPlugin
          >()!
          .checkPermissions();
      return result?.isAlertEnabled == true ||
              result?.isProvisionalEnabled == true
          ? ReminderPermission.allowed
          : ReminderPermission.denied;
    }
    return ReminderPermission.unsupported;
  }

  @override
  Future<ReminderPermission> requestPermission() async {
    if (await permission() == ReminderPermission.allowed) {
      return ReminderPermission.allowed;
    }
    if (_android) {
      await _plugin
          .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin
          >()!
          .requestNotificationsPermission();
    }
    if (_ios) {
      await _plugin
          .resolvePlatformSpecificImplementation<
            IOSFlutterLocalNotificationsPlugin
          >()!
          .requestPermissions(alert: true, sound: true, badge: false);
    }
    return permission();
  }

  @override
  Future<tz.Location> location() async =>
      tz.getLocation((await FlutterTimezone.getLocalTimezone()).identifier);

  @override
  Future<void> cancelManaged() async {
    if (!_android && !_ios) return;
    final ids = (await pendingIds()).toSet();
    for (final active in await _plugin.getActiveNotifications()) {
      if (active.id case final id? when ReminderPlanner.ownsId(id)) ids.add(id);
    }
    // The fixed test ID is also cancelled when it has just fired.
    ids.add(ReminderPlanner.testId);
    for (final id in ids) {
      await _plugin.cancel(id: id);
    }
  }

  @override
  Future<void> schedule(ScheduledReminder reminder) async {
    await _plugin.zonedSchedule(
      id: reminder.id,
      scheduledDate: reminder.at,
      title: reminder.hidePreview ? 'NxtRep 提醒' : '${reminder.kind.label}提醒',
      body: reminder.hidePreview ? '你设置的提醒时间到了，点按查看。' : reminder.kind.body,
      payload: reminder.payload,
      notificationDetails: const NotificationDetails(
        android: AndroidNotificationDetails(
          channelId,
          '日常记录提醒',
          channelDescription: '你设置的训练、饮食、饮水和身体数据定时提醒',
          icon: 'ic_stat_nxtrep',
          visibility: NotificationVisibility.private,
        ),
        iOS: DarwinNotificationDetails(
          presentAlert: true,
          presentSound: true,
          presentBadge: false,
          threadIdentifier: 'nxtrep-local-reminders',
        ),
      ),
      androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      matchDateTimeComponents: !reminder.repeat
          ? null
          : reminder.weekly
          ? DateTimeComponents.dayOfWeekAndTime
          : DateTimeComponents.time,
    );
  }

  @override
  Future<Set<int>> pendingIds() async {
    if (!_android && !_ios) return {};
    return (await _plugin.pendingNotificationRequests())
        .map((v) => v.id)
        .where(ReminderPlanner.ownsId)
        .toSet();
  }

  @override
  Future<void> openSettings() async {
    if (_android) {
      await const MethodChannel('nxtrep/system_reminders')
          .invokeMethod<void>('openNotificationSettings');
    } else if (_ios) {
      if (!await launchUrl(
        Uri.parse('app-settings:'),
        mode: LaunchMode.externalApplication,
      )) {
        throw StateError('无法打开系统设置');
      }
    }
  }
}
