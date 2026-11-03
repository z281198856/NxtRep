import 'package:flutter/material.dart';

import '../../../core/notifications/reminder_controller.dart';
import '../../../core/notifications/reminder_models.dart';
import '../../../core/notifications/reminder_platform.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';

class LocalRemindersPage extends StatelessWidget {
  const LocalRemindersPage({super.key, required this.controller});
  final LocalReminderController controller;

  Future<int?> _pick(BuildContext context, int minute) async {
    final selected = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: minute ~/ 60, minute: minute % 60),
      initialEntryMode: TimePickerEntryMode.input,
      helpText: '选择提醒时间',
      cancelText: '取消',
      confirmText: '确定',
      hourLabelText: '小时',
      minuteLabelText: '分钟',
      errorInvalidText: '请输入有效时间',
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(alwaysUse24HourFormat: true),
        child: child!,
      ),
    );
    return selected == null ? null : selected.hour * 60 + selected.minute;
  }

  void _hint(BuildContext context, String message) =>
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));

  Future<void> _editTime(
    BuildContext context,
    ReminderRule rule,
    int? slot,
  ) async {
    final now = TimeOfDay.now();
    final value = await _pick(
      context,
      slot == null ? now.hour * 60 + now.minute : rule.times[slot],
    );
    if (value == null || !context.mounted) return;
    if (rule.times.asMap().entries.any(
      (e) => e.key != slot && e.value == value,
    )) {
      _hint(context, '这个时间已经有提醒了');
      return;
    }
    final times = rule.times.toList();
    if (slot == null) {
      times.add(value);
    } else {
      times[slot] = value;
    }
    times.sort();
    await controller.setRule(rule.copyWith(times: times));
  }

  Future<void> _test(BuildContext context) async {
    final rules = controller.settings.rules.where((r) => r.enabled).toList();
    if (rules.isEmpty) {
      _hint(context, '先开启一类提醒，再发送测试');
      return;
    }
    final kind = await showDialog<ReminderKind>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('测试哪类提醒？'),
        children: [
          for (final rule in rules)
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, rule.kind),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(rule.kind.label),
              ),
            ),
        ],
      ),
    );
    if (kind != null) await controller.test(kind);
  }

  Widget _rule(BuildContext context, ReminderRule rule) {
    final editable = !controller.busy && controller.loaded;
    return AppSurface(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            title: Text('${rule.kind.label}提醒'),
            subtitle: const Text('按所选星期和时间重复提醒'),
            value: rule.enabled,
            key: ValueKey('reminder-${rule.kind.name}'),
            onChanged: editable
                ? (value) => controller.setRule(rule.copyWith(enabled: value))
                : null,
          ),
          if (rule.enabled) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 7,
              runSpacing: 7,
              children: [
                for (var i = 0; i < rule.times.length; i++)
                  InputChip(
                    label: Text(reminderTime(rule.times[i])),
                    onPressed: editable
                        ? () => _editTime(context, rule, i)
                        : null,
                    onDeleted: editable && rule.times.length > 1
                        ? () => controller.setRule(
                            rule.copyWith(
                              times: rule.times.toList()..removeAt(i),
                            ),
                          )
                        : null,
                  ),
                if (rule.kind == ReminderKind.water && rule.times.length < 6)
                  ActionChip(
                    label: const Text('添加时间'),
                    avatar: const Icon(Icons.add, size: 16),
                    onPressed: editable
                        ? () => _editTime(context, rule, null)
                        : null,
                  ),
              ],
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 5,
              runSpacing: 5,
              children: [
                for (var day = 1; day <= 7; day++)
                  FilterChip(
                    label: Text(
                      '周${['一', '二', '三', '四', '五', '六', '日'][day - 1]}',
                    ),
                    selected: rule.weekdays.contains(day),
                    onSelected: editable
                        ? (selected) {
                            final days = rule.weekdays.toSet();
                            if (selected) {
                              days.add(day);
                            } else {
                              days.remove(day);
                            }
                            if (days.isEmpty) {
                              _hint(context, '至少保留一天');
                              return;
                            }
                            controller.setRule(
                              rule.copyWith(weekdays: days.toList()..sort()),
                            );
                          }
                        : null,
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('手机系统提醒')),
    body: ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final settings = controller.settings;
        final allowed = controller.permission == ReminderPermission.allowed;
        final permissionLabel = switch (controller.permission) {
          ReminderPermission.allowed => '系统已允许通知',
          ReminderPermission.denied => '系统尚未允许通知',
          ReminderPermission.channelBlocked => '日常提醒通知渠道已关闭',
          ReminderPermission.unsupported => '当前平台暂不支持手机提醒',
        };
        return ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
          children: [
            AppSurface(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    permissionLabel,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 6),
                  Text(
                    '已安排 ${controller.scheduledCount} 项重复提醒',
                    key: const ValueKey('reminder-schedule-count'),
                  ),
                  if (controller.deviceLocation != null)
                    Text('按手机时区：${controller.deviceLocation!.name}'),
                  if (!allowed)
                    TextButton(
                      onPressed: controller.busy
                          ? null
                          : controller.openSystemSettings,
                      child: const Text('前往系统通知设置'),
                    ),
                  SwitchListTile.adaptive(
                    contentPadding: EdgeInsets.zero,
                    key: const ValueKey('reminder-master'),
                    title: const Text('开启本机系统提醒'),
                    subtitle: const Text('设置保存在本机，按当前账户分别管理'),
                    value: settings.enabled,
                    onChanged: controller.busy || !controller.loaded
                        ? null
                        : controller.setEnabled,
                  ),
                  if (settings.enabled && !settings.rules.any((r) => r.enabled))
                    const Text('再开启下方需要的提醒类型。'),
                ],
              ),
            ),
            if (controller.errorMessage case final error?) ...[
              const SizedBox(height: 12),
              AppErrorCard(message: error),
              TextButton(
                onPressed: controller.busy
                    ? null
                    : () => controller.refresh(force: true),
                child: const Text('重试安排'),
              ),
            ],
            if (controller.message case final message?) ...[
              const SizedBox(height: 10),
              Text(message, style: const TextStyle(color: AppColors.primary)),
            ],
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: controller.busy || !settings.enabled || !allowed
                  ? null
                  : () => _test(context),
              icon: const Icon(Icons.notifications_active_outlined),
              label: const Text('发送测试提醒'),
            ),
            const SizedBox(height: 8),
            const Text('测试约 10 秒后提醒，可先回到桌面等待。点击通知会打开对应页面；系统可能因省电或免打扰延后。'),
            const SizedBox(height: 22),
            const SectionTitle(title: '提醒类型与时间'),
            const SizedBox(height: 10),
            for (final rule in settings.rules) ...[
              _rule(context, rule),
              const SizedBox(height: 12),
            ],
            AppSurface(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SwitchListTile.adaptive(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('免打扰时段'),
                    value: settings.quietEnabled,
                    onChanged: controller.busy
                        ? null
                        : (value) => controller.setQuiet(enabled: value),
                  ),
                  if (settings.quietEnabled) ...[
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton(
                            onPressed: controller.busy
                                ? null
                                : () async {
                                    final value = await _pick(
                                      context,
                                      settings.quietStart,
                                    );
                                    if (value != null) {
                                      await controller.setQuiet(start: value);
                                    }
                                  },
                            child: Text(
                              '开始 ${reminderTime(settings.quietStart)}',
                            ),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: OutlinedButton(
                            onPressed: controller.busy
                                ? null
                                : () async {
                                    final value = await _pick(
                                      context,
                                      settings.quietEnd,
                                    );
                                    if (value != null) {
                                      await controller.setQuiet(end: value);
                                    }
                                  },
                            child: Text(
                              '结束 ${reminderTime(settings.quietEnd)}',
                            ),
                          ),
                        ),
                      ],
                    ),
                    const Text('落在免打扰时段内的时间不安排提醒。'),
                    if (controller.skippedTimes > 0)
                      Text('已有 ${controller.skippedTimes} 个时间因免打扰被跳过。'),
                  ],
                  const Divider(height: 24),
                  SwitchListTile.adaptive(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('通知中隐藏提醒内容'),
                    subtitle: const Text('只显示通用提醒，点开后查看'),
                    value: settings.hidePreview,
                    onChanged: controller.busy ? null : controller.setPrivacy,
                  ),
                ],
              ),
            ),
            if (controller.planned.isNotEmpty && settings.enabled) ...[
              const SizedBox(height: 20),
              const SectionTitle(title: '接下来的提醒'),
              for (final entry in controller.planned.take(5))
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(entry.kind.label),
                  subtitle: Text(
                    '${entry.at.month}月${entry.at.day}日 ${reminderTime(entry.at.hour * 60 + entry.at.minute)}',
                  ),
                ),
            ],
            const SizedBox(height: 16),
            const Text(
              '提醒只按你设置的时间安排，记录仍由你确认。更改手机时区后重新打开 App 可更新安排。系统设置中强行停止 App 后，需要重新打开才能恢复提醒。',
            ),
          ],
        );
      },
    ),
  );
}
